"""Unified diff parser, validator, and sanitizer for candidate patches."""

from __future__ import annotations

import os
import posixpath
import re
import uuid
from collections.abc import Sequence

from bugarena.models.agent import CandidatePatch, PersonaType

HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchValidationError(Exception):
    """Raised when a candidate patch is invalid, malformed, or violates security policies."""


def _parse_header_path(raw_rest: str, prefix: str) -> str:
    """Extract, unquote, strip prefix once, and normalize a diff header path."""
    part = raw_rest.split("\t", 1)[0].strip()
    if len(part) >= 2 and part[0] == '"' and part[-1] == '"':
        part = part[1:-1]
    if part == "/dev/null":
        return "/dev/null"

    part = part.replace("\\", "/").removeprefix(prefix)

    if not part or part.startswith("/") or re.match(r"^[A-Za-z]:", part):
        raise PatchValidationError(f"Invalid or absolute path in diff header: {raw_rest!r}")

    norm = posixpath.normpath(part)
    if norm in (".", "..") or norm.startswith("../") or "/../" in f"/{norm}/":
        raise PatchValidationError(f"Path traversal disallowed in diff header: {raw_rest!r}")
    return norm


def _is_protected_match(protected: str, modified: str) -> bool:
    """Exact or parent-directory containment comparison without substring false positives."""
    p_norm = posixpath.normpath(protected.replace("\\", "/").lstrip("./"))
    m_norm = posixpath.normpath(modified.replace("\\", "/").lstrip("./"))
    if os.name == "nt":
        p_norm = p_norm.lower()
        m_norm = m_norm.lower()
    if p_norm == m_norm:
        return True
    return m_norm.startswith(f"{p_norm}/") or p_norm.startswith(f"{m_norm}/")


def parse_and_validate_patch(
    raw_diff: str,
    persona: PersonaType,
    explanation: str,
    candidate_id: str | None = None,
    protected_paths: Sequence[str] | None = None,
) -> CandidatePatch:
    """
    Parse a unified diff line-by-line, validate syntax/hunks, count churn accurately,
    and verify no protected paths or traversal paths are modified.
    """
    if not raw_diff or not raw_diff.strip():
        raise PatchValidationError("Invalid diff header: diff content is empty")

    clean_diff = raw_diff.replace("\r\n", "\n").replace("\r", "\n").strip("\r\n")
    lines = clean_diff.splitlines()

    modified_files: set[str] = set()
    hunk_count = 0
    lines_added = 0
    lines_deleted = 0
    in_file = False
    in_hunk = False

    i = 0
    while i < len(lines):
        line = lines[i]
        is_paired_header = (
            line.startswith("--- ")
            and i + 1 < len(lines)
            and lines[i + 1].startswith("+++ ")
        )
        if is_paired_header:
            old_p = _parse_header_path(line[4:], "a/")
            new_p = _parse_header_path(lines[i + 1][4:], "b/")
            if old_p != "/dev/null":
                modified_files.add(old_p)
            if new_p != "/dev/null":
                modified_files.add(new_p)
            in_file = True
            in_hunk = False
            i += 2
            continue

        if in_file and line.startswith("@@"):
            if not HUNK_HEADER_RE.match(line):
                raise PatchValidationError(f"Malformed diff hunk header: {line!r}")
            hunk_count += 1
            in_hunk = True
            i += 1
            continue

        if in_hunk:
            if line.startswith("+"):
                lines_added += 1
            elif line.startswith("-"):
                lines_deleted += 1
        i += 1

    if not modified_files:
        raise PatchValidationError("Invalid diff header: Missing '--- a/' or '+++ b/' markers")
    if hunk_count == 0:
        raise PatchValidationError("Malformed diff: Missing valid @@ hunk headers")

    if protected_paths:
        for protected in protected_paths:
            for mod in modified_files:
                if _is_protected_match(protected, mod):
                    raise PatchValidationError(f"Patch modifies protected test file: '{mod}'")

    cid = candidate_id or f"cand_{persona.value[:4]}_{uuid.uuid4().hex[:6]}"
    return CandidatePatch(
        candidate_id=cid,
        persona=persona,
        diff=clean_diff,
        explanation=explanation or "",
        lines_added=lines_added,
        lines_deleted=lines_deleted,
    )
