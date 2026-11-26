"""Asynchronous tournament coordinator for concurrent candidate generation."""

import asyncio
import logging
import uuid
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from bugarena.models.agent import CandidatePatch, PersonaType
from bugarena.models.bug import BugSpec
from bugarena.models.repro import ReproTestSpec
from bugarena.tournament.patch_parser import PatchValidationError, parse_and_validate_patch
from bugarena.tournament.providers.dispatcher import MultiModelDispatcher

logger = logging.getLogger(__name__)

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
        self.personas = list(PersonaType) if personas is None else list(personas)
        self.dispatcher = MultiModelDispatcher()
        self.generator_func = generator_func or self.dispatcher.generate_patch
        self.last_errors: dict[str, str] = {}

    async def run_tournament(
        self,
        bug_spec: BugSpec,
        repro_spec: ReproTestSpec,
        timeout_seconds: float = 60.0,
    ) -> tuple[str, list[CandidatePatch]]:
        """
        Run the multi-agent tournament concurrently across all configured personas.
        Records per-persona failure diagnostics in self.last_errors.
        """
        tournament_id = f"tourn_{uuid.uuid4().hex[:8]}"
        protected_paths = [repro_spec.test_file_path]
        self.dispatcher.timeout_seconds = timeout_seconds
        errors: dict[str, str] = {}

        async def generate_single(persona: PersonaType) -> CandidatePatch | None:
            if not self.generator_func:
                errors[persona.value] = "No generator function configured"
                return None
            try:
                raw_diff, explanation = await asyncio.wait_for(
                    self.generator_func(persona, bug_spec, repro_spec),
                    timeout=timeout_seconds,
                )
                if not raw_diff or not raw_diff.strip():
                    errors[persona.value] = explanation or "Provider returned empty diff"
                    logger.warning(
                        "Persona %s returned empty diff: %s",
                        persona.value,
                        errors[persona.value],
                    )
                    return None
                return parse_and_validate_patch(
                    raw_diff=raw_diff,
                    persona=persona,
                    explanation=explanation,
                    protected_paths=protected_paths,
                )
            except (TimeoutError, PatchValidationError, OSError) as exc:
                errors[persona.value] = str(exc) or type(exc).__name__
                logger.warning("Persona %s generation rejected: %s", persona.value, exc)
                return None
            except Exception as exc:
                errors[persona.value] = str(exc) or type(exc).__name__
                logger.exception("Persona %s generation encountered error", persona.value)
                return None

        tasks = [generate_single(p) for p in self.personas]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        candidates: list[CandidatePatch] = []
        for p, res in zip(self.personas, results, strict=False):
            if isinstance(res, Exception):
                errors[p.value] = str(res)
                logger.error("Persona %s unhandled exception in gather: %s", p.value, res)
            elif isinstance(res, CandidatePatch):
                candidates.append(res)

        self.last_errors = errors
        return tournament_id, candidates
