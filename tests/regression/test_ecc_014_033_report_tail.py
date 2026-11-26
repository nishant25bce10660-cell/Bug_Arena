"""Regression test for ECC-014 and ECC-033 (BA-016): FixReport, record.report_file_path, tail truncation, candidate warning."""

from pathlib import Path

import bugarena.server as srv


def test_ecc_014_033_report_path_persisted_tail_kept_and_truncation_warned(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "m.py").write_text("def f():\n    return 1\n")

    # 1. Oversized error_log (>65536 chars) with crash frame at the TAIL
    prefix = "INFO log noise\n" * 5000
    tail = 'Traceback (most recent call last):\n  File "src/m.py", line 2, in f\n    return 1\nZeroDivisionError: boom\n'
    big_log = prefix + tail
    det = srv.bug_detect(str(repo), big_log)
    assert len(det["suspects"]) == 1
    assert det["suspects"][0]["file_path"] == "src/m.py"

    # 2. Check TournamentRecord.report_file_path updated after generate_fix_report
    diff = "--- a/src/m.py\n+++ b/src/m.py\n@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return 2\n"
    t = srv.agent_fix_tournament(
        str(repo),
        "tests/repro/t.py",
        [{"candidate_id": "c1", "persona": "surgical_minimalist", "explanation": "ok", "diff": diff}],
    )
    rep = srv.generate_fix_report(t["tournament_id"], format="markdown")
    saved = rep["report_file_path"]
    assert Path(saved).is_file()
    stored_rec = srv._TOURNAMENT_REGISTRY[t["tournament_id"]]
    assert stored_rec.report_file_path == saved

    # 3. Invalid format raises ValueError explicitly (never silently treated as markdown)
    import pytest

    with pytest.raises(ValueError, match="Unsupported format"):
        srv.generate_fix_report(t["tournament_id"], format="xml")

    # 4. Warning surfaced when >20 candidates passed to bugarena_autonomous_repair
    cands = [
        {"candidate_id": f"c{i}", "persona": "surgical_minimalist", "explanation": "x", "diff": diff}
        for i in range(25)
    ]
    res = srv.bugarena_autonomous_repair(
        repo_path=str(repo),
        error_log=tail,
        bug_description="want 2",
        call_expr="f()",
        expected_behavior="f() == 2",
        candidate_patches_raw=cands,
    )
    assert "warning" in res and "20" in res["warning"]
