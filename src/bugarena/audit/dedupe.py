"""Root-cause deduplication and parent/child sub-issue grouping."""

from __future__ import annotations

import re

from bugarena.audit.ledger import Finding, FindingDraft, FindingLedger, FindingState


def _normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def root_cause_fingerprint(file_path: str, symbol: str, root_cause: str) -> str:
    """Compute canonical dedup key from normalized file path, symbol, and root cause."""
    norm_file = file_path.replace("\\", "/").lstrip("./").lower()
    norm_sym = _normalize_key(symbol or "module")
    cause_tokens = _normalize_key(root_cause).split()[:8]
    return f"{norm_file}::{norm_sym}::{'_'.join(cause_tokens)}"


def find_duplicate_in_ledger(ledger: FindingLedger, draft: FindingDraft) -> Finding | None:
    """Locate an existing ledger finding sharing location+root cause/overlap."""
    target_file = draft.location.file.replace("\\", "/").lstrip("./").lower()
    target_fp = root_cause_fingerprint(draft.location.file, draft.location.symbol, draft.root_cause)
    draft_title_tokens = set(_normalize_key(draft.title).split())

    for existing in ledger.findings:
        ex_file = existing.location.file.replace("\\", "/").lstrip("./").lower()
        if ex_file != target_file:
            continue
        ex_fp = root_cause_fingerprint(
            existing.location.file, existing.location.symbol, existing.root_cause
        )
        if ex_fp == target_fp:
            return existing
        # Overlapping line range + same symbol or strong title/cause similarity
        lines_overlap = not (
            draft.location.line_end < existing.location.line_start
            or draft.location.line_start > existing.location.line_end
        )
        ex_title_tokens = set(_normalize_key(existing.title).split())
        if lines_overlap and (
            draft.location.symbol == existing.location.symbol
            or len(draft_title_tokens & ex_title_tokens) >= 4
        ):
            return existing
    return None


def merge_or_insert_draft(
    ledger: FindingLedger,
    draft: FindingDraft,
    *,
    round_num: int,
    parent_id: str | None = None,
    cross_refs: tuple[str, ...] = (),
) -> tuple[Finding, bool]:
    """
    Deduplicate draft against existing ledger entries.
    Returns (finding, is_new).
    """
    existing = find_duplicate_in_ledger(ledger, draft)
    if existing is not None:
        new_rounds = tuple(sorted(set(existing.rounds_seen) | {round_num}))
        new_refs = tuple(sorted(set(existing.cross_refs) | set(cross_refs)))
        updated = existing.model_copy(
            update={"rounds_seen": new_rounds, "cross_refs": new_refs}
        )
        ledger.upsert(updated)
        return updated, False

    created = ledger.add_draft(
        draft,
        parent_id=parent_id,
        state=FindingState.SUSPECTED,
        cross_refs=cross_refs,
        round_num=round_num,
    )
    return created, True


def split_bundled_finding(
    ledger: FindingLedger,
    parent_id: str,
    child_drafts: list[FindingDraft],
    *,
    round_num: int,
) -> list[Finding]:
    """Split a multi-symptom finding into child findings F-NNN.a, F-NNN.b, ..."""
    parent = ledger.get(parent_id)
    if parent is None:
        raise KeyError(f"Parent finding '{parent_id}' not found in ledger")

    created_children: list[Finding] = []
    for draft in child_drafts:
        child = ledger.add_draft(
            draft,
            parent_id=parent.id,
            state=FindingState.SUSPECTED,
            cross_refs=parent.cross_refs,
            round_num=round_num,
        )
        created_children.append(child)
    return created_children
