"""Immutable models for bug reproduction and execution outcomes."""

from pydantic import BaseModel, ConfigDict, Field


class ExecutionOutcome(BaseModel):
    """Represents the execution result of running a test or command."""

    model_config = ConfigDict(frozen=True)

    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float = Field(ge=0.0)
    timed_out: bool = False


class ReproTestSpec(BaseModel):
    """Specification of a synthesized reproduction test case."""

    model_config = ConfigDict(frozen=True)

    test_file_path: str
    test_code: str
    expected_exception: str | None = None
    red_baseline_verified: bool
    initial_outcome: ExecutionOutcome | None = None
