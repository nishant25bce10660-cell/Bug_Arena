"""Unit and integration tests for the ECC-style subagent & multi-round audit engine."""

import json

import pytest

from bugarena.agents import AgentRunner, AgentSpec, build_agent_registry
from bugarena.audit import (
    EvidenceType,
    Finding,
    FindingDraft,
    FindingLedger,
    FindingLocation,
    FindingRepro,
    FindingState,
    LoopOperator,
    SeverityLevel,
    apply_severity_rubric,
    merge_or_insert_draft,
    split_bundled_finding,
    verify_finding,
)
from bugarena.server import (
    audit_report,
    audit_round,
    audit_start,
    audit_status,
    finding_verify,
    fix_loop_start,
    mcp,
)


def _sample_draft(**overrides) -> FindingDraft:
    base = {
        "title": "Sample Defect",
        "location": FindingLocation(file="src/mod.py", line_start=10, line_end=15, symbol="fn"),
        "category": "logic",
        "what_it_is": "Bad check",
        "what_it_does": "Wrong return",
        "root_cause": "Condition inverted in fn.",
        "repro": FindingRepro(
            inputs="fn(0)",
            expected="1",
            actual="0",
            probe_script="import sys; print('REPRODUCED: zero'); sys.exit(1)",
        ),
        "suggested_fix": "Invert condition",
        "risks": "None",
        "regression_test_idea": "Assert fn(0) == 1",
        "proposed_severity": SeverityLevel.HIGH,
        "found_by": "code-reviewer",
    }
    base.update(overrides)
    return FindingDraft(**base)


def test_agent_registry_has_all_required_roles_and_prompts():
    reg = build_agent_registry()
    for role in (
        "loop-operator",
        "python-reviewer",
        "code-reviewer",
        "security-reviewer",
        "silent-failure-hunter",
        "performance-optimizer",
        "type-design-analyzer",
        "pr-test-analyzer",
        "comment-analyzer",
        "architect",
        "code-architect",
        "agent-evaluator",
        "fix-author-surgical",
        "fix-reviewer",
    ):
        assert role in reg
        spec = reg[role]
        assert "file:line" in spec.role_prompt
        assert "root_cause" in spec.role_prompt.lower() or "root cause" in spec.role_prompt.lower()


def test_finding_invariants_enforced():
    draft = _sample_draft()
    # CONFIRMED cannot be STATIC or verified by same agent
    with pytest.raises(ValueError, match="evidence_type=DYNAMIC"):
        Finding(
            id="F-001",
            state=FindingState.CONFIRMED,
            evidence_type=EvidenceType.STATIC,
            verified_by="code-architect",
            verification_output="out",
            **draft.model_dump(),
        )
    with pytest.raises(ValueError, match="different from found_by"):
        Finding(
            id="F-001",
            state=FindingState.CONFIRMED,
            evidence_type=EvidenceType.DYNAMIC,
            verified_by="code-reviewer",
            verification_output="out",
            **draft.model_dump(),
        )
    # DISMISSED requires verification_output
    with pytest.raises(ValueError, match="verification_output"):
        Finding(
            id="F-001",
            state=FindingState.DISMISSED,
            evidence_type=EvidenceType.DYNAMIC,
            verified_by="code-architect",
            verification_output="",
            **draft.model_dump(),
        )


def test_severity_rubric_rules():
    sev, _ = apply_severity_rubric(
        SeverityLevel.CRITICAL,
        category="logic",
        evidence_type=EvidenceType.STATIC,
        what_it_is="Static only",
    )
    assert sev == SeverityLevel.HIGH

    dep_sev, _ = apply_severity_rubric(
        SeverityLevel.CRITICAL,
        category="build/config",
        evidence_type=EvidenceType.DYNAMIC,
        what_it_is="Missing runtime dependency httpx",
    )
    assert dep_sev != SeverityLevel.CRITICAL


def test_dedupe_and_parent_child_split(tmp_path):
    ledger = FindingLedger(tmp_path / "ledger.json")
    f1, is_new1 = merge_or_insert_draft(ledger, _sample_draft(), round_num=1)
    assert is_new1 is True
    f2, is_new2 = merge_or_insert_draft(ledger, _sample_draft(), round_num=2)
    assert is_new2 is False
    assert f2.id == f1.id
    assert f2.rounds_seen == (1, 2)

    children = split_bundled_finding(
        ledger,
        f1.id,
        [_sample_draft(title="Sub A"), _sample_draft(title="Sub B")],
        round_num=2,
    )
    assert [c.id for c in children] == ["F-001.a", "F-001.b"]
    ledger.save()
    assert (tmp_path / "ledger.json").is_file()


def test_independent_verification_confirm_and_dismiss(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("x = 1\n")
    ledger = FindingLedger(tmp_path / "ledger.json")
    f_conf = ledger.add_draft(_sample_draft(), round_num=1)
    f_dism = ledger.add_draft(
        _sample_draft(
            title="False Alarm",
            repro=FindingRepro(
                inputs="x",
                expected="ok",
                actual="ok",
                probe_script="print('DISPROVED: works cleanly')",
            ),
        ),
        round_num=1,
    )
    res1 = verify_finding(repo, ledger, f_conf.id)
    assert res1.state == FindingState.CONFIRMED
    assert res1.evidence_type == EvidenceType.DYNAMIC
    assert res1.verified_by != res1.found_by

    res2 = verify_finding(repo, ledger, f_dism.id)
    assert res2.state == FindingState.DISMISSED
    assert "DISPROVED" in res2.verification_output


@pytest.mark.asyncio
async def test_agent_runner_quarantines_invalid_json(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    op = LoopOperator(state_root=tmp_path / ".bugarena")
    start_res = op.start(repo, agents=["code-reviewer"])
    rid = start_res["run_id"]

    async def bad_llm(_spec: AgentSpec, _prompt: str) -> str:
        return "not json"

    r1 = await op.run_round(rid, auto_generate=True, llm_caller=bad_llm)
    assert r1["quarantined_agents"] == []
    r2 = await op.run_round(rid, auto_generate=True, llm_caller=bad_llm)
    assert "code-reviewer" in r2["quarantined_agents"]


@pytest.mark.asyncio
async def test_new_audit_mcp_tools_registered_and_end_to_end(tmp_path):
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    for tname in (
        "audit_start",
        "audit_round",
        "audit_status",
        "finding_verify",
        "audit_report",
        "fix_loop_start",
    ):
        assert tname in names

    repo = tmp_path / "sample_repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("def ok(): return 1\n")

    start = await audit_start(str(repo), agents=["comment-analyzer", "architect"])
    rid = start["run_id"]
    rnd = await audit_round(rid, auto_generate=False)
    assert rnd["round"] == 1
    st = await audit_status(rid)
    assert st["current_round"] == 1
    rep_md = await audit_report(rid, format="markdown", output_file="audit_out.md")
    assert (repo / "audit_out.md").is_file()
    assert "# BugArena Audit Report" in rep_md["markdown"]
    rep_json = await audit_report(rid, format="json", output_file="audit_out.json")
    assert json.loads((repo / "audit_out.json").read_text(encoding="utf-8"))["rounds_run"] == 1
    fix_res = await fix_loop_start(rid, auto_generate=False)
    assert fix_res["run_id"] == rid
    if st["counts"]["TOTAL"] > 0:
        first_id = rep_json["report_json"]["findings"][0]["id"]
        fv = await finding_verify(rid, first_id)
        assert fv["finding"]["id"] == first_id


@pytest.mark.asyncio
async def test_agent_runner_schema_validation_success(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    runner = AgentRunner()
    spec = build_agent_registry()["code-reviewer"]
    payload = json.dumps([_sample_draft().model_dump()])

    async def ok_llm(_s: AgentSpec, _p: str) -> str:
        return f"```json\n{payload}\n```"

    res = await runner.run_agent(spec, repo, auto_generate=True, llm_caller=ok_llm)
    assert len(res.findings) == 1
    assert res.error is None
