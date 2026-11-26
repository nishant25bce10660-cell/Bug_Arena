"""Regression test for ECC-008 (BA-006, BA-007): line-by-line diff parser, normpath, protected checks."""

import pytest

from bugarena.models.agent import PersonaType
from bugarena.tournament.patch_parser import PatchValidationError, parse_and_validate_patch


def test_ecc_008_blocks_bypasses_and_allows_non_matching_substrings():
    prot = ["tests/repro/secret_test.py"]

    # 1. CRLF / mixed line endings modifying protected path
    crlf_diff = "--- a/tests/repro/secret_test.py\r\n+++ b/tests/repro/secret_test.py\r\n@@ -1 +1 @@\r\n-a\r\n+b\r\n"
    with pytest.raises(PatchValidationError, match="protected"):
        parse_and_validate_patch(crlf_diff, PersonaType.SURGICAL_MINIMALIST, "cheat", protected_paths=prot)

    # 2. Protected /dev/null deletion
    del_diff = "--- a/tests/repro/secret_test.py\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-assert False\n"
    with pytest.raises(PatchValidationError, match="protected"):
        parse_and_validate_patch(del_diff, PersonaType.SURGICAL_MINIMALIST, "del", protected_paths=prot)

    # 3. Parent '..' or absolute target path rejected
    trav_diff = "--- a/../etc/passwd\n+++ b/../etc/passwd\n@@ -1 +1 @@\n-x\n+y\n"
    with pytest.raises(PatchValidationError):
        parse_and_validate_patch(trav_diff, PersonaType.SURGICAL_MINIMALIST, "trav")

    abs_diff = "--- a//etc/passwd\n+++ b//etc/passwd\n@@ -1 +1 @@\n-x\n+y\n"
    with pytest.raises(PatchValidationError):
        parse_and_validate_patch(abs_diff, PersonaType.SURGICAL_MINIMALIST, "abs")

    # 4. Protected 'tests/calc.py' must NOT block editing 'calc.py' or 'src/calc.py'
    benign = "--- a/calc.py\n+++ b/calc.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"
    ok = parse_and_validate_patch(benign, PersonaType.SURGICAL_MINIMALIST, "ok", protected_paths=["tests/calc.py"])
    assert ok.lines_added == 1


def test_ecc_008_hunk_required_and_sql_comment_churn_counted():
    # Header-only diff without @@ hunk MUST be rejected
    no_hunk = "--- a/a.py\n+++ b/a.py\n+fake_add\n"
    with pytest.raises(PatchValidationError, match="hunk"):
        parse_and_validate_patch(no_hunk, PersonaType.SURGICAL_MINIMALIST, "empty hunk")

    # Deleted '-- select 1' inside hunk MUST count as 1 line deleted
    sql_diff = "--- a/q.sql\n+++ b/q.sql\n@@ -1,1 +1,1 @@\n--- old comment\n+-- new comment\n"
    res = parse_and_validate_patch(sql_diff, PersonaType.SURGICAL_MINIMALIST, "sql")
    assert res.lines_deleted == 1
    assert res.lines_added == 1
