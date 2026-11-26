"""Regression test for ECC-031 (BA-017): repo-scoped _REPRO_REGISTRY lookup."""

from bugarena.server import bug_reproduce, generate_bug_report


def test_ecc_031_repro_registry_scoped_by_resolved_repo(tmp_path):
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / "a.py").write_text("def f():\n    return 1 / 0\n")
    (repo_b / "b.py").write_text("def g():\n    return 2\n")

    bug_reproduce(
        repo_path=str(repo_a),
        suspect_file="a.py",
        bug_description="div zero in A",
        function_name="f",
        call_expr="f()",
        expected_behavior="f() == 0",
    )

    rep_a = generate_bug_report(
        repo_path=str(repo_a),
        error_log='  File "a.py", line 2, in f\nZeroDivisionError: division by zero',
    )
    assert "## 2. Failing Reproduction Test (Red Baseline)" in rep_a["report_markdown"]

    # Calling generate_bug_report on repo_b or "." must NOT pull repo_a's repro
    rep_b = generate_bug_report(
        repo_path=str(repo_b),
        error_log='  File "b.py", line 2, in g\nRuntimeError: err',
    )
    assert "div zero in A" not in rep_b["report_markdown"]
