"""Regression test for ECC-001 and ECC-002: AST allowlist & verified repro_spec binding."""

import pytest

from bugarena.models.bug import SuspectLocation
from bugarena.sandbox.security import SecurityViolationError
from bugarena.server import agent_fix_tournament, bug_reproduce, evaluate_patches
from bugarena.synthesizer.test_generator import generate_reproduction_test_code


def _suspect() -> SuspectLocation:
    return SuspectLocation(
        file_path="src/calc.py",
        function_name="divide",
        line_range=(1, 3),
        confidence=0.9,
        bug_type="ZeroDivisionError",
        reasoning="div zero",
        code_snippet="return a / b",
    )


def test_ecc_001_rejects_unsafe_call_expr_and_expected_behavior():
    with pytest.raises(ValueError, match="Unsafe"):
        generate_reproduction_test_code(
            _suspect(),
            "rce",
            call_expr="__import__('pathlib').Path('pwn.txt').write_text('X')",
            expected_behavior="True",
        )
    with pytest.raises(ValueError, match="Unsafe"):
        generate_reproduction_test_code(
            _suspect(),
            "rce",
            call_expr="divide(10, 0)",
            expected_behavior="eval('1+1') == 2",
        )


def test_ecc_002_evaluate_patches_binds_repro_spec_and_blocks_arbitrary_code(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "m.py").write_text("def f():\n    return 1\n")

    rep = bug_reproduce(
        repo_path=str(repo),
        suspect_file="src/m.py",
        bug_description="want 2",
        function_name="f",
        call_expr="f()",
        expected_behavior="f() == 2",
    )
    assert rep["status"] == "REPRODUCED_RED"

    t = agent_fix_tournament(
        repo_path=str(repo),
        repro_test_file=rep["test_file_path"],
        candidate_patches_raw=[
            {
                "candidate_id": "c1",
                "persona": "surgical_minimalist",
                "explanation": "fix",
                "diff": "--- a/src/m.py\n+++ b/src/m.py\n@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return 2\n",
            }
        ],
    )

    marker = tmp_path / "pwned_eval.txt"
    with pytest.raises((SecurityViolationError, ValueError)):
        evaluate_patches(
            repo_path=str(repo),
            tournament_id=t["tournament_id"],
            repro_test_file=rep["test_file_path"],
            repro_code=f"import pathlib\npathlib.Path({str(marker)!r}).write_text('X')\ndef test_x():\n    assert True\n",
        )
    assert not marker.exists()
