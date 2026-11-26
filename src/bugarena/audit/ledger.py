"""Immutable finding schema and atomic JSON ledger persistence under .bugarena/."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FindingState(StrEnum):
    """Lifecycle states for an audited defect finding."""

    SUSPECTED = "SUSPECTED"
    REPRODUCED = "REPRODUCED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    UNVERIFIED = "UNVERIFIED"
    FIXED = "FIXED"
    WONTFIX = "WONTFIX"
    WONTFIX_NEEDS_HUMAN = "WONTFIX-NEEDS-HUMAN"


class EvidenceType(StrEnum):
    """Strength of supporting evidence for a finding."""

    DYNAMIC = "DYNAMIC"
    STATIC = "STATIC"
    DOC_COMPARE = "DOC_COMPARE"


class SeverityLevel(StrEnum):
    """Normalized severity tiers (Section 8 rubric)."""

    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class FindingLocation(BaseModel):
    """Precise code or configuration location for a finding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str
    line_start: int = Field(default=1, ge=1)
    line_end: int = Field(default=1, ge=1)
    symbol: str = ""

    @model_validator(mode="after")
    def _validate_lines(self) -> FindingLocation:
        if self.line_end < self.line_start:
            object.__setattr__(self, "line_end", self.line_start)
        return self


class FindingRepro(BaseModel):
    """Minimal reproduction recipe required for every finding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    inputs: str
    expected: str
    actual: str
    probe_script: str = ""


class FindingDraft(BaseModel):
    """Schema emitted by specialist reviewer subagents before ledger confirmation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    location: FindingLocation
    category: str
    what_it_is: str
    what_it_does: str
    root_cause: str
    repro: FindingRepro
    suggested_fix: str
    risks: str
    regression_test_idea: str
    proposed_severity: SeverityLevel
    severity_justification: str = ""
    evidence_hint: EvidenceType = EvidenceType.STATIC
    found_by: str


class Finding(FindingDraft):
    """Verified or tracked ledger finding entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    parent_id: str | None = None
    state: FindingState = FindingState.SUSPECTED
    evidence_type: EvidenceType = EvidenceType.STATIC
    verified_by: str | None = None
    verification_output: str = ""
    cross_refs: tuple[str, ...] = ()
    rounds_seen: tuple[int, ...] = ()
    commit_hash: str | None = None
    regression_test_path: str | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _enforce_state_and_severity_invariants(self) -> Finding:
        # Rule (Section 5): CONFIRMED requires DYNAMIC evidence and independent verified_by
        if self.state == FindingState.CONFIRMED:
            if self.evidence_type != EvidenceType.DYNAMIC:
                raise ValueError(
                    f"Finding {self.id}: CONFIRMED state requires evidence_type=DYNAMIC, "
                    f"got {self.evidence_type.value}"
                )
            if not self.verified_by or self.verified_by == self.found_by:
                raise ValueError(
                    f"Finding {self.id}: CONFIRMED state requires verified_by different from "
                    f"found_by ({self.found_by!r})"
                )

        # Rule (Section 5): DISMISSED requires stored disproving evidence
        if self.state == FindingState.DISMISSED and not self.verification_output.strip():
            raise ValueError(
                f"Finding {self.id}: DISMISSED state requires non-empty verification_output"
            )

        # Rule (Section 8): STATIC findings cannot be Critical
        if (
            self.evidence_type != EvidenceType.DYNAMIC
            and self.proposed_severity == SeverityLevel.CRITICAL
        ):
            raise ValueError(
                f"Finding {self.id}: non-DYNAMIC finding cannot carry Critical severity"
            )
        return self


class LedgerFileModel(BaseModel):
    """Top-level persisted structure in .bugarena/ledger.json."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "1.0"
    project: str = "bugarena-mcp"
    baseline_head: str = ""
    branch: str = ""
    updated_at: str = ""
    findings: tuple[Finding, ...] = ()


class FindingLedger:
    """Thread-safe / atomic JSON finding ledger stored under .bugarena/ledger.json."""

    def __init__(self, ledger_path: Path | str = ".bugarena/ledger.json"):
        self.ledger_path = Path(ledger_path)
        self._findings: list[Finding] = []
        self.baseline_head: str = ""
        self.branch: str = ""
        if self.ledger_path.is_file():
            self.load()

    @property
    def findings(self) -> tuple[Finding, ...]:
        """Return immutable tuple view of ledger findings."""
        return tuple(self._findings)

    def load(self) -> tuple[Finding, ...]:
        """Load findings from disk."""
        if not self.ledger_path.is_file():
            self._findings = []
            return ()
        raw = self.ledger_path.read_text(encoding="utf-8")
        data = LedgerFileModel.model_validate_json(raw)
        self.baseline_head = data.baseline_head
        self.branch = data.branch
        self._findings = list(data.findings)
        return tuple(self._findings)

    def save(self, baseline_head: str | None = None, branch: str | None = None) -> Path:
        """Atomically persist ledger to disk."""
        if baseline_head is not None:
            self.baseline_head = baseline_head
        if branch is not None:
            self.branch = branch

        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        model = LedgerFileModel(
            baseline_head=self.baseline_head,
            branch=self.branch,
            updated_at=datetime.now(UTC).isoformat(),
            findings=tuple(self._findings),
        )
        payload = model.model_dump_json(indent=2)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.ledger_path.parent), prefix=".ledger_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_name, self.ledger_path)
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
        return self.ledger_path

    def next_id(self, parent_id: str | None = None) -> str:
        """Generate the next sequential F-NNN or F-NNN.x identifier."""
        if parent_id:
            suffixes = [
                f.id.split(".", 1)[1]
                for f in self._findings
                if f.parent_id == parent_id and "." in f.id
            ]
            idx = len(suffixes)
            letter = chr(ord("a") + (idx % 26))
            return f"{parent_id}.{letter}"
        top_nums = [
            int(f.id[2:])
            for f in self._findings
            if f.id.startswith("F-") and "." not in f.id and f.id[2:].isdigit()
        ]
        nxt = max(top_nums, default=0) + 1
        return f"F-{nxt:03d}"

    def get(self, finding_id: str) -> Finding | None:
        """Retrieve a finding by id."""
        for f in self._findings:
            if f.id == finding_id:
                return f
        return None

    def upsert(self, finding: Finding) -> None:
        """Insert or replace a finding by id."""
        for idx, existing in enumerate(self._findings):
            if existing.id == finding.id:
                self._findings[idx] = finding
                return
        self._findings.append(finding)

    def add_draft(
        self,
        draft: FindingDraft,
        *,
        finding_id: str | None = None,
        parent_id: str | None = None,
        state: FindingState = FindingState.SUSPECTED,
        evidence_type: EvidenceType | None = None,
        cross_refs: tuple[str, ...] = (),
        round_num: int = 0,
    ) -> Finding:
        """Promote a draft into the ledger (avoiding exact duplicate titles/locations)."""
        ev = evidence_type or draft.evidence_hint
        sev = draft.proposed_severity
        # Section 8 rubric: non-DYNAMIC cannot be Critical
        if ev != EvidenceType.DYNAMIC and sev == SeverityLevel.CRITICAL:
            sev = SeverityLevel.HIGH

        fid = finding_id or self.next_id(parent_id=parent_id)
        finding = Finding(
            id=fid,
            parent_id=parent_id,
            state=state,
            evidence_type=ev,
            cross_refs=cross_refs,
            rounds_seen=(round_num,) if round_num >= 0 else (),
            title=draft.title,
            location=draft.location,
            category=draft.category,
            what_it_is=draft.what_it_is,
            what_it_does=draft.what_it_does,
            root_cause=draft.root_cause,
            repro=draft.repro,
            suggested_fix=draft.suggested_fix,
            risks=draft.risks,
            regression_test_idea=draft.regression_test_idea,
            proposed_severity=sev,
            severity_justification=draft.severity_justification
            or f"Graded {sev.value} under Section 8 rubric.",
            evidence_hint=draft.evidence_hint,
            found_by=draft.found_by,
        )
        self.upsert(finding)
        return finding

    def counts(self) -> dict[str, int]:
        """Return counts grouped by FindingState."""
        counts: dict[str, int] = {s.value: 0 for s in FindingState}
        for f in self._findings:
            counts[f.state.value] = counts.get(f.state.value, 0) + 1
        counts["TOTAL"] = len(self._findings)
        return counts
