"""Subagent execution engine supporting grounded offline analysis and schema-validated LLM calls."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from bugarena.agents.base import AgentRunResult, AgentSpec
from bugarena.audit.detectors import run_offline_detector
from bugarena.audit.ledger import Finding, FindingDraft
from bugarena.audit.tools import execute_grounding_tool
from bugarena.tournament.providers.dispatcher import MultiModelDispatcher

AgentLLMCaller = Callable[[AgentSpec, str], Awaitable[str]]


def _extract_json_array(raw_text: str) -> list[dict[str, Any]]:
    clean = raw_text.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        clean = "\n".join(lines).strip()
    parsed = json.loads(clean)
    if isinstance(parsed, dict) and "findings" in parsed:
        parsed = parsed["findings"]
    if not isinstance(parsed, list):
        raise TypeError("Agent JSON output must be a list of FindingDraft objects")
    return parsed


class AgentRunner:
    """Runs an ECC-style AgentSpec with retries, schema validation, and cost/time caps."""

    def __init__(
        self,
        dispatcher: MultiModelDispatcher | None = None,
        *,
        max_retries: int = 2,
        max_cost_usd: float = 0.25,
    ):
        self.dispatcher = dispatcher or MultiModelDispatcher()
        self.max_retries = max_retries
        self.max_cost_usd = max_cost_usd

    def _build_grounding_context(
        self,
        spec: AgentSpec,
        repo_path: Path,
        existing_findings: tuple[Finding, ...],
    ) -> tuple[str, list[str]]:
        tool_calls: list[str] = []
        snippets: list[str] = []

        # Ledger injection so agent never duplicates existing findings (Section 4)
        ledger_lines = [
            f"- {f.id} [{f.state.value}] {f.location.file}:{f.location.line_start} :: {f.title}"
            for f in existing_findings[:100]
        ]
        snippets.append("## Existing Ledger (Do NOT re-report these)\n" + ("\n".join(ledger_lines) or "Empty"))

        # Permitted grounding snapshot
        for tool_name in ("git_ls", "ast_scan", "radon_cc", "ruff_json"):
            if "all" in spec.allowed_tools or tool_name in spec.allowed_tools:
                try:
                    out = execute_grounding_tool(tool_name, spec.allowed_tools, repo_path)
                    tool_calls.append(tool_name)
                    snippets.append(f"## Tool {tool_name}\n{json.dumps(out)[:3000]}")
                except (OSError, ValueError, PermissionError, KeyError) as exc:
                    snippets.append(f"## Tool {tool_name} error\n{exc}")

        return "\n\n".join(snippets), tool_calls

    async def run_agent(
        self,
        spec: AgentSpec,
        repo_path: Path | str,
        *,
        existing_findings: tuple[Finding, ...] = (),
        auto_generate: bool = False,
        llm_caller: AgentLLMCaller | None = None,
    ) -> AgentRunResult:
        """
        Execute one subagent role.
        - If llm_caller is supplied or auto_generate=True: invoke LLM with retries & Pydantic validation.
        - If auto_generate=False (default safe/offline mode): run grounded offline specialist detector.
        """
        start = time.perf_counter()
        repo = Path(repo_path).resolve()

        if not auto_generate and llm_caller is None:
            drafts = await asyncio.to_thread(
                run_offline_detector, spec.name, repo, spec.allowed_tools
            )
            seen_keys = {
                (f.location.file.lower(), f.title.lower()) for f in existing_findings
            }
            filtered = tuple(
                d for d in drafts if (d.location.file.lower(), d.title.lower()) not in seen_keys
            )
            return AgentRunResult(
                agent_name=spec.name,
                findings=filtered,
                raw_output=json.dumps([d.model_dump() for d in filtered]),
                duration_seconds=round(time.perf_counter() - start, 3),
                tool_calls=spec.allowed_tools,
                cost_usd=0.0,
            )

        context_text, used_tools = await asyncio.to_thread(
            self._build_grounding_context, spec, repo, existing_findings
        )
        prompt = (
            f"{spec.role_prompt}\n\n{context_text}\n\n"
            "Return ONLY a JSON array of objects matching FindingDraft schema."
        )

        last_err: str | None = None
        raw_out = ""
        invalid_json_err = False

        for _attempt in range(max(1, self.max_retries)):
            try:
                if llm_caller is not None:
                    raw_out = await asyncio.wait_for(
                        llm_caller(spec, prompt), timeout=spec.timeout
                    )
                else:
                    # Gated paid API path via MultiModelDispatcher raw text helper
                    raw_out = await asyncio.wait_for(
                        self._call_dispatcher_text(spec, prompt), timeout=spec.timeout
                    )
                items = _extract_json_array(raw_out)
                validated = tuple(FindingDraft.model_validate(item) for item in items)
                return AgentRunResult(
                    agent_name=spec.name,
                    findings=validated,
                    raw_output=raw_out[:8000],
                    duration_seconds=round(time.perf_counter() - start, 3),
                    tool_calls=tuple(used_tools),
                    cost_usd=0.01,
                )
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                invalid_json_err = True
                last_err = f"Schema/JSON validation error: {exc}"
            except (TimeoutError, OSError) as exc:
                last_err = f"Execution/timeout error: {exc}"

        return AgentRunResult(
            agent_name=spec.name,
            findings=(),
            raw_output=raw_out[:4000],
            error=last_err,
            invalid_json_error=invalid_json_err,
            duration_seconds=round(time.perf_counter() - start, 3),
            tool_calls=tuple(used_tools),
            cost_usd=0.0,
        )

    async def _call_dispatcher_text(self, spec: AgentSpec, prompt: str) -> str:
        model = spec.model_pref or "gemini"
        if "gemini" in model.lower() or "gemma" in model.lower():
            _d, text = await self.dispatcher._call_gemini(model, spec.role_prompt, prompt)
            return text
        if "deepseek" in model.lower():
            _d, text = await self.dispatcher._call_deepseek(model, spec.role_prompt, prompt)
            return text
        if "groq" in model.lower() or "qwen" in model.lower() or "llama" in model.lower():
            _d, text = await self.dispatcher._call_groq(model, spec.role_prompt, prompt)
            return text
        if "ollama" in model.lower():
            _d, text = await self.dispatcher._call_ollama(model, spec.role_prompt, prompt)
            return text
        _d, text = await self.dispatcher._call_openai(model, spec.role_prompt, prompt)
        return text
