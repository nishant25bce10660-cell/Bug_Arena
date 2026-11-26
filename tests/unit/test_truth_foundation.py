"""Tests for Phase 2 Truth Foundation: EvidenceVault, ClaimLedger, CitationChecker, Scoreboard, Transcript."""

import json
from pathlib import Path

import pytest

from bugarena.truth import (
    AgentScoreboard,
    CitationChecker,
    Claim,
    ClaimLedger,
    ClaimStatus,
    EvidenceVault,
    TranscriptLogger,
    apply_site_severity_rubric,
)


def test_evidence_vault_scrubs_pii_and_detects_tampering(tmp_path: Path):
    run_dir = tmp_path / "run_001"
    vault = EvidenceVault(run_dir)

    raw_har = json.dumps({
        "url": "https://example.com/api",
        "headers": {
            "Authorization": "Bearer super_secret_jwt_12345",
            "Cookie": "sessionid=abc987xyz; csrftoken=tok123",
        },
        "contact": "alice@example.com",
        "phone": "+1-555-867-5309",
        "status": 500,
    }).encode("utf-8")

    ev = vault.record_artifact(
        data=raw_har,
        ext=".json",
        tool_name="cdp.network",
        args_summary="GET /api",
        mime_type="application/json",
    )
    assert ev.evidence_id == "EV-0001"
    stored_text = (run_dir / ev.rel_path).read_text(encoding="utf-8")
    assert "super_secret_jwt_12345" not in stored_text
    assert "abc987xyz" not in stored_text
    assert "alice@example.com" not in stored_text

    redactions = json.loads((run_dir / "evidence" / "redactions.json").read_text(encoding="utf-8"))
    assert len(redactions) >= 1
    assert vault.verify_chain()["valid"] is True

    # Tamper with artifact -> hash chain verification MUST fail!
    (run_dir / ev.rel_path).write_text("tampered", encoding="utf-8")
    check = vault.verify_chain()
    assert check["valid"] is False
    assert "EV-0001" in check["errors"][0]


def test_lying_agent_rejected_by_vault_citation_and_severity_rubric(tmp_path: Path):
    run_dir = tmp_path / "run_002"
    vault = EvidenceVault(run_dir)
    scoreboard = AgentScoreboard(run_dir, global_scores_path=tmp_path / "agent_scores.json")
    ledger = ClaimLedger(run_dir, vault=vault, scoreboard=scoreboard)

    ev = vault.record_artifact(
        data=b"Console Error: TypeError: Cannot read property 'id' of null at app.js:42",
        ext=".txt",
        tool_name="cdp.console",
        args_summary="Runtime.consoleAPICalled",
    )

    # 1. No evidence_refs -> schema rejects immediately
    with pytest.raises(ValueError, match="evidence_refs"):
        Claim(
            id="C-001",
            statement="Missing button",
            evidence_refs=(),
            confidence=0.9,
            found_by="lying-agent",
            evidence_type="DYNAMIC",
            proposed_severity="High",
            limitations="none",
        )

    # 2. Fabricated evidence ID -> rejected and penalized on scoreboard
    fake_claim = Claim(
        id="C-002",
        statement="Screenshot proves server RCE",
        evidence_refs=("EV-9999",),
        confidence=0.99,
        found_by="lying-agent",
        evidence_type="DYNAMIC",
        proposed_severity="Critical",
        limitations="none",
    )
    res_fake = ledger.submit_claim(fake_claim)
    assert res_fake["accepted"] is False
    assert res_fake["status"] == ClaimStatus.REJECTED

    # 3. Quote not present in cited artifact -> CitationChecker rejects & penalizes
    misquoted_claim = Claim(
        id="C-003",
        statement='Console printed "SQL syntax error near DROP TABLE"',
        evidence_refs=(ev.evidence_id,),
        quoted_spans=("SQL syntax error near DROP TABLE",),
        confidence=0.95,
        found_by="lying-agent",
        evidence_type="DYNAMIC",
        proposed_severity="Critical",
        limitations="only checked home page",
    )
    res_quote = ledger.submit_claim(misquoted_claim)
    assert res_quote["accepted"] is False
    assert "citation" in res_quote["reason"].lower()

    score_lying = scoreboard.get_agent_score("lying-agent")
    assert score_lying.honesty < 0.7
    assert score_lying.fabrication_failures >= 2

    # 4. Honest claim with real quote + STATIC severity capped below Critical
    sev, justification = apply_site_severity_rubric(
        proposed="Critical",
        evidence_type="STATIC",
        security_exploitable=True,
        core_flow_lost=False,
        common_path_broken=True,
        a11y_or_perf_barrier=False,
    )
    assert sev != "Critical"
    assert justification

    good_claim = Claim(
        id="C-004",
        statement='Console logged "Cannot read property \'id\' of null"',
        evidence_refs=(ev.evidence_id,),
        quoted_spans=("Cannot read property 'id' of null",),
        cited_numbers=("42",),
        confidence=0.9,
        found_by="honest-agent",
        evidence_type="DYNAMIC",
        proposed_severity="High",
        limitations="desktop viewport only",
    )
    res_good = ledger.submit_claim(good_claim)
    assert res_good["accepted"] is True
    assert CitationChecker.verify_claim_citations(good_claim, vault)["valid"] is True


def test_self_retraction_vs_verifier_disproval_and_transcript(tmp_path: Path):
    run_dir = tmp_path / "run_003"
    vault = EvidenceVault(run_dir)
    scoreboard = AgentScoreboard(run_dir, global_scores_path=tmp_path / "agent_scores.json")
    ledger = ClaimLedger(run_dir, vault=vault, scoreboard=scoreboard)
    transcript = TranscriptLogger(run_dir)

    transcript.log(
        agent="console-analyst",
        cursor="[mcp_chrome]",
        tool="cdp.console",
        args={"url": "https://example.com", "token": "sk-secret-value-12345"},
        result_bytes=b"hello",
        status="ok",
    )
    t_text = (run_dir / "transcripts" / "transcript.jsonl").read_text(encoding="utf-8")
    assert "sk-secret-value-12345" not in t_text
    assert "[mcp_chrome]" in t_text

    ev = vault.record_artifact(b"minor console warning", ext=".txt", tool_name="cdp.console")
    c1 = Claim(
        id="C-010",
        statement="Warning caused broken checkout",
        evidence_refs=(ev.evidence_id,),
        quoted_spans=("minor console warning",),
        confidence=0.8,
        found_by="agent-a",
        evidence_type="DYNAMIC",
        proposed_severity="High",
        limitations="unverified",
    )
    c2 = Claim(
        id="C-011",
        statement="Warning caused broken login",
        evidence_refs=(ev.evidence_id,),
        quoted_spans=("minor console warning",),
        confidence=0.8,
        found_by="agent-b",
        evidence_type="DYNAMIC",
        proposed_severity="High",
        limitations="unverified",
    )
    ledger.submit_claim(c1)
    ledger.submit_claim(c2)

    # agent-a self-retracts honestly; agent-b is caught by verifier
    ledger.retract_claim("C-010", reason="Re-checked DOM; checkout works fine", by_agent="agent-a")
    ledger.record_verification("C-011", verifier="verifier-1", verdict="NOT_REPRODUCED", detail="login works")

    assert scoreboard.get_agent_score("agent-a").honesty > scoreboard.get_agent_score("agent-b").honesty
    corr_log = (run_dir / "agents" / "corrections_log.md").read_text(encoding="utf-8")
    assert "C-010" in corr_log and "C-011" in corr_log
