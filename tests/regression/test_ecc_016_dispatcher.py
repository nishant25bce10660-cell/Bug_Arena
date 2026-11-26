"""Regression test for ECC-016 (BA-010): MultiModelDispatcher routing, overrides, null safety, o-series."""

import asyncio
import json
from unittest.mock import patch

import httpx

from bugarena.models.agent import PersonaType
from bugarena.models.bug import BugSpec
from bugarena.models.repro import ReproTestSpec
from bugarena.tournament.providers.dispatcher import (
    MultiModelDispatcher,
    get_recommended_model_for_persona,
)


def test_ecc_016_defensive_guardian_uses_deepseek_when_only_deepseek_key(monkeypatch):
    for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds_mock")
    assert "deepseek" in get_recommended_model_for_persona(PersonaType.DEFENSIVE_GUARDIAN).lower()


def test_ecc_016_ollama_routing_explicit_override_null_content_and_anthropic_fallback(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq_k")
    monkeypatch.setenv("GEMINI_API_KEY", "gem_k")
    monkeypatch.setenv("OPENAI_API_KEY", "oai_k")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    requests_seen: list[tuple[str, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content.decode("utf-8"))
        requests_seen.append((str(req.url), body))
        if "11434" in str(req.url):
            return httpx.Response(200, json={"response": None})
        return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})

    orig_client = httpx.AsyncClient

    def fake_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return orig_client(**kwargs)

    d = MultiModelDispatcher()
    bug = BugSpec(bug_id="b", repo_path=".")
    repro = ReproTestSpec(test_file_path="t.py", test_code="pass", red_baseline_verified=True)

    with patch("httpx.AsyncClient", side_effect=fake_client):
        # 1. ollama/llama3.2 routes to localhost:11434 and survives null response
        diff1, expl1 = asyncio.run(
            d.generate_patch(PersonaType.SURGICAL_MINIMALIST, bug, repro, model_override="ollama/llama3.2")
        )
        assert diff1 == "" and isinstance(expl1, str)
        assert "11434" in requests_seen[-1][0]

        # 2. Explicit gemini-2.0-flash is NOT rewritten to gemma-4-26b-a4b-it
        asyncio.run(
            d.generate_patch(PersonaType.SURGICAL_MINIMALIST, bug, repro, model_override="gemini-2.0-flash")
        )
        assert "gemini-2.0-flash:generateContent" in requests_seen[-1][0]

        # 3. Explicit groq llama-3.3-70b-versatile is NOT rewritten and survives content: None
        asyncio.run(
            d.generate_patch(PersonaType.SURGICAL_MINIMALIST, bug, repro, model_override="llama-3.3-70b-versatile")
        )
        assert requests_seen[-1][1]["model"] == "llama-3.3-70b-versatile"

        # 4. OpenAI o3-mini omits 'temperature' and handles content: None
        asyncio.run(
            d.generate_patch(PersonaType.ARCHITECTURAL_FIXER, bug, repro, model_override="o3-mini")
        )
        assert "temperature" not in requests_seen[-1][1]

        # 5. _call_anthropic fallback with only GROQ_API_KEY delegates to groq (NOT Missing OPENAI_API_KEY)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        _d5, e5 = asyncio.run(d._call_anthropic("claude-3-5-sonnet", "sys", "prompt"))
        assert "Missing OPENAI_API_KEY" not in e5
        assert "api.groq.com" in requests_seen[-1][0]
