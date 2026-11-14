"""Log and traceback parsing utilities for Python and other runtimes."""

import re

from bugarena.models.bug import FaultTrace

FRAME_PATTERN = re.compile(
    r'File\s+["\'](?P<file>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>\w+))?',
    re.IGNORECASE,
)

EXCEPTION_PATTERN = re.compile(
    r"^(?P<type>[a-zA-Z_]\w*(?:Error|Exception|Warning|Fault|Interrupt)?):\s*(?P<msg>.*)$",
    re.MULTILINE,
)


def parse_python_traceback(error_log: str) -> list[FaultTrace]:
    """
    Parse a Python runtime traceback into structured FaultTrace objects.
    """
    if not error_log or not error_log.strip():
        return []

    lines = error_log.strip().splitlines()
    traces: list[FaultTrace] = []

    # Detect the exception message (typically on the final non-empty line)
    error_message = "UnknownError"
    for line in reversed(lines):
        line_clean = line.strip()
        if not line_clean:
            continue
        exc_match = EXCEPTION_PATTERN.match(line_clean)
        if exc_match or ":" in line_clean and not line_clean.startswith("File "):
            error_message = line_clean
            break

    # Parse frames
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = FRAME_PATTERN.search(line)
        if match:
            file_path = match.group("file").replace("\\", "/")
            line_num = int(match.group("line"))
            func_name = match.group("func") or "<module>"

            # The subsequent non-frame lines before the next File or exception are code lines
            code_lines = []
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                if FRAME_PATTERN.search(next_line) or EXCEPTION_PATTERN.match(next_line):
                    break
                # Filter caret underline decorators like ^^^^^ or ~~^~~
                if not re.match(r"^[\^~ \t\-=]+$", next_line):
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
