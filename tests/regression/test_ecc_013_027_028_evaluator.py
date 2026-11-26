"""Regression test for ECC-013 (BA-008), ECC-027, ECC-028 (BA-009): evaluator, scorer, ast_metrics."""

import pytest

from bugarena.evaluation.ast_metrics import _count_ast_branches, calculate_cyclomatic_delta
from bugarena.evaluation.scorer import compute_patch_score
from bugarena.evaluation.test_runner import PatchEvaluator
from bugarena.models.agent import CandidatePatch, PersonaType
from bugarena.models.repro import ReproTestSpec


def test_ecc_028_ast_metrics_raises_value_error_on_syntax_error():
    with pytest.raises(ValueError, match="SyntaxError"):
        _count_ast_branches("def broken( :")
    with pytest.raises(ValueError, match="SyntaxError"):
        calculate_cyclomatic_delta("def ok():\n    return 1\n", "def broken( :")


def test_ecc_013_scorer_no_free_mutation_and_empty_tests_not_free_30():
    ev_none = compute_patch_score("p1", True, 0, 10, 1, 0, mutation_kill_ratio=None)
    ev_meas = compute_patch_score("p2", True, 0, 10, 1, 0, mutation_kill_ratio=0.9)
    assert ev_none.score < ev_meas.score

    ev_empty = compute_patch_score("p3", True, 0, 0, 1, 0, mutation_kill_ratio=None)
    assert ev_empty.score < 70.0  # No free 30/30 when total_regressions == 0


def test_ecc_013_027_evaluator_syntax_gate_cc_delta_and_apply_reason(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "app.py").write_text("def f(x):\n    return x\n")
    (repo / "unused.py").write_text("def g():\n    return 1\n")
    (repo / "tests" / "test_app.py").write_text("from app import f\ndef test_ok(): assert f(1) == 1\n")

    repro = ReproTestSpec(
        test_file_path="tests/repro/test_r.py",
        test_code="from app import f\ndef test_r(): assert f(2) == 3\n",
        red_baseline_verified=True,
    )
    bad_syntax = CandidatePatch(
        candidate_id="bad_syn",
        persona=PersonaType.SURGICAL_MINIMALIST,
        explanation="breaks unimported file syntax",
        lines_added=2,
        lines_deleted=2,
        diff=(
            "--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n def f(x):\n-    return x\n+    return x + 1\n"
            "--- a/unused.py\n+++ b/unused.py\n@@ -1,2 +1,2 @@\n def g():\n-    return 1\n+    return (\n"
        ),
    )
    bloated = CandidatePatch(
        candidate_id="bloated",
        persona=PersonaType.ARCHITECTURAL_FIXER,
        explanation="adds branches",
        lines_added=5,
        lines_deleted=1,
        diff=(
            "--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,6 @@\n def f(x):\n+    if x == 2:\n+        return 3\n+    if x == 9:\n+        return 9\n-    return x\n+    return x\n"
        ),
    )
    mismatch = CandidatePatch(
        candidate_id="mismatch",
        persona=PersonaType.DEFENSIVE_GUARDIAN,
        explanation="bad hunk",
        lines_added=1,
        lines_deleted=1,
        diff="--- a/app.py\n+++ b/app.py\n@@ -99,1 +99,1 @@\n-NOPE\n+YEP\n",
    )

    evals, champ = PatchEvaluator(repo).evaluate_candidates([bad_syntax, bloated, mismatch], repro)
    by_id = {e.candidate_id: e for e in evals}

    assert by_id["bad_syn"].disqualified is True
    assert "syntax" in (by_id["bad_syn"].disqualification_reason or "").lower()

    assert by_id["bloated"].cyclomatic_delta > 0
    assert champ == "bloated"

    assert by_id["mismatch"].disqualified is True
    assert "apply" in (by_id["mismatch"].disqualification_reason or "").lower() or "patch" in (by_id["mismatch"].disqualification_reason or "").lower()
    assert "mismatch" in (by_id["mismatch"].disqualification_reason or "").lower() or "bounds" in (by_id["mismatch"].disqualification_reason or "").lower()
