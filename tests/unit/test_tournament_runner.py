"""Unit tests for the asynchronous TournamentRunner."""

import pytest

from bugarena.models.agent import PersonaType
from bugarena.models.bug import BugSpec
from bugarena.models.repro import ReproTestSpec
from bugarena.tournament.runner import TournamentRunner


@pytest.mark.asyncio
async def test_tournament_runner_concurrent_success():
    """Verify concurrent patch generation across multiple personas."""
    bug_spec = BugSpec(
        bug_id="bug_runner_1",
        repo_path=".",
        error_log="ZeroDivisionError",
    )
    repro_spec = ReproTestSpec(
        test_file_path="tests/test_calc.py",
        test_code="def test_zero(): assert divide(1, 0) == 0",
        expected_failure_type="ZeroDivisionError",
        red_baseline_verified=True,
    )

    valid_diff = (
        "--- a/src/calc.py\n"
        "+++ b/src/calc.py\n"
        "@@ -1,2 +1,4 @@\n"
        "+if b == 0:\n"
        "+    return 0\n"
    )

    async def mock_generator(persona: PersonaType, b_spec: BugSpec, r_spec: ReproTestSpec):
        return valid_diff, f"Fixed by {persona.value}"

    runner = TournamentRunner(
        personas=[
            PersonaType.SURGICAL_MINIMALIST,
            PersonaType.DEFENSIVE_GUARDIAN,
            PersonaType.ARCHITECTURAL_FIXER,
        ],
        generator_func=mock_generator,
    )

    t_id, candidates = await runner.run_tournament(bug_spec, repro_spec, timeout_seconds=5.0)

    assert t_id.startswith("tourn_")
    assert len(candidates) == 3
    personas_generated = {c.persona for c in candidates}
    assert PersonaType.SURGICAL_MINIMALIST in personas_generated
    assert PersonaType.DEFENSIVE_GUARDIAN in personas_generated
    assert PersonaType.ARCHITECTURAL_FIXER in personas_generated


@pytest.mark.asyncio
async def test_tournament_runner_handles_failures_gracefully():
    """Verify that a failing or throwing persona does not crash the tournament."""
    bug_spec = BugSpec(
        bug_id="bug_runner_2",
        repo_path=".",
        error_log="ValueError",
    )
    repro_spec = ReproTestSpec(
        test_file_path="tests/test_val.py",
        test_code="def test_val(): pass",
        expected_failure_type="ValueError",
        red_baseline_verified=True,
    )

    valid_diff = (
        "--- a/src/val.py\n"
        "+++ b/src/val.py\n"
        "@@ -1,1 +1,2 @@\n"
        "+# valid fix\n"
    )

    async def mock_generator(persona: PersonaType, b_spec: BugSpec, r_spec: ReproTestSpec):
        if persona == PersonaType.SURGICAL_MINIMALIST:
            return valid_diff, "Surgical fix"
        elif persona == PersonaType.DEFENSIVE_GUARDIAN:
            # Simulate network or provider exception
            raise RuntimeError("API connection timeout")
        else:
            # Simulate invalid diff (e.g. tampering with test file)
            tamper_diff = "--- a/tests/test_val.py\n+++ b/tests/test_val.py\n@@ -1 +1 @@\n+pass\n"
            return tamper_diff, "Tampered diff"

    runner = TournamentRunner(
        personas=[
            PersonaType.SURGICAL_MINIMALIST,
            PersonaType.DEFENSIVE_GUARDIAN,
            PersonaType.ARCHITECTURAL_FIXER,
        ],
        generator_func=mock_generator,
    )

    t_id, candidates = await runner.run_tournament(bug_spec, repro_spec, timeout_seconds=5.0)

    assert t_id.startswith("tourn_")
    # Only the Surgical Minimalist patch should have passed validation
    assert len(candidates) == 1
    assert candidates[0].persona == PersonaType.SURGICAL_MINIMALIST
