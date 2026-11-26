"""Regression test for ECC-007: package __init__.py hygiene and reporting public exports."""

from pathlib import Path

from bugarena import reporting


def test_ecc_007_personas_init_exists_and_reporting_exports_complete():
    repo_root = Path(__file__).resolve().parents[2]
    assert (repo_root / "src" / "bugarena" / "tournament" / "personas" / "__init__.py").is_file()
    for name in (
        "format_bug_diagnostic_markdown",
        "format_markdown_report",
        "save_markdown_report",
    ):
        assert name in reporting.__all__
        assert callable(getattr(reporting, name))
