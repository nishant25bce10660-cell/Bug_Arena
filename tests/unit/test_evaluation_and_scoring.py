from bugarena.evaluation.ast_metrics import compute_churn_score, compute_complexity_score
from bugarena.evaluation.scorer import compute_patch_score
from bugarena.models.tournament import PatchEvaluation


def test_churn_score():
    # 0 lines changed -> 1.0
    assert compute_churn_score(0) == 1.0
    # 25 lines changed -> 0.5
    assert compute_churn_score(25) == 0.5
    # 50 lines changed -> 0.0
    assert compute_churn_score(50) == 0.0
    # 100 lines changed -> 0.0 (clamped)
    assert compute_churn_score(100) == 0.0


def test_complexity_score():
    # 0 complexity delta -> 1.0
    assert compute_complexity_score(0) == 1.0
    # +5 complexity delta -> 0.5
    assert compute_complexity_score(5) == 0.5
    # +10 complexity delta -> 0.0
    assert compute_complexity_score(10) == 0.0
    # Negative delta (simplification) -> 1.0
    assert compute_complexity_score(-2) == 1.0


def test_scorer_hard_disqualification_repro_fail():
    eval_res = compute_patch_score(
        candidate_id="cand_1",
        repro_passed=False,
        regressions_count=0,
        total_regressions=100,
        lines_changed=2,
        cyclomatic_delta=0,
    )
    assert isinstance(eval_res, PatchEvaluation)
    assert eval_res.disqualified is True
    assert eval_res.score == 0.0
    assert "Reproduction test failed" in (eval_res.disqualification_reason or "")


def test_scorer_hard_disqualification_regressions():
    eval_res = compute_patch_score(
        candidate_id="cand_2",
        repro_passed=True,
        regressions_count=2,  # Regressions introduced!
        total_regressions=100,
        lines_changed=5,
        cyclomatic_delta=1,
    )
    assert eval_res.disqualified is True
    assert eval_res.score == 0.0
    assert "regressions" in (eval_res.disqualification_reason or "").lower()


def test_scorer_ranking_prefers_minimal_churn():
    # Both pass repro with 0 regressions, but surgical has less churn and lower CC
    surgical_eval = compute_patch_score(
        candidate_id="cand_surgical",
        repro_passed=True,
        regressions_count=0,
        total_regressions=50,
        lines_changed=2,
        cyclomatic_delta=1,
    )
    architectural_eval = compute_patch_score(
        candidate_id="cand_arch",
        repro_passed=True,
        regressions_count=0,
        total_regressions=50,
        lines_changed=40,
        cyclomatic_delta=4,
    )

    assert not surgical_eval.disqualified
    assert not architectural_eval.disqualified
    assert surgical_eval.score > architectural_eval.score
    assert surgical_eval.score > 90.0
