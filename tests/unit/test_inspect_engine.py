"""Tests for Phase 4 Inspect Engine: 14 CDP DevTools collectors, coverage matrix, fixture recall."""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from bugarena.browser import AccessPolicy, BrowserCursor, discover_browsers
from bugarena.inspect import (
    ALL_PANELS,
    InspectCoverageMatrix,
    collect_cross_browser_diff,
    run_full_site_inspection,
)
from bugarena.truth import EvidenceVault, TranscriptLogger

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "site_bugs"
TRUTH_PATH = _FIXTURE_DIR / "fixture_truth.json"


def _serve_fixture_site():
    spec = importlib.util.spec_from_file_location("site_bugs_server", _FIXTURE_DIR / "server.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.serve_fixture_site()


def test_all_14_inspect_panels_defined_and_passive_matrix_marks_interaction_blocked(tmp_path: Path):
    assert len(ALL_PANELS) == 14
    matrix = InspectCoverageMatrix(run_dir=tmp_path)
    matrix.mark_panel("Elements", covered=True, evidence_ids=("EV-0001",))
    matrix.mark_panel("Interaction flows", covered=False, reason="Blocked in passive mode")
    out = matrix.write_markdown()
    text = out.read_text(encoding="utf-8")
    assert "## DevTools Inspect Coverage Matrix" in text
    assert "| `Elements` | COVERED |" in text
    assert "| `Interaction flows` | NOT COVERED | Blocked in passive mode |" in text


@pytest.mark.browser
def test_live_fixture_site_full_inspect_recall_zero_decoys(tmp_path: Path):
    browsers = [b for b in discover_browsers() if b.found]
    if not browsers:
        pytest.skip("No Chromium browser installed on host.")
    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))

    async def _audit(base_url: str):
        run_dir = tmp_path / "site_run"
        vault = EvidenceVault(run_dir)
        transcript = TranscriptLogger(run_dir)
        policy = AccessPolicy.from_answers({
            "site_url": base_url,
            "authorization": "own",
            "access_level": "full_access",
        })
        cursor = await BrowserCursor.launch(
            browser_name=browsers[0].name,
            executable=browsers[0].executable,
            headless=True,
        )
        try:
            res = await run_full_site_inspection(
                cursor=cursor,
                url=base_url,
                policy=policy,
                vault=vault,
                transcript=transcript,
                panels="all",
            )
            return res, vault.verify_chain()
        finally:
            await cursor.close()

    with _serve_fixture_site() as base_url:
        result, chain = asyncio.run(_audit(base_url))

    assert chain["valid"] is True
    assert (tmp_path / "site_run" / "coverage_matrix.md").is_file()

    findings = result["findings"]
    blob = "\n".join(json.dumps(f) for f in findings).lower()

    matched = [b["id"] for b in truth["planted_bugs"] if b["match"].lower() in blob]
    recall = len(matched) / len(truth["planted_bugs"])
    assert recall >= 0.90, (
        f"Recall {recall:.1%} < 90%; matched={matched}, "
        f"missing={ {b['id'] for b in truth['planted_bugs']} - set(matched) }"
    )

    # Zero decoys reported as bugs
    for decoy in truth["decoys"]:
        assert decoy["id"].lower() not in blob, f"Decoy {decoy['id']} falsely flagged as bug!"


def test_cross_browser_diff_flags_browser_specific_bugs(tmp_path: Path):
    vault = EvidenceVault(tmp_path)
    per_browser = {
        "chrome": {"findings": [{"title": "Shared bug"}, {"title": "Chrome-only layout shift"}]},
        "brave": {"findings": [{"title": "Shared bug"}, {"title": "Brave shield blocks script"}]},
    }
    diff_res = collect_cross_browser_diff(per_browser, vault, "https://example.com")
    assert len(diff_res["diffs"]) == 2
    assert len(diff_res["findings"]) == 2
    assert vault.verify_chain()["valid"] is True
