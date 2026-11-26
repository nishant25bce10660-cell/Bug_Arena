"""Regression test for ECC-032: reject duplicate candidate_id, null explanation, non-str diff."""

from bugarena.server import agent_fix_tournament


def test_ecc_032_duplicate_ids_null_explanation_and_structured_errors(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    diff = "--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"

    # 1. explanation: null & persona: null should normalize gracefully without crashing
    res_ok = agent_fix_tournament(
        repo_path=str(repo),
        repro_test_file="tests/t.py",
        candidate_patches_raw=[
            {"candidate_id": "c1", "persona": None, "explanation": None, "diff": diff}
        ],
    )
    assert "error" not in res_ok
    assert res_ok["candidate_count"] == 1

    # 2. Duplicate candidate_id MUST return structured error dict
    res_dup = agent_fix_tournament(
        repo_path=str(repo),
        repro_test_file="tests/t.py",
        candidate_patches_raw=[
            {"candidate_id": "dup", "explanation": "a", "diff": diff},
            {"candidate_id": "dup", "explanation": "b", "diff": diff},
        ],
    )
    assert "error" in res_dup and "duplicate" in res_dup["error"].lower()

    # 3. Non-string diff returns structured error dict instead of raising AttributeError
    res_bad = agent_fix_tournament(
        repo_path=str(repo),
        repro_test_file="tests/t.py",
        candidate_patches_raw=[{"candidate_id": "c2", "diff": None}],
    )
    assert "error" in res_bad
