"""Regression test for ECC-003: validate output_file confinement in report writers."""

import pytest

from bugarena.reporting.markdown_formatter import save_markdown_report
from bugarena.sandbox.security import SecurityViolationError
from bugarena.server import agent_fix_tournament, generate_bug_report, generate_fix_report


def test_ecc_003_save_markdown_report_rejects_escape(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "escaped.md"

    with pytest.raises(SecurityViolationError, match="Path traversal detected"):
        save_markdown_report("# Report", outside, base_dir=repo)
    assert not outside.exists()


def test_ecc_003_generate_bug_report_rejects_outside_output_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("x = 1 / 0\n")
    outside = tmp_path / "escaped_bug.md"

    with pytest.raises(SecurityViolationError, match="Path traversal detected"):
        generate_bug_report(
            repo_path=str(repo),
            error_log='File "app.py", line 1\nZeroDivisionError: division by zero',
            output_file=str(outside),
        )
    assert not outside.exists()


def test_ecc_003_generate_fix_report_rejects_outside_output_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    t = agent_fix_tournament(
        repo_path=str(repo),
        repro_test_file="tests/test_r.py",
        candidate_patches_raw=[
            {
                "candidate_id": "c1",
                "persona": "surgical_minimalist",
                "explanation": "fix",
                "diff": "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x=1\n+x=2\n",
            }
        ],
    )
    outside = tmp_path / "escaped_fix.md"
    with pytest.raises(SecurityViolationError, match="Path traversal detected"):
        generate_fix_report(t["tournament_id"], format="markdown", output_file=str(outside))
    assert not outside.exists()
