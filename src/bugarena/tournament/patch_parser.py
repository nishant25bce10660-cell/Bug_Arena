"""Unified diff parser, validator, and sanitizer for candidate patches."""

import re
import uuid
from collections.abc import Sequence

from bugarena.models.agent import CandidatePatch, PersonaType


class PatchValidationError(Exception):
    """Raised when a candidate patch is invalid, malformed, or violates security policies."""


DIFF_HEADER_PATTERN = re.compile(
    r"^--- (?:a/)?(?P<old_file>\S+)\n\+\+\+ (?:b/)?(?P<new_file>\S+)", re.MULTILINE
)


def parse_and_validate_patch(
    raw_diff: str,
    persona: PersonaType,
    explanation: str,
    candidate_id: str | None = None,
    protected_paths: Sequence[str] | None = None,
) -> CandidatePatch:
    """
    Parse a unified diff, validate syntax, count churn, and verify no protected files are modified.
    """
    if not raw_diff or not raw_diff.strip():
        raise PatchValidationError("Invalid diff header: diff content is empty")

    clean_diff = raw_diff.replace("\r\n", "\n").strip("\r\n")
    match = DIFF_HEADER_PATTERN.search(clean_diff)
    if not match:
        raise PatchValidationError("Invalid diff header: Missing '--- a/' or '+++ b/' markers")

    # Check modified files
    modified_files = set()
    for m in DIFF_HEADER_PATTERN.finditer(clean_diff):
        target = m.group("new_file")
        target = target.removeprefix("b/")
        modified_files.add(target.replace("\\", "/"))

    if protected_paths:
        for protected in protected_paths:
            clean_prot = protected.replace("\\", "/")
            for mod in modified_files:
                if clean_prot in mod or mod in clean_prot:
                    raise PatchValidationError(f"Patch modifies protected test file: '{mod}'")

    # Count churn
    lines_added = 0
    lines_deleted = 0
    for line in clean_diff.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith("+"):
            lines_added += 1
        elif line.startswith("-"):
            lines_deleted += 1

    cid = candidate_id or f"cand_{persona.value[:4]}_{uuid.uuid4().hex[:6]}"
    return CandidatePatch(
        candidate_id=cid,
        persona=persona,
        diff=clean_diff,
        explanation=explanation,
        lines_added=lines_added,
        lines_deleted=lines_deleted,
    )
