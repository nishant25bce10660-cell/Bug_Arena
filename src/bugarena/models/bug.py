"""Immutable models for bug detection and fault localization."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FaultTrace(BaseModel):
    """Represents an individual stack frame or trace line."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_path: str
    line_number: int = Field(ge=1)
    function_name: str
    code: str
    error_message: str


class SuspectLocation(BaseModel):
    """Represents a suspicious code location identified by analysis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_path: str
    function_name: str
    line_range: tuple[int, int]
    confidence: float = Field(ge=0.0, le=1.0)
    bug_type: str
    reasoning: str
    code_snippet: str

    @model_validator(mode="after")
    def _validate_line_range(self) -> SuspectLocation:
        start, end = self.line_range
        if start < 1 or end < start:
            raise ValueError(f"Invalid line_range {self.line_range}; expected 1 <= start <= end")
        return self


class BugSpec(BaseModel):
    """Complete specification of a detected bug."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bug_id: str
    repo_path: str
    error_log: str | None = None
    hint: str | None = None
    suspects: tuple[SuspectLocation, ...] = ()
    traces: tuple[FaultTrace, ...] = ()
