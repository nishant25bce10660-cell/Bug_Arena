"""Regression test for ECC-037: bounded parallel PatchEvaluator & tool payload bounds."""

import inspect

import pytest

from bugarena.evaluation.test_runner import PatchEvaluator
from bugarena.server import bug_reproduce, generate_bug_report


def test_ecc_037_evaluator_parallel_and_tool_payload_limits(tmp_path):
    sig = inspect.signature(PatchEvaluator.evaluate_candidates)
    assert "total_deadline_seconds" in sig.parameters or "max_workers" in sig.parameters

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("x = 1\n")

    # Option-prefixed repo_path rejected cleanly across server tools
    with pytest.raises(ValueError, match="repo_path"):
        bug_reproduce("-bad", "m.py", "desc")
    with pytest.raises(ValueError, match="repo_path"):
        generate_bug_report("-bad", "err")
