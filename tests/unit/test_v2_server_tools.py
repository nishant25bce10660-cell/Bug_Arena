"""End-to-end tests for all 26 MCP tools wired in server.py (v1 + v2)."""

import importlib.util
from pathlib import Path

import pytest

from bugarena.browser import discover_browsers
from bugarena.server import (
    agent_scoreboard,
    browser_cursor_list,
    claim_retract,
    mcp,
    merge_both_skills,
    project_audit_start,
    report_build,
    session_confirm,
    session_prepare,
    site_audit_start,
    site_audit_status,
    verify_pack_build,
)

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "site_bugs"


def _serve_fixture_site():
    spec = importlib.util.spec_from_file_location("site_bugs_server_v2", _FIXTURE_DIR / "server.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.serve_fixture_site()


@pytest.mark.asyncio
async def test_all_26_mcp_tools_registered_with_descriptions():
    tools = await mcp.list_tools()
    assert len(tools) == 26
    for t in tools:
        assert (t.description or "").strip(), f"Empty description on {t.name}"


@pytest.mark.asyncio
async def test_v2_mcp_tools_project_only_and_merge_dry_run(tmp_path: Path):
    prep = await session_prepare(user_hint="audit site")
    assert len(prep["questions"]) == 13

    conf = await session_confirm({
        "site_url": "https://example.com",
        "authorization": "neither",
        "access_level": "full_access",
        "output_dir": str(tmp_path / "reports"),
    })
    assert conf["access_level"] == "passive"

    # Reject site_audit_start without valid session_token
    with pytest.raises(PermissionError):
        await site_audit_start("https://example.com", conf["run_id"], "wrong-token")

    cursors = await browser_cursor_list(conf["run_id"], session_token=conf["session_token"])
    assert cursors["run_id"] == conf["run_id"]

    # Project-only audit without any browser works cleanly
    proj = tmp_path / "sample_proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "ok.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    p_res = await project_audit_start(str(proj))
    assert p_res["project_run_id"]

    # merge_both_skills MCP tool defaults dry_run=True
    sk = tmp_path / "clean_sk"
    sk.mkdir()
    (sk / "skill.py").write_text('def hello(): return {"ok": True}\nTOOLS = {"hello": hello}\n', encoding="utf-8")
    m_res = await merge_both_skills(str(sk), output_root=str(tmp_path / "merged"))
    assert m_res["status"] == "DRY_RUN_PASSED"
    assert m_res["primary_mcp"] == "bugarena"


@pytest.mark.browser
@pytest.mark.asyncio
async def test_full_v2_site_audit_and_verify_pack_across_installed_browsers(tmp_path: Path):
    installed = [b.name for b in discover_browsers() if b.found]
    if not installed:
        pytest.skip("No Chromium browsers installed")

    with _serve_fixture_site() as base_url:
        conf = await session_confirm({
            "site_url": base_url,
            "authorization": "own",
            "access_level": "full_access",
            "browsers": installed,
            "output_dir": str(tmp_path / "bugarena_reports"),
        })
        rid = conf["run_id"]
        tok = conf["session_token"]
        audit_res = await site_audit_start(base_url, rid, tok, headless=True)
        assert audit_res["confirmed_count"] >= 10
        st = await site_audit_status(rid, session_token=tok)
        assert st["vault_valid"] is True

        rep = await report_build(rid, formats=["md", "pdf"], session_token=tok)
        assert Path(rep["report_md"]).is_file()
        assert Path(rep["report_pdf"]).read_bytes().startswith(b"%PDF-")

        vp = await verify_pack_build(rid, session_token=tok)
        assert Path(vp["verify_script"]).is_file()
        assert Path(vp["verify_prompt"]).is_file()

        sb = await agent_scoreboard(rid)
        assert len(sb["agents"]) >= 1

        # Claim retraction preserves log and adjusts score cleanly
        ret = await claim_retract(rid, "F-0001", "Retraction smoke check", agent_name="console-analyst", session_token=tok)
        assert ret["status"] == "RETRACTED"
