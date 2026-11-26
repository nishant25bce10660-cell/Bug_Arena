"""Tests for Phases 5, 6, and 7: v2 agent roster, site audit loop, VLQ source-map linking, and Gemini/Grok analysis."""

import json
from pathlib import Path

import httpx
import pytest

from bugarena.agents import SITE_ANALYST_ROLES, build_agent_registry
from bugarena.inspect.site_audit import SiteAuditCoordinator
from bugarena.linking import link_site_and_project_findings, resolve_source_location
from bugarena.tournament.providers import dispatcher as disp_mod
from bugarena.tournament.providers.cross_vendor import analyze_findings_cross_vendor
from bugarena.tournament.providers.dispatcher import MultiModelDispatcher
from bugarena.truth import AgentScoreboard, Claim, ClaimLedger, EvidenceVault


def test_v2_subagent_roster_and_prompts_complete():
    reg = build_agent_registry()
    expected = {
        *SITE_ANALYST_ROLES,
        "report-writer",
        "verifier",
        "honesty-auditor",
        "merge-analyst",
    }
    assert len(SITE_ANALYST_ROLES) == 8
    for role in expected:
        assert role in reg, f"Missing v2 role {role}"
        assert reg[role].role_prompt.strip()


def test_vlq_sourcemap_decoder_and_site_project_linking(tmp_path: Path):
    project = tmp_path / "proj"
    (project / "src" / "frontend").mkdir(parents=True)
    (project / "src" / "frontend" / "app.ts").write_text("line1\nline2\nline3\n", encoding="utf-8")

    smap = {
        "version": 3,
        "sources": ["src/frontend/app.ts"],
        "mappings": "AAAA;AACA;AACA",
    }
    loc = resolve_source_location(smap, gen_line=2, gen_col=0)
    assert loc is not None
    assert loc["source"] == "src/frontend/app.ts"
    assert loc["line"] == 2

    site_findings = [
        {
            "id": "C-001",
            "title": "Null dereference at app.js:2",
            "where_found": {"url": "http://127.0.0.1/index.html", "script_url": "http://127.0.0.1/app.js", "line": 2, "col": 0},
        },
        {
            "id": "C-002",
            "title": "Missing CSP header",
            "where_found": {"url": "http://127.0.0.1/index.html"},
        },
    ]
    project_findings = [
        {"id": "P-001", "file": "src/backend/auth.py", "line": 10, "title": "Auth check"}
    ]
    linked = link_site_and_project_findings(
        site_findings=site_findings,
        project_findings=project_findings,
        source_maps={"http://127.0.0.1/app.js": smap},
        project_path=project,
    )
    statuses = {x["id"]: x["linkage_status"] for x in linked}
    assert statuses["C-001"] == "linked"
    assert statuses["C-002"] == "site_only"
    assert statuses["P-001"] == "project_only"
    c1 = next(x for x in linked if x["id"] == "C-001")
    assert c1["where_found"]["project_file"] == "src/frontend/app.ts"


@pytest.mark.asyncio
async def test_xai_grok_route_and_cross_vendor_writer_critic_split(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setenv("XAI_API_KEY", "fake-xai-key")

    seen_hosts: list[str] = []
    real_client = httpx.AsyncClient

    def _handler(req: httpx.Request) -> httpx.Response:
        seen_hosts.append(req.url.host)
        if "x.ai" in req.url.host:
            body = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({
                                "verdict": "AGREE_WITH_RESERVATIONS",
                                "notes": "Verified EV-0001 shows TypeError on line 42; keep High severity.",
                                "unsupported_claims": [],
                            })
                        }
                    }
                ]
            }
            return httpx.Response(200, json=body)
        body = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps({
                                    "executive_summary": "Verified 1 dynamic console defect citing TypeError on line 42.",
                                    "quick_wins": ["Guard null before .id access"],
                                })
                            }
                        ]
                    }
                }
            ]
        }
        return httpx.Response(200, json=body)

    monkeypatch.setattr(
        disp_mod.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(_handler), **kwargs),
    )

    # 1. MultiModelDispatcher routes xai/grok to api.x.ai (not api.groq.com)
    d = MultiModelDispatcher(timeout_seconds=5.0)
    _, _ = await d._route_model("grok-3-mini", "sys", "prompt", timeout_seconds=5.0)
    assert "api.x.ai" in seen_hosts

    # 2. Cross-vendor writer (Gemini) vs critic (Grok) with citation validation
    run_dir = tmp_path / "cv_run"
    vault = EvidenceVault(run_dir)
    ev = vault.record_artifact(b"TypeError on line 42", ext=".txt", tool_name="cdp.console")
    sb = AgentScoreboard(run_dir, global_scores_path=tmp_path / "scores.json")
    ledger = ClaimLedger(run_dir, vault=vault, scoreboard=sb)
    c = Claim(
        id="C-001",
        statement="TypeError on line 42",
        evidence_refs=(ev.evidence_id,),
        quoted_spans=("TypeError on line 42",),
        confidence=0.9,
        found_by="console-analyst",
        evidence_type="DYNAMIC",
        proposed_severity="High",
    )
    ledger.submit_claim(c)
    ledger.record_verification("C-001", verifier="verifier", verdict="CONFIRMED")

    analysis = await analyze_findings_cross_vendor(
        ledger=ledger,
        vault=vault,
        writer_vendor="gemini",
        critic_vendor="grok",
    )
    assert analysis["writer_vendor"] != analysis["critic_vendor"]
    assert "executive_summary" in analysis["writer_output"]
    assert analysis["critic_output"]["verdict"] == "AGREE_WITH_RESERVATIONS"


def test_site_audit_coordinator_honesty_auditor_rejects_ungrounded_adjectives(tmp_path: Path):
    coord = SiteAuditCoordinator(output_root=tmp_path / "reports")
    run_dir = tmp_path / "reports" / "run_h"
    vault = EvidenceVault(run_dir)
    ev = vault.record_artifact(b"HTTP 404 /missing.css", ext=".txt", tool_name="cdp.network")
    sb = AgentScoreboard(run_dir, global_scores_path=tmp_path / "scores.json")
    ledger = ClaimLedger(run_dir, vault=vault, scoreboard=sb)
    c = Claim(
        id="C-099",
        statement="All users always suffer catastrophic outage across every browser",
        evidence_refs=(ev.evidence_id,),
        quoted_spans=("HTTP 404 /missing.css",),
        confidence=0.95,
        found_by="network-analyst",
        evidence_type="STATIC",
        proposed_severity="Critical",
    )
    ledger.submit_claim(c)
    flags = coord.run_honesty_audit(ledger, vault)
    assert any(fl["claim_id"] == "C-099" for fl in flags)
