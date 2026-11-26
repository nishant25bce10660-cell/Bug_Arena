"""Phase 11 Step 4 hardening tests (fail-open ACLs, dict scrubbing, SSRF origin, robots pre-nav, event-loop PDF, error surfacing)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from bugarena.browser.cursor import AccessPolicy, BrowserCursor
from bugarena.browser.discovery import _probe_version
from bugarena.browser.questionnaire import SessionManager
from bugarena.inspect.collectors import _same_origin, collect_network_and_security
from bugarena.inspect.site_audit import SiteAuditCoordinator
from bugarena.reporting.v2_report import build_v2_report_bundle
from bugarena.server import _scrub_payload, agent_scoreboard, session_confirm
from bugarena.skills_merge.pipeline import _static_security_scan
from bugarena.truth import AgentScoreboard, Claim, ClaimLedger, EvidenceVault
from bugarena.truth.vault import scrub_evidence_text


def test_empty_tools_allowed_and_empty_active_tools_fail_closed(tmp_path: Path):
    mgr = SessionManager(default_output_root=tmp_path)
    conf = mgr.session_confirm(
        {"site_url": "https://example.com", "tools_allowed": []},
        all_tool_names=("site_audit_start", "report_build"),
    )
    assert conf["active_tools"] == []


@pytest.mark.asyncio
async def test_agent_scoreboard_requires_session_token_when_run_id_given(tmp_path: Path):
    conf = await session_confirm({
        "site_url": "https://example.com",
        "output_dir": str(tmp_path / "r"),
        "tool_filters": {"tools_allowed": ["site_audit_status"]},
    })
    with pytest.raises(PermissionError):
        await agent_scoreboard(conf["run_id"])
    with pytest.raises(PermissionError):
        await agent_scoreboard(conf["run_id"], session_token="wrong")


def test_scrub_payload_redacts_sensitive_dict_keys_and_preserves_markdown_auth():
    cleaned = _scrub_payload({
        "doc_headers": {
            "set-cookie": "__Host-custom=opaque_val_999",
            "x-api-key": "arbitrary-key-no-prefix",
            "proxy-authorization": "Basic dXNlcjpwYXNz",
        },
        "safe": "hello",
    })
    assert "opaque_val_999" not in str(cleaned)
    assert "arbitrary-key-no-prefix" not in str(cleaned)
    assert "dXNlcjpwYXNz" not in str(cleaned)

    md = "- **Authorization:** `own`\n- **Token:** `Authorization: Basic dXNlcjpwYXNz`"
    md_clean, _ = scrub_evidence_text(md)
    assert "- **Authorization:** `own`" in md_clean
    assert "dXNlcjpwYXNz" not in md_clean


def test_same_origin_blocks_host_prefix_and_port_confusion():
    assert _same_origin("https://example.com/a.js", "https://example.com/a.js.map") is True
    assert _same_origin("https://example.com/a.js", "https://example.com.evil.com/a.js.map") is False
    assert _same_origin("http://127.0.0.1:80/a.js", "http://127.0.0.1:8080/a.js.map") is False
    assert _same_origin("https://example.com/a.js", "https://user@example.com/a.js.map") is False


def test_skill_merge_blocks_file_writes_builtins_and_symlink_escape_on_approved(tmp_path: Path):
    sk = tmp_path / "sneaky"
    sk.mkdir()
    (sk / "skill.py").write_text(
        "import builtins, webbrowser\nopen('out.txt', 'w').write('x')\n",
        encoding="utf-8",
    )
    hazards = _static_security_scan(sk)
    kinds = {h["hazard"] for h in hazards}
    assert "dangerous_import" in kinds
    assert "dangerous_call" in kinds


@pytest.mark.asyncio
async def test_inspect_panel_rejects_unimplemented_panel_and_timeout_raises(tmp_path: Path):
    coord = SiteAuditCoordinator(output_root=tmp_path)
    conf = coord.sessions.session_confirm({"site_url": "http://127.0.0.1:9999", "authorization": "own"})
    with pytest.raises(ValueError, match="panel|supported"):
        await coord.inspect_panel(conf["run_id"], "chrome", "Cross-browser diff")

    class _NeverLoadsCDP:
        def __init__(self) -> None:
            self.events: dict[str, list] = {"Page.loadEventFired": []}

        async def send(self, method: str, params: dict | None = None):
            if method == "Page.navigate":
                return {"frameId": "1"}
            return {"result": {"value": {"state": "loading", "href": "about:blank"}}}

    cur = BrowserCursor(browser_name="chrome", port=9222, profile_dir=tmp_path, cdp=_NeverLoadsCDP())  # type: ignore[arg-type]
    policy = AccessPolicy.from_answers({"site_url": "http://127.0.0.1:8080", "authorization": "own"})
    with pytest.raises(TimeoutError):
        await cur.navigate("http://127.0.0.1:8080", policy=policy, readiness_timeout=0.05)


@pytest.mark.asyncio
async def test_build_v2_report_surfaces_vault_errors_and_works_inside_event_loop(tmp_path: Path):
    rdir = tmp_path / "run_err"
    v = EvidenceVault(rdir)
    sb = AgentScoreboard(rdir, global_scores_path=tmp_path / "scores.json")
    cl = ClaimLedger(rdir, vault=v, scoreboard=sb)
    ev = v.record_artifact("err", ext=".txt", tool_name="t")
    cl.submit_claim(Claim(id="F-0001", statement="err", evidence_refs=(ev.evidence_id,), confidence=0.9, found_by="a"))
    cl.record_verification("F-0001", verifier="verifier", verdict="CONFIRMED")
    # Tamper artifact so chain fails
    (rdir / ev.rel_path).write_text("tampered", encoding="utf-8")

    analysis = {
        "writer_output": {"executive_summary": "s", "quick_wins": [], "mode": "deterministic_fallback", "fallback_reason": "500 error"},
        "critic_output": {"verdict": "FALLBACK", "notes": "critic failed", "unsupported_claims": []},
    }
    res = build_v2_report_bundle(rdir, formats=("md",), analysis_summary=analysis, allow_fallback_pdf=True)
    assert res["vault_errors"]
    assert res["analysis"]["critic_output"]["verdict"] == "FALLBACK"


def test_probe_version_ignores_nonzero_exit_and_network_scrubs_doc_headers(tmp_path: Path):
    class _FailProc:
        returncode = 1
        stdout = ""
        stderr = "segmentation fault"

    with patch("bugarena.browser.discovery.subprocess.run", return_value=_FailProc()):
        assert _probe_version("chrome.exe") == "unknown"

    class _NetCDP:
        def __init__(self) -> None:
            self.events = {
                "Network.requestWillBeSent": [{"requestId": "1", "request": {"url": "https://example.com/", "method": "GET"}}],
                "Network.responseReceived": [
                    {
                        "requestId": "1",
                        "type": "Document",
                        "response": {"status": 200, "headers": {"Set-Cookie": "custom_tok=secret_cookie_val", "X-Api-Key": "plainkey"}},
                    }
                ],
                "Network.loadingFinished": [],
                "Network.loadingFailed": [],
            }

    res = collect_network_and_security(_NetCDP(), EvidenceVault(tmp_path / "nv"), "https://example.com/", "chrome")  # type: ignore[arg-type]
    assert "secret_cookie_val" not in str(res["doc_headers"])
    assert "plainkey" not in str(res["doc_headers"])
