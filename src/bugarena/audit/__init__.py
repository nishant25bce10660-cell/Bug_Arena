"""BugArena multi-agent audit engine package."""

from bugarena.audit.coverage import (
    CoverageMatrix,
    ModuleCoverage,
    build_coverage_matrix,
    classify_area,
    mark_area_coverage,
)
from bugarena.audit.dedupe import (
    find_duplicate_in_ledger,
    merge_or_insert_draft,
    root_cause_fingerprint,
    split_bundled_finding,
)
from bugarena.audit.evaluator import AgentEvaluator, AgentScorecard
from bugarena.audit.ledger import (
    EvidenceType,
    Finding,
    FindingDraft,
    FindingLedger,
    FindingLocation,
    FindingRepro,
    FindingState,
    SeverityLevel,
)
from bugarena.audit.loop import LoopOperator, LoopState, RoundSummary
from bugarena.audit.probes import run_isolated_probe
from bugarena.audit.report import generate_audit_report
from bugarena.audit.verify import apply_severity_rubric, verify_finding

__all__ = [
    "AgentEvaluator",
    "AgentScorecard",
    "CoverageMatrix",
    "EvidenceType",
    "Finding",
    "FindingDraft",
    "FindingLedger",
    "FindingLocation",
    "FindingRepro",
    "FindingState",
    "LoopOperator",
    "LoopState",
    "ModuleCoverage",
    "RoundSummary",
    "SeverityLevel",
    "apply_severity_rubric",
    "build_coverage_matrix",
    "classify_area",
    "find_duplicate_in_ledger",
    "generate_audit_report",
    "mark_area_coverage",
    "merge_or_insert_draft",
    "root_cause_fingerprint",
    "run_isolated_probe",
    "split_bundled_finding",
    "verify_finding",
]
