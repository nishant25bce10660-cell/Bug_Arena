"""Tests for scripts/update_project_report.py and report tracking coverage rules."""

import importlib.util
from pathlib import Path

import pytest

from bugarena.audit.coverage import classify_area

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "update_project_report.py"


def _load_report_module():
    spec = importlib.util.spec_from_file_location("update_project_report", SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_project_report_classification_areas():
    assert classify_area("PROJECT_REPORT.md") == "docs"
    assert classify_area("AGENTS.md") == "docs"
    assert classify_area(".githooks/pre-commit") == "scripts"


@pytest.mark.slow
def test_generate_project_report_runs_audit_and_writes_markdown(tmp_path: Path):
    assert SCRIPT_PATH.is_file(), "Missing scripts/update_project_report.py"
    mod = _load_report_module()

    out_file = tmp_path / "PROJECT_REPORT.md"
    result = mod.generate_project_report(
        repo_path=REPO_ROOT,
        output_path=out_file,
        skip_pytest=True,
    )

    assert out_file.is_file()
    content = out_file.read_text(encoding="utf-8")
    assert "# BugArena MCP — Project & Audit Report" in content
    assert "## Audit Verdict" in content
    assert "## Verification Status" in content
    assert "## MCP Tools" in content
    assert "## Coverage Matrix" in content
    assert "## Recent Changes" in content
    assert "audit_start" in content
    assert "bug_detect" in content
    assert result["coverage_pct"] == 100.0
    assert result["open_confirmed"] == 0
