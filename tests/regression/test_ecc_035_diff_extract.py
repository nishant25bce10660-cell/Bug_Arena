"""Regression test for ECC-035 (BA-011): git diff fence extraction and timeout propagation."""

import asyncio
from unittest.mock import patch

import httpx

from bugarena.models.agent import PersonaType
from bugarena.models.bug import BugSpec
from bugarena.models.repro import ReproTestSpec
from bugarena.tournament.providers.dispatcher import (
    MultiModelDispatcher,
    extract_diff_and_explanation,
)


def test_ecc_035_extract_diff_handles_git_header_crlf_and_prose():
    fenced = (
        "Here is the patch:\r\n"
        "```diff\r\n"
        "diff --git a/src/a.py b/src/a.py\r\n"
        "index 1234567..89abcdef 100644\r\n"
        "--- a/src/a.py\r\n"
        "+++ b/src/a.py\r\n"
        "@@ -1,1 +1,1 @@\r\n"
        "-x = 1\r\n"
        "+x = 2\r\n"
        "```\r\n"
        "Hope that helps!"
    )
    diff, expl = extract_diff_and_explanation(fenced)
    assert "```" not in diff
    assert "Hope that helps!" not in diff
    assert "--- a/src/a.py" in diff
    assert "+x = 2" in diff
    assert "Here is the patch" in expl

    unfenced = (
        "Explanation first.\n"
        "--- a/src/b.py\n"
        "+++ b/src/b.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "+new\n"
        "And here is a trailing explanation sentence."
    )
    diff2, expl2 = extract_diff_and_explanation(unfenced)
    assert "trailing explanation" not in diff2
    assert "Explanation first" in expl2


def test_ecc_035_timeout_seconds_propagated_to_httpx_client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test_key")
    seen_timeouts = []

    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    orig_client = httpx.AsyncClient

    def fake_client(**kwargs):
        seen_timeouts.append(kwargs.get("timeout"))
        kwargs["transport"] = httpx.MockTransport(handler)
        return orig_client(**kwargs)

    d = MultiModelDispatcher(timeout_seconds=12.0)
    bug = BugSpec(bug_id="b", repo_path=".")
    repro = ReproTestSpec(test_file_path="t.py", test_code="pass", red_baseline_verified=True)
    with patch("httpx.AsyncClient", side_effect=fake_client):
        asyncio.run(
            d.generate_patch(
                PersonaType.SURGICAL_MINIMALIST,
                bug,
                repro,
                model_override="gpt-4o-mini",
                timeout_seconds=7.5,
            )
        )
    assert seen_timeouts == [7.5]
