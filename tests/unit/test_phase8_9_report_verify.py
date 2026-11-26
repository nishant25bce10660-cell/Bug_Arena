"""Tests for Phases 8 & 9: Section 1 run folder, REPORT.md/REPORT.pdf, per-finding dirs, and offline verify.py."""

import base64
import subprocess
import sys
from pathlib import Path

import pytest

from bugarena.browser import discover_browsers
from bugarena.inspect.matrix import InspectCoverageMatrix
from bugarena.reporting.v2_report import build_v2_report_bundle
from bugarena.truth import AgentScoreboard, Claim, ClaimLedger, EvidenceVault, TranscriptLogger
from bugarena.verify import build_verify_pack

_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _seed_run_folder(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "scope_and_authorization.md").write_text(
        "# Scope & Authorization\n- Target: https://example.com\n- Authorization: own\n- Access: full_access\n",
        encoding="utf-8",
    )
    InspectCoverageMatrix(run_dir).write_markdown()
    vault = EvidenceVault(run_dir)
    sb = AgentScoreboard(run_dir, global_scores_path=run_dir.parent / "agent_scores.json")
    ledger = ClaimLedger(run_dir, vault=vault, scoreboard=sb)
    tx = TranscriptLogger(run_dir)

    ev_txt = vault.record_artifact(
        b"Uncaught TypeError: Cannot read properties of null at app.js:42",
        ext=".txt",
        tool_name="cdp.console",
        args_summary="https://example.com",
    )
    ev_png = vault.record_artifact(
        _PNG_1X1,
        ext=".png",
        tool_name="cdp.captureScreenshot_annotated",
        args_summary="https://example.com",
        mime_type="image/png",
        is_binary=True,
    )
    tx.log(agent="console-analyst", cursor="[mcp_chrome]", tool="cdp.console", args={"url": "https://example.com"}, result_bytes=b"ok")

    c_conf = Claim(
        id="F-0001",
        statement="Null dereference at app.js:42 breaks checkout button",
        evidence_refs=(ev_txt.evidence_id, ev_png.evidence_id),
        quoted_spans=("Cannot read properties of null",),
        cited_numbers=("42",),
        confidence=0.92,
        found_by="console-analyst",
        evidence_type="DYNAMIC",
        proposed_severity="High",
        where_found={"url": "https://example.com", "panel": "Console", "selector": "#checkout", "script_url": "app.js:42"},
        how_it_occurs="Missing null guard before reading property.",
        repro_steps=("Open https://example.com", "Click #checkout"),
        fix_guidance="Add optional chaining `obj?.prop`.",
        browsers_affected=("chrome",),
    )
    ledger.submit_claim(c_conf, common_path_broken=True)
    ledger.record_verification("F-0001", verifier="verifier", verdict="CONFIRMED")

    # Unverified claim MUST stay out of CONFIRMED list and go into unverified_leads.md
    c_unv = Claim(
        id="F-0002",
        statement="Possible cache header omission",
        evidence_refs=(ev_txt.evidence_id,),
        confidence=0.4,
        found_by="network-analyst",
        evidence_type="STATIC",
        proposed_severity="Low",
    )
    ledger.submit_claim(c_unv)


def test_build_v2_report_and_verify_pack_offline_tamper_detection(tmp_path: Path):
    run_dir = tmp_path / "run_v2"
    _seed_run_folder(run_dir)

    rep = build_v2_report_bundle(run_dir, formats=("md", "pdf"), allow_fallback_pdf=True)
    pack = build_verify_pack(run_dir)

    for rel in (
        "REPORT.md",
        "REPORT.pdf",
        "report.json",
        "scope_and_authorization.md",
        "coverage_matrix.md",
        "unverified_leads.md",
        "evidence/manifest.jsonl",
        "transcripts/transcript.jsonl",
        "agents/scoreboard.json",
        "agents/corrections_log.md",
        "findings/F-0001/finding.json",
        "findings/F-0001/repro.md",
        "findings/F-0001/repro_script.py",
        "findings/F-0001/fix.md",
        "verify/VERIFY_PROMPT.md",
        "verify/verify.py",
        "verify/claims.json",
        "verify/README.txt",
    ):
        assert (run_dir / rel).exists(), f"Missing Section 1 file: {rel}"

    assert (run_dir / "REPORT.pdf").read_bytes().startswith(b"%PDF-")
    md_text = (run_dir / "REPORT.md").read_text(encoding="utf-8")
    assert "F-0001" in md_text
    assert "Appendix A" in md_text and "Appendix D" in md_text
    unv_text = (run_dir / "unverified_leads.md").read_text(encoding="utf-8")
    assert "F-0002" in unv_text
    assert rep["confirmed_count"] == 1
    assert pack["verify_script"]

    # Offline stdlib-only verify.py passes on clean run folder
    ok_res = subprocess.run(
        [sys.executable, str(run_dir / "verify" / "verify.py")],
        cwd=str(run_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok_res.returncode == 0, ok_res.stdout + ok_res.stderr

    # Tamper with artifact -> verify.py MUST exit non-zero!
    (run_dir / "evidence" / "raw" / "EV-0001.txt").write_text("tampered", encoding="utf-8")
    bad_res = subprocess.run(
        [sys.executable, str(run_dir / "verify" / "verify.py")],
        cwd=str(run_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad_res.returncode != 0
    assert "mismatch" in (bad_res.stdout + bad_res.stderr).lower()


@pytest.mark.browser
def test_live_chromium_print_to_pdf_renders_valid_pdf_with_embedded_images(tmp_path: Path):
    if not any(b.found for b in discover_browsers()):
        pytest.skip("No Chromium installed")
    run_dir = tmp_path / "run_pdf_live"
    _seed_run_folder(run_dir)
    rep = build_v2_report_bundle(run_dir, formats=("md", "pdf"), allow_fallback_pdf=False)
    pdf_bytes = (run_dir / "REPORT.pdf").read_bytes()
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 5000
    assert rep["pdf_engine"] == "chromium"
