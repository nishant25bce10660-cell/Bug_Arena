"""Regression test for ECC-030 (BA-018): bug_reproduce combines stdout + stderr in failure_output."""

from bugarena.server import bug_reproduce


def test_ecc_030_bug_reproduce_includes_pytest_stdout(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("def f():\n    return 1\n")

    res = bug_reproduce(
        repo_path=str(repo),
        suspect_file="m.py",
        bug_description="want 2",
        function_name="f",
        call_expr="f()",
        expected_behavior="f() == 2",
    )
    assert res["status"] == "REPRODUCED_RED"
    out = res["failure_output"]
    assert "assert 1 == 2" in out or "AssertionError" in out or "FAILED" in out
