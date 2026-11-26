"""Log and traceback parsing utilities for Python and other runtimes."""

from __future__ import annotations

import re

from bugarena.models.bug import FaultTrace

FRAME_PATTERN = re.compile(
    r'File\s+["\'](?P<file>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>[^\r\n]+))?',
    re.IGNORECASE,
)

EXCEPTION_PATTERN = re.compile(
    r"^(?P<type>(?:[A-Za-z_]\w*\.)*"
    r"(?:[A-Z]\w*(?:Error|Exception|Warning|Fault|Interrupt|Exit|Failure)|StopIteration|StopAsyncIteration|GeneratorExit|SystemExit|KeyboardInterrupt))"
    r"(?::\s*(?P<msg>.*))?$"
)

CHAIN_SEPARATOR_RE = re.compile(
    r"^(?:Traceback \(most recent call last\):|"
    r"The above exception was the direct cause of the following exception:|"
    r"During handling of the above exception, another exception occurred:)$"
)


def _split_traceback_blocks(lines: list[str]) -> list[list[str]]:
    """Split concatenated/chained tracebacks into separate blocks."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if CHAIN_SEPARATOR_RE.match(stripped):
            if current and any(FRAME_PATTERN.search(line) for line in current):
                blocks.append(current)
                current = []
            continue
        current.append(raw)
    if current:
        blocks.append(current)
    return blocks or [lines]


def _parse_single_block(lines: list[str]) -> list[FaultTrace]:
    error_message = "UnknownError"
    for line in reversed(lines):
        line_clean = line.strip()
        if not line_clean or line_clean.startswith("File "):
            continue
        if EXCEPTION_PATTERN.match(line_clean):
            error_message = line_clean
            break

    traces: list[FaultTrace] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = FRAME_PATTERN.search(line)
        if match:
            file_path = match.group("file").replace("\\", "/")
            line_num = int(match.group("line"))
            func_name = (match.group("func") or "<module>").strip()

            code_lines = []
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                if (
                    FRAME_PATTERN.search(next_line)
                    or EXCEPTION_PATTERN.match(next_line)
                    or CHAIN_SEPARATOR_RE.match(next_line)
                ):
                    break
                if next_line and not re.match(r"^[\^~ \t\-=]+$", next_line):
                    code_lines.append(next_line)
                i += 1

            code_snippet = "\n".join(code_lines) if code_lines else line
            traces.append(
                FaultTrace(
                    file_path=file_path,
                    line_number=line_num,
                    function_name=func_name,
                    code=code_snippet,
                    error_message=error_message,
                )
            )
        else:
            i += 1
    return traces


def parse_python_traceback(error_log: str) -> list[FaultTrace]:
    """
    Parse one or more chained Python runtime tracebacks into structured FaultTrace objects.
    """
    if not error_log or not error_log.strip():
        return []

    lines = error_log.strip().splitlines()
    all_traces: list[FaultTrace] = []
    for block in _split_traceback_blocks(lines):
        all_traces.extend(_parse_single_block(block))
    return all_traces
