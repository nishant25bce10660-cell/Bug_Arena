"""Tests for Phase 3 Browser Layer: discovery, questionnaire gate, cursor isolation, passive safety."""

import ast
import asyncio
from pathlib import Path

import pytest

from bugarena.browser import (
    AccessPolicy,
    AuthorizationError,
    BrowserCursor,
    CursorIsolationError,
    SessionManager,
    discover_browsers,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_no_os_input_automation_anywhere_in_src():
    banned = {"pyautogui", "pynput", "SendInput"}
    for py_file in (REPO_ROOT / "src").rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in banned, f"Banned OS input import in {py_file}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in banned, f"Banned OS input import in {py_file}"
        assert "SendInput" not in text, f"SendInput found in {py_file}"


def test_questionnaire_gate_forces_passive_when_neither_and_writes_scope(tmp_path: Path):
    mgr = SessionManager(default_output_root=tmp_path / "bugarena_reports")
    prep = mgr.session_prepare(user_hint="check https://example.com")
    assert len(prep["questions"]) == 13
    assert "detected_browsers" in prep
    assert "api_keys_present" in prep

    # Missing URL rejected cleanly
    with pytest.raises(ValueError, match="site_url"):
        mgr.session_confirm({"authorization": "neither"})

    # authorization="neither" MUST force access_level="passive" even if caller asked for full_access
    conf = mgr.session_confirm({
        "site_url": "https://example.com",
        "authorization": "neither",
        "access_level": "full_access",
        "browsers": ["chrome"],
    })
    assert conf["access_level"] == "passive"
    assert conf["session_token"]
    scope_md = Path(conf["scope_file"]).read_text(encoding="utf-8")
    assert "passive" in scope_md.lower()
    assert "https://example.com" in scope_md


def test_passive_policy_blocks_active_probes_and_rate_limits():
    policy = AccessPolicy.from_answers({
        "site_url": "https://example.com",
        "authorization": "neither",
        "access_level": "full_access",
    })
    assert policy.access_level == "passive"
    assert policy.max_rps <= 2.0
    policy.assert_action_allowed("navigate")
    with pytest.raises(AuthorizationError):
        policy.assert_action_allowed("form_submit")
    with pytest.raises(AuthorizationError):
        policy.assert_action_allowed("fuzz")


def test_cursor_capability_token_prevents_cross_browser_port_access(tmp_path: Path):
    c_chrome = BrowserCursor(browser_name="chrome", port=9222, profile_dir=tmp_path / "p1")
    c_brave = BrowserCursor(browser_name="brave", port=9223, profile_dir=tmp_path / "p2")
    assert c_chrome.cursor_name == "[mcp_chrome]"
    assert c_brave.cursor_name == "[mcp_brave]"

    # Valid own token succeeds
    c_chrome.verify_target(port=9222, capability_token=c_chrome.capability_token)
    # Using chrome's token on brave's port fails cleanly
    with pytest.raises(CursorIsolationError):
        c_brave.verify_target(port=9223, capability_token=c_chrome.capability_token)
    # Using chrome cursor against brave port fails cleanly
    with pytest.raises(CursorIsolationError):
        c_chrome.verify_target(port=9223, capability_token=c_chrome.capability_token)


def test_browser_discovery_detects_installed_browsers():
    found = {b.name: b for b in discover_browsers()}
    assert "chrome" in found and "brave" in found and "helium" in found


@pytest.mark.browser
def test_live_headless_browser_cursor_isolation_and_cleanup(tmp_path: Path):
    browsers = [b for b in discover_browsers() if b.found]
    if not browsers:
        pytest.skip("No Chromium browser installed on host.")
    target = browsers[0]

    async def _run():
        before_pids = BrowserCursor.snapshot_browser_pids()
        cursor = await BrowserCursor.launch(
            browser_name=target.name,
            executable=target.executable,
            headless=True,
        )
        try:
            assert cursor.cursor_name == f"[mcp_{target.name}]"
            assert cursor.port > 0
            assert cursor.profile_dir.exists()
            ver = await cursor.cdp.send("Browser.getVersion")
            assert "product" in ver
        finally:
            await cursor.close()
        assert not cursor.profile_dir.exists()
        after_pids = BrowserCursor.snapshot_browser_pids()
        assert before_pids == after_pids

    asyncio.run(_run())
