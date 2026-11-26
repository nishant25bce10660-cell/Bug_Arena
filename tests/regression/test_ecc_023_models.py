"""Regression test for ECC-023: tuple immutability, StrEnum, extra='forbid', invariants."""

import pytest
from pydantic import ValidationError

from bugarena.models.agent import CandidatePatch, PersonaType
from bugarena.models.bug import BugSpec, FaultTrace, SuspectLocation
from bugarena.models.report import FixReport
from bugarena.models.repro import ExecutionOutcome, ReproTestSpec
from bugarena.models.tournament import PatchEvaluation, TournamentRecord


def test_ecc_023_immutable_tuples_strenum_extra_forbid_and_invariants():
    # 1. StrEnum formatting
    assert str(PersonaType.SURGICAL_MINIMALIST) == "surgical_minimalist"

    # 2. Sequence inputs coerced to immutable tuples (never mutable list)
    trace = FaultTrace(
        file_path="src/calc.py",
        line_number=1,
        function_name="divide",
        code="return a / b",
        error_message="err",
    )
    suspect = SuspectLocation(
        file_path="src/calc.py",
        function_name="divide",
        line_range=(1, 3),
        confidence=0.9,
        bug_type="ZeroDivisionError",
        reasoning="bad",
        code_snippet="return a / b",
    )
    bug = BugSpec(bug_id="b1", repo_path=".", suspects=[suspect], traces=[trace])
    assert isinstance(bug.suspects, tuple)
    assert isinstance(bug.traces, tuple)

    tourn = TournamentRecord(tournament_id="t1", repo_path=".", candidates=[], evaluations=[])
    assert isinstance(tourn.candidates, tuple)
    assert isinstance(tourn.evaluations, tuple)

    # 3. extra='forbid' on every domain model
    for cls, kwargs in (
        (SuspectLocation, {"file_path": "a.py", "function_name": "f", "line_range": (1, 1), "confidence": 0.5, "bug_type": "E", "reasoning": "r", "code_snippet": "x", "bogus": 1}),
        (FixReport, {"tournament_id": "t", "summary_markdown": "m", "git_patch_diff": "", "champion_candidate_id": "x"}),
        (CandidatePatch, {"candidate_id": "c", "persona": PersonaType.SURGICAL_MINIMALIST, "diff": "d", "explanation": "e", "lines_added": 0, "lines_deleted": 0, "extra_k": 1}),
        (ExecutionOutcome, {"exit_code": 0, "stdout": "", "stderr": "", "duration_seconds": 0.1, "extra_k": 1}),
        (ReproTestSpec, {"test_file_path": "t.py", "test_code": "pass", "red_baseline_verified": True, "extra_k": 1}),
        (PatchEvaluation, {"candidate_id": "c", "repro_passed": True, "regressions_count": 0, "total_regressions_checked": 1, "diff_churn": 0, "cyclomatic_delta": 0, "score": 90.0, "extra_k": 1}),
    ):
        with pytest.raises(ValidationError):
            cls(**kwargs)

    # 4. Invariant validators: inverted line_range, negative FaultTrace line_number
    with pytest.raises(ValidationError):
        SuspectLocation(
            file_path="a.py",
            function_name="f",
            line_range=(10, 2),
            confidence=0.5,
            bug_type="E",
            reasoning="r",
            code_snippet="x",
        )
    with pytest.raises(ValidationError):
        FaultTrace(
            file_path="a.py",
            line_number=0,
            function_name="f",
            code="x",
            error_message="e",
        )
