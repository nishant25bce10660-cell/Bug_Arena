"""Immutable models for the multi-agent tournament and patch evaluations."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bugarena.models.agent import CandidatePatch
from bugarena.models.bug import BugSpec
from bugarena.models.repro import ReproTestSpec


class PatchEvaluation(BaseModel):
    """Evaluation metrics and score for a single candidate patch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    repro_passed: bool
    regressions_count: int = Field(ge=0)
    total_regressions_checked: int = Field(ge=0)
    diff_churn: int = Field(ge=0)
    cyclomatic_delta: int
    mutation_kill_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    score: float = Field(ge=0.0, le=100.0)
    disqualified: bool = False
    disqualification_reason: str | None = None

    @model_validator(mode="after")
    def _validate_eval_invariants(self) -> PatchEvaluation:
        if self.disqualified and self.score != 0.0:
            raise ValueError("Disqualified PatchEvaluation must have score == 0.0")
        return self


class TournamentRecord(BaseModel):
    """Full state record of a multi-agent repair tournament."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tournament_id: str
    repo_path: str
    candidates: tuple[CandidatePatch, ...] = ()
    evaluations: tuple[PatchEvaluation, ...] = ()
    champion_candidate_id: str | None = None
    bug_spec: BugSpec | None = None
    repro_spec: ReproTestSpec | None = None
    bug_description: str | None = None
    report_file_path: str | None = None
