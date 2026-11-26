"""Composite scoring engine and hard disqualification gating."""

from bugarena.evaluation.ast_metrics import compute_churn_score, compute_complexity_score
from bugarena.models.tournament import PatchEvaluation


def compute_patch_score(
    candidate_id: str,
    repro_passed: bool,
    regressions_count: int,
    total_regressions: int,
    lines_changed: int,
    cyclomatic_delta: int,
    mutation_kill_ratio: float | None = None,
) -> PatchEvaluation:
    """
    Evaluate candidate patch using hard disqualification gates and composite score formula:
    S(p) = 40*R + 30*(1 - reg/total) + 15*Q_churn + 10*Q_complexity + 5*Q_mutation
    """
    if regressions_count < 0 or total_regressions < 0:
        raise ValueError("regressions_count and total_regressions must be non-negative.")

    # Hard Disqualification Gate 1: Red-to-Green Gate
    if not repro_passed:
        return PatchEvaluation(
            candidate_id=candidate_id,
            repro_passed=False,
            regressions_count=regressions_count,
            total_regressions_checked=total_regressions,
            diff_churn=lines_changed,
            cyclomatic_delta=cyclomatic_delta,
            mutation_kill_ratio=mutation_kill_ratio,
            score=0.0,
            disqualified=True,
            disqualification_reason="Reproduction test failed: Patch did not resolve the defect.",
        )

    # Hard Disqualification Gate 2: Zero Regression Gate
    if regressions_count > 0:
        return PatchEvaluation(
            candidate_id=candidate_id,
            repro_passed=True,
            regressions_count=regressions_count,
            total_regressions_checked=total_regressions,
            diff_churn=lines_changed,
            cyclomatic_delta=cyclomatic_delta,
            mutation_kill_ratio=mutation_kill_ratio,
            score=0.0,
            disqualified=True,
            disqualification_reason=f"Introduced {regressions_count} regressions in existing test suite.",
        )

    # Composite Score Calculation (no free points for missing tests or unmeasured mutation)
    q_repro = 40.0
    q_reg = (
        (1.0 - min(1.0, regressions_count / total_regressions)) * 30.0
        if total_regressions > 0
        else 0.0
    )
    q_churn = compute_churn_score(lines_changed) * 15.0
    q_complexity = compute_complexity_score(cyclomatic_delta) * 10.0
    q_mutation = (mutation_kill_ratio if mutation_kill_ratio is not None else 0.0) * 5.0

    composite_score = round(q_repro + q_reg + q_churn + q_complexity + q_mutation, 2)
    composite_score = min(100.0, max(0.0, composite_score))

    return PatchEvaluation(
        candidate_id=candidate_id,
        repro_passed=True,
        regressions_count=0,
        total_regressions_checked=total_regressions,
        diff_churn=lines_changed,
        cyclomatic_delta=cyclomatic_delta,
        mutation_kill_ratio=mutation_kill_ratio,
        score=composite_score,
        disqualified=False,
        disqualification_reason=None,
    )
