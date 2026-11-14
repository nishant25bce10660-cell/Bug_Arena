import pytest

from bugarena.models.agent import CandidatePatch, PersonaType
from bugarena.models.tournament import PatchEvaluation, TournamentRecord
from bugarena.reporting.markdown_formatter import format_markdown_report
from bugarena.server import mcp


def test_markdown_formatter_generates_report():
    cand = CandidatePatch(
        candidate_id="cand_surg_1",
        persona=PersonaType.SURGICAL_MINIMALIST,
        diff="--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,3 @@\n+if b == 0: raise ValueError()\n",
        explanation="Added zero check before division",
        lines_added=1,
        lines_deleted=0,
    )
    eval_rec = PatchEvaluation(
        candidate_id="cand_surg_1",
        repro_passed=True,
        regressions_count=0,
        total_regressions_checked=50,
        diff_churn=1,
        cyclomatic_delta=1,
        mutation_kill_ratio=1.0,
        score=99.2,
        disqualified=False,
    )
    tournament = TournamentRecord(
        tournament_id="tourn_test_123",
        repo_path="/workspace/repo",
        candidates=[cand],
        evaluations=[eval_rec],
        champion_candidate_id="cand_surg_1",
    )

    report_md = format_markdown_report(tournament)
    assert "# BugArena Repair Tournament Report" in report_md
    assert "tourn_test_123" in report_md
    assert "cand_surg_1" in report_md
    assert "99.2" in report_md
    assert "git apply" in report_md
    assert "if b == 0: raise ValueError()" in report_md


@pytest.mark.asyncio
async def test_mcp_server_tools_registered():
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "bug_detect" in tool_names
    assert "bug_reproduce" in tool_names
    assert "agent_fix_tournament" in tool_names
    assert "evaluate_patches" in tool_names
    assert "generate_fix_report" in tool_names
    assert "bugarena_autonomous_repair" in tool_names
