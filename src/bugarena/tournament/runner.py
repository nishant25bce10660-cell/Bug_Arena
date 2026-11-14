"""Asynchronous tournament coordinator for concurrent candidate generation."""

import asyncio
import uuid
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from bugarena.models.agent import CandidatePatch, PersonaType
from bugarena.models.bug import BugSpec
from bugarena.models.repro import ReproTestSpec
from bugarena.tournament.patch_parser import PatchValidationError, parse_and_validate_patch

CandidateGenerator = Callable[
    [PersonaType, BugSpec, ReproTestSpec], Coroutine[Any, Any, tuple[str, str]]
]


class TournamentRunner:
    """Orchestrates parallel multi-agent competition for candidate patch proposals."""

    def __init__(
        self,
        personas: Sequence[PersonaType] | None = None,
        generator_func: CandidateGenerator | None = None,
    ):
        self.personas = list(
            personas
            or [
                PersonaType.SURGICAL_MINIMALIST,
                PersonaType.DEFENSIVE_GUARDIAN,
                PersonaType.ARCHITECTURAL_FIXER,
            ]
        )
        self.generator_func = generator_func

    async def run_tournament(
        self,
        bug_spec: BugSpec,
        repro_spec: ReproTestSpec,
        timeout_seconds: float = 60.0,
    ) -> tuple[str, list[CandidatePatch]]:
        """
        Run the multi-agent tournament concurrently across all configured personas.
        """
        tournament_id = f"tourn_{uuid.uuid4().hex[:8]}"
        protected_paths = [repro_spec.test_file_path]

        async def generate_single(persona: PersonaType) -> CandidatePatch | None:
            if not self.generator_func:
                return None
            try:
                raw_diff, explanation = await asyncio.wait_for(
                    self.generator_func(persona, bug_spec, repro_spec),
                    timeout=timeout_seconds,
                )
                return parse_and_validate_patch(
                    raw_diff=raw_diff,
                    persona=persona,
                    explanation=explanation,
                    protected_paths=protected_paths,
                )
            except (TimeoutError, PatchValidationError, OSError):
                return None

        tasks = [generate_single(p) for p in self.personas]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        candidates: list[CandidatePatch] = []
        for res in results:
            if isinstance(res, CandidatePatch):
                candidates.append(res)

        return tournament_id, candidates
