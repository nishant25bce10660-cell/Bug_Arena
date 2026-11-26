"""ECC-style specialist subagent registry, prompts, and schema-validated runner."""

from bugarena.agents.base import AgentRunResult, AgentSpec
from bugarena.agents.registry import AGENT_TOOL_MAP, build_agent_registry, get_agent_spec
from bugarena.agents.runner import AgentRunner

__all__ = [
    "AGENT_TOOL_MAP",
    "AgentRunResult",
    "AgentRunner",
    "AgentSpec",
    "build_agent_registry",
    "get_agent_spec",
]
