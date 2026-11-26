"""Tests proving Phase 0 fixes for Red Flags #2, #4, #6, #7, #8."""

import asyncio
import tomllib
from pathlib import Path

from bugarena.audit.coverage import CoverageMatrix, ModuleCoverage, classify_area
from bugarena.server import mcp

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_coverage_requires_real_probe_or_test_no_docs_packaging_bypass():
    matrix = CoverageMatrix(
        repo_path=".",
        areas=(
            ModuleCoverage(area="docs", files=("README.md",), static_read=True, dynamic_probe=False, test_exists=False),
            ModuleCoverage(area="packaging", files=("pyproject.toml",), static_read=True, dynamic_probe=False, test_exists=False),
        ),
    )
    assert matrix.coverage_pct == 0.0
    assert classify_area("docs/architecture.md") == "docs"
    assert classify_area("CONTRIBUTING.md") == "docs"


def test_all_mcp_tools_have_non_empty_first_line_descriptions():
    async def _get():
        return await mcp.list_tools()

    tools = asyncio.run(_get())
    assert len(tools) >= 13
    for tool in tools:
        desc = (tool.description or "").strip()
        first_line = desc.splitlines()[0].strip() if desc else ""
        assert len(first_line) >= 15, f"Tool {tool.name} has empty/short description: {tool.description!r}"


def test_pyproject_declares_slow_and_browser_markers():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    markers = data["tool"]["pytest"]["ini_options"].get("markers", [])
    joined = "\n".join(markers)
    assert "slow:" in joined
    assert "browser:" in joined


def test_docs_and_contributing_guide_files_exist_and_non_empty():
    expected_docs = (
        "CONTRIBUTING.md",
        "docs/README.md",
        "docs/STATE_VERIFICATION.md",
        "docs/TOOLING_AVAILABLE.md",
        "docs/architecture.md",
        "docs/configuration.md",
        "docs/evidence.md",
        "docs/repository-review.md",
        "docs/tools.md",
    )
    for rel in expected_docs:
        p = REPO_ROOT / rel
        assert p.is_file(), f"Missing documented guide: {rel}"
        assert p.read_text(encoding="utf-8").strip().startswith("#")
