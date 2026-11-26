"""Regression test for ECC-009 and ECC-042 (BA-004, BA-005): strict hunk state machine."""

import pytest

from bugarena.models.agent import PersonaType
from bugarena.sandbox.manager import EphemeralSandboxManager
from bugarena.tournament.patch_parser import parse_and_validate_patch


def test_ecc_009_u0_insert_sql_comment_delete_and_context_mismatch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "nums.txt").write_text("1\n2\n3\n4\n5\n", encoding="utf-8")
    (repo / "q.sql").write_text("-- header\nSELECT 1;\n", encoding="utf-8")
    (repo / "obsolete.py").write_text("old = 1\n", encoding="utf-8")
    mgr = EphemeralSandboxManager(repo)

    # 1. -U0 pure insertion
    diff_u0 = "--- a/nums.txt\n+++ b/nums.txt\n@@ -4,0 +5,1 @@\n+INSERTED\n"
    with mgr.create_sandbox() as sb:
        mgr.apply_patch(sb, diff_u0)
        assert (sb / "nums.txt").read_text(encoding="utf-8").splitlines() == [
            "1",
            "2",
            "3",
            "4",
            "INSERTED",
            "5",
        ]

    # 2. Deleted '-- comment' inside hunk + timestamped headers + +++ /dev/null deletion
    diff_sql_del = (
        "--- a/q.sql\t2026-01-01 00:00:00\r\n"
        "+++ b/q.sql\t2026-01-01 00:00:00\r\n"
        "@@ -1,2 +1,2 @@\r\n"
        "--- header\r\n"
        "+-- new header\r\n"
        " SELECT 1;\r\n"
        "--- a/obsolete.py\r\n"
        "+++ /dev/null\r\n"
        "@@ -1,1 +0,0 @@\r\n"
        "-old = 1\r\n"
    )
    with mgr.create_sandbox() as sb:
        mgr.apply_patch(sb, diff_sql_del)
        assert (sb / "q.sql").read_text(encoding="utf-8").splitlines() == [
            "-- new header",
            "SELECT 1;",
        ]
        assert not (sb / "obsolete.py").exists()

    # 3. Context mismatch MUST raise ValueError, never corrupt silently
    bad_ctx = "--- a/nums.txt\n+++ b/nums.txt\n@@ -99,1 +99,1 @@\n-WRONG\n+CORRUPT\n"
    with mgr.create_sandbox() as sb, pytest.raises(ValueError):
        mgr.apply_patch(sb, bad_ctx)


def test_ecc_042_trailing_blank_context_and_single_b_strip(tmp_path):
    repo = tmp_path / "repo"
    (repo / "b").mkdir(parents=True)
    (repo / "b" / "mod.py").write_text("a = 1\n\nb = 2\n", encoding="utf-8")

    # Note trailing ' ' blank context line after +a = 10; must NOT be deleted by .strip()
    raw_diff = "--- a/b/mod.py\n+++ b/b/mod.py\n@@ -1,2 +1,2 @@\n-a = 1\n+a = 10\n \n"
    parsed = parse_and_validate_patch(raw_diff, PersonaType.SURGICAL_MINIMALIST, "fix")
    assert parsed.diff.endswith("\n ")

    mgr = EphemeralSandboxManager(repo)
    with mgr.create_sandbox() as sb:
        mgr.apply_patch(sb, parsed.diff)
        assert (sb / "b" / "mod.py").read_text(encoding="utf-8") == "a = 10\n\nb = 2\n"
