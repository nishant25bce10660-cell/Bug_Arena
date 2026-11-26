"""Regression test for ECC-012: bugarena_autonomous_repair returns NO_SUSPECTS_FOUND on empty suspects."""

from bugarena.server import bugarena_autonomous_repair


def test_ecc_012_autonomous_repair_returns_no_suspects_found(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("x = 1\n")

    res = bugarena_autonomous_repair(
        repo_path=str(repo),
        error_log="RuntimeError: generic error with no file frame",
        bug_description="generic crash",
        candidate_patches_raw=[],
    )
    assert res["status"] == "NO_SUSPECTS_FOUND"
    assert "error" in res
