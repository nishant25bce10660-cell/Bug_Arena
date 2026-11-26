"""Regression test for ECC-036: check_api_keys --dry-run, JSON error guard, and no user-specific paths."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_api_keys.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("check_api_keys", SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ecc_036_no_hardcoded_user_path_and_dry_run_cli():
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "nisha" not in text
    assert "--dry-run" in text

    res = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert res.returncode == 0
    assert "DRY_RUN" in res.stdout or "dry-run" in res.stdout.lower()


@pytest.mark.asyncio
async def test_ecc_036_check_ollama_handles_non_json_response(monkeypatch):
    mod = _load_script_module()

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        mod.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=httpx.MockTransport(_handler), **kwargs),
    )

    out = await mod.check_ollama()
    assert out["status"] in {"ERROR", "OFFLINE"}
    assert "Local Ollama" in out["provider"]
