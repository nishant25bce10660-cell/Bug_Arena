import pytest

from bugarena.models.agent import CandidatePatch, PersonaType
from bugarena.models.bug import BugSpec, SuspectLocation
from bugarena.models.repro import ReproTestSpec
from bugarena.models.tournament import PatchEvaluation, TournamentRecord
from bugarena.reporting.markdown_formatter import (
    format_markdown_report,
    save_markdown_report,
)
from bugarena.server import generate_bug_report, mcp


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
    assert "BugArena" in report_md and "Report" in report_md
    assert "tourn_test_123" in report_md
    assert "cand_surg_1" in report_md
    assert "99.2" in report_md
    assert "git apply" in report_md
    assert "if b == 0: raise ValueError()" in report_md


def test_markdown_report_includes_bug_diagnostics_and_saves_file(tmp_path):
    suspect = SuspectLocation(
        file_path="src/calc.py",
        function_name="divide",
        line_range=(10, 15),
        confidence=0.95,
        bug_type="ZeroDivisionError",
        reasoning="Divisor b is not guarded against zero.",
        code_snippet="def divide(a, b):\n    return a / b",
    )
    bug_spec = BugSpec(
        bug_id="bug_diag_01",
        repo_path=str(tmp_path),
        error_log="ZeroDivisionError: division by zero in divide",
        hint="Add zero check for divisor",
        suspects=[suspect],
    )
    repro = ReproTestSpec(
        test_file_path="tests/test_repro.py",
        test_code="def test_zero(): assert divide(1, 0) == 0",
        expected_exception="ZeroDivisionError",
        red_baseline_verified=True,
    )
    tournament = TournamentRecord(
        tournament_id="tourn_diag_01",
        repo_path=str(tmp_path),
        bug_spec=bug_spec,
        repro_spec=repro,
        bug_description="Calling divide(10, 0) causes ZeroDivisionError crash.",
    )

    report_md = format_markdown_report(tournament)
    assert "## 1. Bug Description & Diagnostics" in report_md
    assert "bug_diag_01" in report_md
    assert "Calling divide(10, 0) causes ZeroDivisionError crash." in report_md
    assert "ZeroDivisionError" in report_md
    assert "Divisor b is not guarded against zero." in report_md
    assert "def divide(a, b):" in report_md
    assert "tests/test_repro.py" in report_md
    assert "def test_zero():" in report_md

    out_file = tmp_path / "reports" / "custom_bug_report.md"
    saved = save_markdown_report(report_md, out_file)
    assert saved.is_file()
    assert saved.read_text(encoding="utf-8") == report_md


def test_generate_bug_report_tool(tmp_path):
    code_file = tmp_path / "math.py"
    code_file.write_text("def div(a, b):\n    return a / b\n")

    error_log = f'Traceback (most recent call last):\n  File "{code_file}", line 2, in div\n    return a / b\nZeroDivisionError: division by zero\n'
    out_md = tmp_path / "reports" / "math_bug.md"

    res = generate_bug_report(
        repo_path=str(tmp_path),
        error_log=error_log,
        bug_description="div crashes on 0 denominator",
        output_file=str(out_md),
    )
    assert "bug_id" in res
    assert res["report_file_path"] == str(out_md.resolve())
    assert out_md.is_file()
    content = out_md.read_text(encoding="utf-8")
    assert "div crashes on 0 denominator" in content
    assert "ZeroDivisionError" in content


@pytest.mark.asyncio
async def test_mcp_server_tools_registered():
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "bug_detect" in tool_names
    assert "bug_reproduce" in tool_names
    assert "agent_fix_tournament" in tool_names
    assert "evaluate_patches" in tool_names
    assert "generate_fix_report" in tool_names
    assert "generate_bug_report" in tool_names
    assert "bugarena_autonomous_repair" in tool_names
