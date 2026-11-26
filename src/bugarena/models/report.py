"""Immutable models for bug diagnostic reports and export payloads."""

from pydantic import BaseModel, ConfigDict

from bugarena.models.agent import CandidatePatch
from bugarena.models.tournament import PatchEvaluation


class FixReport(BaseModel):
    """Actionable fix report returned to client or user."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tournament_id: str
    champion_patch: CandidatePatch | None = None
    champion_eval: PatchEvaluation | None = None
    summary_markdown: str
    git_patch_diff: str
    report_file_path: str | None = None
