"""Phase 11 regression & hardening tests (ACL, AccessPolicy, traversal, CDP/cursor cleanup)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from bugarena.audit.loop import LoopOperator
from bugarena.browser.cdp import CDPClient, CDPError
from bugarena.browser.cursor import AccessPolicy, AuthorizationError, BrowserCursor
from bugarena.browser.questionnaire import SessionManager
from bugarena.server import (
    browser_cursor_list,
    claim_retract,
    inspect_panel,
    project_audit_start,
    report_build,
    session_confirm,
    site_audit_round,
    site_audit_status,
    verify_pack_build,
)


def test_access_policy_parses_string_booleans_and_strict_subdomains():
    policy = AccessPolicy.from_answers({
        "site_url": "https://example.com:8443/app",
        "authorization": "own",
        "access_level": "full_access",
        "respect_robots_txt": "no",
        "allow_subdomains": "false",
    })
    assert policy.respect_robots_txt is False
    assert policy.allow_subdomains is False

    sub_policy = AccessPolicy.from_answers({
        "site_url": "https://example.com:8443/app",
        "authorization": "own",
        "access_level": "full_access",
        "allow_subdomains": "yes",
    })
    assert sub_policy.allow_subdomains is True
    sub_policy.assert_action_allowed("navigate", target_url="https://api.example.com:8443/v1")

    for bad_url in (
        "http://api.example.com:8443/v1",  # scheme downgrade
        "javascript://api.example.com:8443/alert(1)",  # non-http scheme
        "https://evil@api.example.com:8443/v1",  # userinfo spoofing
        "https://evil-example.com:8443/v1",  # unregistered suffix
    ):
        with pytest.raises(AuthorizationError):
            sub_policy.assert_action_allowed("navigate", target_url=bad_url)


def test_access_policy_enforces_robots_disallow():
    policy = AccessPolicy.from_answers({
        "site_url": "https://example.com/",
        "authorization": "neither",
        "respect_robots_txt": True,
    })
    disallows = policy.parse_robots_disallow("User-agent: *\nDisallow: /private/\nDisallow: /admin\n")
    assert "/private/" in disallows
    assert policy.is_path_allowed("https://example.com/public", disallows) is True
    assert policy.is_path_allowed("https://example.com/private/secret", disallows) is False
    assert policy.is_path_allowed("https://example.com/admin", disallows) is False
    with pytest.raises(AuthorizationError):
        policy.assert_action_allowed("navigate", target_url="https://example.com/private/secret", robots_disallow=disallows)


def test_session_manager_blocks_traversal_and_duplicate_run_id_and_nested_config(tmp_path: Path):
    mgr = SessionManager(default_output_root=tmp_path)
    with pytest.raises(ValueError):
        mgr.session_confirm({"site_url": "https://example.com", "run_id": "../escape"})
    with pytest.raises(ValueError):
        mgr.session_confirm({"site_url": "https://example.com", "run_id": "-leading"})

    conf = mgr.session_confirm(
        {
            "site_url": "https://example.com",
            "run_id": "nested_ok_1",
            "output_config": {"output_dir": str(tmp_path / "sub"), "formats": ["md"]},
            "tool_filters": {"tools_allowed": "all", "tools_denied": ["verify_pack_build"]},
            "scope": {"mode": "crawl", "max_pages": 5, "allow_subdomains": "no"},
        },
        all_tool_names=("site_audit_start", "verify_pack_build", "report_build"),
    )
    assert "verify_pack_build" not in conf["active_tools"]
    assert Path(conf["run_dir"]).resolve().is_relative_to((tmp_path / "sub").resolve())

    with pytest.raises(ValueError, match="already exists"):
        mgr.session_confirm({"site_url": "https://example.com", "run_id": "nested_ok_1"})


@pytest.mark.asyncio
async def test_v2_session_scoped_mcp_tools_enforce_token_and_acl(tmp_path: Path):
    conf = await session_confirm({
        "site_url": "https://example.com",
        "authorization": "own",
        "access_level": "full_access",
        "output_dir": str(tmp_path / "reports"),
        "tool_filters": {"tools_denied": ["verify_pack_build"]},
    })
    rid = conf["run_id"]
    tok = conf["session_token"]

    for fn, args in (
        (site_audit_round, (rid,)),
        (site_audit_status, (rid,)),
        (browser_cursor_list, (rid,)),
        (inspect_panel, (rid, "chrome", "Elements")),
        (report_build, (rid,)),
        (verify_pack_build, (rid,)),
        (claim_retract, (rid, "F-0001", "reason")),
    ):
        with pytest.raises(PermissionError):
            await fn(*args, session_token="bad-token")

    # Denied in active_tools must fail even with valid token
    with pytest.raises(PermissionError, match="tools_denied|not enabled|active_tools"):
        await verify_pack_build(rid, session_token=tok)

    # project_audit_start locks mode='read_only' and validates site_run_id before running
    with pytest.raises(PermissionError):
        await project_audit_start(str(tmp_path), mode="fix")
    with pytest.raises(KeyError):
        await project_audit_start(str(tmp_path), site_run_id="nonexistent_run", session_token=tok)


def test_loop_operator_blocks_run_id_traversal(tmp_path: Path):
    op = LoopOperator(state_root=tmp_path / ".bugarena")
    with pytest.raises(ValueError):
        op._find_run_dir("../../etc")


@pytest.mark.asyncio
async def test_cdp_client_rejects_crlf_and_cleans_pending_on_timeout():
    with pytest.raises(ValueError):
        CDPClient("ws://127.0.0.1:9222/devtools/page/1\r\nX-Injected: 1")

    client = CDPClient("ws://127.0.0.1:9222/devtools/page/1")

    async def _noop_send(_op: int, _payload: bytes) -> None:
        return None

    with patch.object(client, "_send_frame", side_effect=_noop_send), pytest.raises(asyncio.TimeoutError):
        await client.send("Runtime.evaluate", {"expression": "1+1"}, timeout=0.01)
    assert client._pending == {}

    # _recv_loop error rejects any waiting pending futures cleanly
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    client._pending[99] = fut
    await client._recv_loop()
    assert fut.done()
    with pytest.raises(CDPError):
        fut.result()


@pytest.mark.asyncio
async def test_browser_cursor_navigate_checks_error_text():
    class _FakeCDP:
        def __init__(self):
            self.events: dict[str, list[dict]] = {"Page.loadEventFired": []}

        async def send(self, method: str, params: dict | None = None):
            if method == "Page.navigate":
                return {"errorText": "net::ERR_ABORTED"}
            return {}

    cur = BrowserCursor(browser_name="chrome", port=9222, profile_dir=Path("."), cdp=_FakeCDP())  # type: ignore[arg-type]
    policy = AccessPolicy.from_answers({"site_url": "http://127.0.0.1:8080", "authorization": "own"})
    with pytest.raises(RuntimeError, match="ERR_ABORTED"):
        await cur.navigate("http://127.0.0.1:8080", policy=policy)
