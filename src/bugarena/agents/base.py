"""Base schemas and contracts for specialist ECC-style subagents."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from bugarena.audit.ledger import FindingDraft


class AgentSpec(BaseModel):
    """Immutable specification of an audit or repair subagent role."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    role_prompt: str
    allowed_tools: tuple[str, ...]
    output_schema: str = "FindingDraft"
    model_pref: str | None = None
    timeout: float = Field(default=60.0, gt=0.0)


class AgentRunResult(BaseModel):
    """Structured result emitted by running a single specialist subagent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_name: str
    findings: tuple[FindingDraft, ...] = ()
    raw_output: str = ""
    error: str | None = None
    invalid_json_error: bool = False
    duration_seconds: float = Field(default=0.0, ge=0.0)
    tool_calls: tuple[str, ...] = ()
    cost_usd: float = Field(default=0.0, ge=0.0)
