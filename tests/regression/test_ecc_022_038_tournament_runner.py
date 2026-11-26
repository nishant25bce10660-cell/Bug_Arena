"""Regression test for ECC-022 and ECC-038 (BA-012): TournamentRunner personas & failure diagnostics."""

import asyncio

import pytest

from bugarena.models.agent import PersonaType
from bugarena.models.bug import BugSpec
from bugarena.models.repro import ReproTestSpec
from bugarena.tournament.personas.base import get_persona_prompt
from bugarena.tournament.runner import TournamentRunner


def test_ecc_022_038_personas_defaults_empty_unknown_and_errors():
    # 1. Default personas include all 4 PersonaType values (incl CONTRACT_ENFORCER)
    r_def = TournamentRunner()
    assert set(r_def.personas) == set(PersonaType)
    assert len(r_def.personas) == 4

    # 2. Explicit personas=[] is respected
    r_empty = TournamentRunner(personas=[])
    assert r_empty.personas == []

    # 3. Unknown persona raises KeyError instead of silent fallback
    with pytest.raises(KeyError):
        get_persona_prompt("nonexistent_persona")  # type: ignore[arg-type]

    # 4. Per-persona failures surfaced on runner.last_errors instead of silent []
    async def broken_gen(persona: PersonaType, _b: BugSpec, _r: ReproTestSpec):
        if persona == PersonaType.SURGICAL_MINIMALIST:
            return "", "Missing GEMINI_API_KEY"
        raise TimeoutError("timed out waiting for LLM")

    runner = TournamentRunner(generator_func=broken_gen)
    bug = BugSpec(bug_id="b", repo_path=".")
    repro = ReproTestSpec(test_file_path="t.py", test_code="pass", red_baseline_verified=True)
    _tid, cands = asyncio.run(runner.run_tournament(bug, repro, timeout_seconds=1.0))
    assert cands == []
    assert hasattr(runner, "last_errors")
    assert "Missing GEMINI_API_KEY" in runner.last_errors.get("surgical_minimalist", "")
    assert "timed out" in runner.last_errors.get("defensive_guardian", "").lower()
