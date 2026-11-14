"""Immutable models for the multi-agent tournament and patch evaluations."""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from bugarena.models.agent import CandidatePatch
from bugarena.models.bug import BugSpec
from bugarena.models.repro import ReproTestSpec


class PatchEvaluation(BaseModel):
    """Evaluation metrics and score for a single candidate patch."""

    model_config = ConfigDict(frozen=True)

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


class TournamentRecord(BaseModel):
    """Full state record of a multi-agent repair tournament."""

    model_config = ConfigDict(frozen=True)

    tournament_id: str
    repo_path: str
    candidates: Sequence[CandidatePatch] = Field(default_factory=tuple)
    evaluations: Sequence[PatchEvaluation] = Field(default_factory=tuple)
    champion_candidate_id: str | None = None
    bug_spec: BugSpec | None = None
    repro_spec: ReproTestSpec | None = None
    bug_description: str | None = None
    report_file_path: str | None = None
