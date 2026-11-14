import pytest
from pydantic import ValidationError

from bugarena.models.agent import CandidatePatch, PersonaType
from bugarena.models.bug import BugSpec, FaultTrace, SuspectLocation
from bugarena.models.repro import ExecutionOutcome, ReproTestSpec
from bugarena.models.tournament import PatchEvaluation, TournamentRecord


def test_suspect_location_immutability():
    loc = SuspectLocation(
        file_path="src/calc.py",
        function_name="divide",
        line_range=(10, 15),
        confidence=0.95,
        bug_type="ZeroDivisionError",
        reasoning="Denominator unchecked",
        code_snippet="return a / b",
    )
    assert loc.file_path == "src/calc.py"
    with pytest.raises(ValidationError):
        loc.confidence = 0.5  # Mutation must fail due to frozen=True


def test_bug_spec_creation():
    trace = FaultTrace(
        file_path="src/calc.py",
        line_number=12,
        function_name="divide",
        code="return a / b",
        error_message="division by zero",
    )
    loc = SuspectLocation(
        file_path="src/calc.py",
        function_name="divide",
        line_range=(10, 15),
        confidence=0.95,
        bug_type="ZeroDivisionError",
        reasoning="Denominator unchecked",
        code_snippet="return a / b",
    )
    bug = BugSpec(
        bug_id="bug_101",
        repo_path="/workspace/repo",
        error_log="ZeroDivisionError: division by zero",
        suspects=[loc],
        traces=[trace],
    )
    assert bug.bug_id == "bug_101"
    assert len(bug.suspects) == 1
    assert len(bug.traces) == 1
    with pytest.raises(ValidationError):
        bug.repo_path = "/new/path"


def test_repro_test_spec_immutability():
    outcome = ExecutionOutcome(
        exit_code=1,
        stdout="",
        stderr="ZeroDivisionError: division by zero",
        duration_seconds=0.42,
        timed_out=False,
    )
    spec = ReproTestSpec(
        test_file_path="tests/repro/test_bug_101.py",
        test_code="def test_zero_div(): divide(10, 0)",
        expected_exception="ZeroDivisionError",
        red_baseline_verified=True,
        initial_outcome=outcome,
    )
    assert spec.red_baseline_verified is True
    assert spec.initial_outcome.exit_code == 1
    with pytest.raises(ValidationError):
        spec.red_baseline_verified = False


def test_candidate_patch_immutability():
    patch = CandidatePatch(
        candidate_id="cand_surg_1",
        persona=PersonaType.SURGICAL_MINIMALIST,
        diff="--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,3 @@\n+if b == 0: raise ValueError()",
        explanation="Added zero check before division",
        lines_added=1,
        lines_deleted=0,
    )
    assert patch.persona == PersonaType.SURGICAL_MINIMALIST
    with pytest.raises(ValidationError):
        patch.lines_added = 5


def test_tournament_and_evaluation():
    patch_eval = PatchEvaluation(
        candidate_id="cand_surg_1",
        repro_passed=True,
        regressions_count=0,
        total_regressions_checked=50,
        diff_churn=1,
        cyclomatic_delta=1,
        mutation_kill_ratio=0.8,
        score=98.5,
        disqualified=False,
    )
    assert patch_eval.score == 98.5
    assert not patch_eval.disqualified

    tournament = TournamentRecord(
        tournament_id="tourn_abc",
        repo_path="/workspace/repo",
        candidates=[],
        evaluations=[patch_eval],
        champion_candidate_id="cand_surg_1",
    )
    assert tournament.champion_candidate_id == "cand_surg_1"
    with pytest.raises(ValidationError):
        tournament.champion_candidate_id = "cand_other"
