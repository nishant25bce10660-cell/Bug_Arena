"""Registry loading prompt-defined ECC-style subagent roles and tool ACLs."""

from __future__ import annotations

from pathlib import Path

from bugarena.agents.base import AgentSpec

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

AGENT_TOOL_MAP: dict[str, tuple[str, ...]] = {
    "loop-operator": ("ledger", "coverage"),
    "python-reviewer": ("ast_scan", "ruff_json"),
    "code-reviewer": ("grep", "pytest_run"),
    "security-reviewer": ("grep", "probe_run"),
    "silent-failure-hunter": ("grep", "probe_run"),
    "performance-optimizer": ("radon_cc", "grep"),
    "type-design-analyzer": ("ast_scan", "probe_run"),
    "pr-test-analyzer": ("pytest_run", "coverage"),
    "comment-analyzer": ("grep",),
    "architect": ("git_ls", "grep"),
    "code-architect": ("all",),
    "agent-evaluator": ("ledger",),
    "fix-author-surgical": ("pytest_run",),
    "fix-author-defensive": ("pytest_run",),
    "fix-author-contract": ("pytest_run",),
    "fix-author-architectural": ("pytest_run",),
    "fix-reviewer": ("pytest_run", "probe_run"),
    # BugArena v2 multi-browser site audit & truth roles
    "console-analyst": ("cdp.console", "vault"),
    "network-analyst": ("cdp.network", "vault"),
    "dom-a11y-analyst": ("cdp.elements", "vault"),
    "storage-security-analyst": ("cdp.application", "cdp.security", "vault"),
    "performance-memory-analyst": ("cdp.performance", "cdp.memory", "vault"),
    "js-source-analyst": ("cdp.sources", "vault"),
    "responsive-analyst": ("cdp.sensors", "cdp.rendering", "vault"),
    "cross-browser-diff-analyst": ("cdp.diff", "vault"),
    "report-writer": ("vault", "ledger"),
    "verifier": ("cdp.replay", "probe_run", "vault"),
    "honesty-auditor": ("ledger", "vault", "transcript"),
    "merge-analyst": ("ast_scan", "merge_sandbox"),
}

_PROMPT_FILENAME_OVERRIDES: dict[str, str] = {
    "fix-author-surgical": "fix_author.md",
    "fix-author-defensive": "fix_author.md",
    "fix-author-contract": "fix_author.md",
    "fix-author-architectural": "fix_author.md",
}

SWEEP_ROLES: tuple[str, ...] = (
    "python-reviewer",
    "code-reviewer",
    "security-reviewer",
    "silent-failure-hunter",
    "performance-optimizer",
    "type-design-analyzer",
    "pr-test-analyzer",
    "comment-analyzer",
    "architect",
)

SITE_ANALYST_ROLES: tuple[str, ...] = (
    "console-analyst",
    "network-analyst",
    "dom-a11y-analyst",
    "storage-security-analyst",
    "performance-memory-analyst",
    "js-source-analyst",
    "responsive-analyst",
    "cross-browser-diff-analyst",
)


def _load_prompt_text(role_name: str) -> str:
    fname = _PROMPT_FILENAME_OVERRIDES.get(role_name, f"{role_name.replace('-', '_')}.md")
    path = PROMPTS_DIR / fname
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return (
        f"# Role: {role_name}\n"
        "Cite exact file:line evidence, state one-sentence root_cause, "
        "provide inputs -> expected -> actual repro, do not repeat ledger entries, "
        "mark unexecuted claims STATIC, output FindingDraft JSON."
    )


def build_agent_registry() -> dict[str, AgentSpec]:
    """Build immutable mapping of all registered ECC-style subagent roles."""
    registry: dict[str, AgentSpec] = {}
    for name, tools in AGENT_TOOL_MAP.items():
        registry[name] = AgentSpec(
            name=name,
            role_prompt=_load_prompt_text(name),
            allowed_tools=tools,
            output_schema="FindingDraft",
            model_pref=None,
            timeout=60.0,
        )
    return registry


def get_agent_spec(name: str) -> AgentSpec:
    """Lookup a single AgentSpec by role name."""
    reg = build_agent_registry()
    if name not in reg:
        raise KeyError(f"Unknown agent role '{name}'. Available: {sorted(reg)}")
    return reg[name]
