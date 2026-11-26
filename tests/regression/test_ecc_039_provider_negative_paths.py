"""Regression tests for ECC-039: non-tautological security checks and MockTransport coverage across providers."""

import json
from pathlib import Path

import httpx
import pytest

from bugarena.tournament.providers import dispatcher as disp_mod
from bugarena.tournament.providers.dispatcher import MultiModelDispatcher


def test_ecc_039_no_tautology_in_test_security():
    sec_test = Path(__file__).resolve().parents[1] / "unit" / "test_security.py"
    src = sec_test.read_text(encoding="utf-8")
    assert 'or r\'\\"\\"\\"\' in test_code' not in src
    assert "ast.parse" in src


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "env_key", "model_name", "payload"),
    [
        (
            "_call_gemini",
            "GEMINI_API_KEY",
            "gemma-4-26b-a4b-it",
            {"candidates": [{"content": {"parts": [{"text": "```diff\n--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a=1\n+a=2\n```"}]}}]},
        ),
        (
            "_call_openai",
            "OPENAI_API_KEY",
            "gpt-5.4",
            {"choices": [{"message": {"content": "```diff\n--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a=1\n+a=2\n```"}}]},
        ),
        (
            "_call_deepseek",
            "DEEPSEEK_API_KEY",
            "deepseek-reasoner",
            {"choices": [{"message": {"content": "```diff\n--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a=1\n+a=2\n```"}}]},
        ),
        (
            "_call_groq",
            "GROQ_API_KEY",
            "qwen/qwen3.8-27b",
            {"choices": [{"message": {"content": "```diff\n--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a=1\n+a=2\n```"}}]},
        ),
        (
            "_call_ollama",
            None,
            "ollama/qwen3.5",
            {"response": "```diff\n--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a=1\n+a=2\n```"},
        ),
    ],
)
async def test_ecc_039_all_providers_success_and_error_paths(
    monkeypatch, method_name, env_key, model_name, payload
):
    if env_key:
        monkeypatch.setenv(env_key, "fake-key-for-mock-test")

    real_async_client = httpx.AsyncClient
    dispatcher = MultiModelDispatcher(timeout_seconds=5.0)
    fn = getattr(dispatcher, method_name)

    # 1. Success response via MockTransport
    monkeypatch.setattr(
        disp_mod.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(
            transport=httpx.MockTransport(
                lambda _req: httpx.Response(200, content=json.dumps(payload).encode("utf-8"))
            ),
            **kwargs,
        ),
    )
    diff, _ = await fn(model_name, "sys", "usr")
    assert "--- a/x.py" in diff and "+a=2" in diff

    # 2. HTTP 500 error returns empty diff + provider error message
    monkeypatch.setattr(
        disp_mod.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(
            transport=httpx.MockTransport(lambda _req: httpx.Response(500, text="server error")),
            **kwargs,
        ),
    )
    diff_err, msg_err = await fn(model_name, "sys", "usr")
    assert diff_err == ""
    assert "error" in msg_err.lower()

    # 3. Malformed JSON response returns empty diff + error without crashing
    monkeypatch.setattr(
        disp_mod.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(
            transport=httpx.MockTransport(lambda _req: httpx.Response(200, text="{broken json")),
            **kwargs,
        ),
    )
    diff_bad, msg_bad = await fn(model_name, "sys", "usr")
    assert diff_bad == ""
    assert "error" in msg_bad.lower()
