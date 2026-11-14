"""Immutable models for bug detection and fault localization."""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field


class FaultTrace(BaseModel):
    """Represents an individual stack frame or trace line."""

    model_config = ConfigDict(frozen=True)

    file_path: str
    line_number: int
    function_name: str
    code: str
    error_message: str


class SuspectLocation(BaseModel):
    """Represents a suspicious code location identified by analysis."""

    model_config = ConfigDict(frozen=True)

    file_path: str
    function_name: str
    line_range: tuple[int, int]
    confidence: float = Field(ge=0.0, le=1.0)
    bug_type: str
    reasoning: str
    code_snippet: str


class BugSpec(BaseModel):
    """Complete specification of a detected bug."""

    model_config = ConfigDict(frozen=True)

    bug_id: str
    repo_path: str
    error_log: str | None = None
    hint: str | None = None
    suspects: Sequence[SuspectLocation] = Field(default_factory=tuple)
    traces: Sequence[FaultTrace] = Field(default_factory=tuple)
