import sys

import pytest

from bugarena.models.bug import SuspectLocation
from bugarena.models.repro import ReproTestSpec
from bugarena.synthesizer.red_validator import ReproductionFalsePositiveError, validate_red_baseline
from bugarena.synthesizer.test_generator import generate_reproduction_test_code

SAMPLE_BUGGY_MODULE = """
def divide(a: float, b: float) -> float:
    return a / b
"""


def test_generate_reproduction_test_code():
    suspect = SuspectLocation(
        file_path="src/math/calculator.py",
        function_name="divide",
        line_range=(1, 3),
        confidence=0.9,
        bug_type="ZeroDivisionError",
        reasoning="Crashes on zero",
        code_snippet="return a / b",
    )
    code = generate_reproduction_test_code(
        suspect=suspect,
        bug_description="divide(10, 0) raises ZeroDivisionError",
        call_expr="divide(10, 0)",
        expected_behavior="raises ZeroDivisionError",
    )
    assert "def test_reproduction_" in code
    assert "divide(10, 0)" in code
    assert "pytest.raises(ZeroDivisionError)" in code


def test_validate_red_baseline_success(tmp_path):
    repo = tmp_path / "repo"
    math_dir = repo / "src"
    math_dir.mkdir(parents=True)
    (math_dir / "calc.py").write_text(SAMPLE_BUGGY_MODULE)

    # In the buggy code, divide(10, 0) raises ZeroDivisionError.
    # Desired behavior test asserts divide(10, 0) == 0.0, which fails on buggy code, proving Red baseline!
    desired_behavior_test = (
        "from src.calc import divide\n"
        "def test_divide_zero_safe():\n"
        "    assert divide(10, 0) == 0.0\n"
    )

    spec = validate_red_baseline(
        base_repo_path=repo,
        test_rel_path="tests/test_repro.py",
        test_code=desired_behavior_test,
        python_executable=sys.executable,
    )

    assert isinstance(spec, ReproTestSpec)
    assert spec.red_baseline_verified is True
    assert spec.initial_outcome is not None
    assert spec.initial_outcome.exit_code != 0
    assert (
        "ZeroDivisionError" in spec.initial_outcome.stdout
        or "ZeroDivisionError" in spec.initial_outcome.stderr
    )


def test_validate_red_baseline_rejects_passing_test(tmp_path):
    repo = tmp_path / "repo"
    math_dir = repo / "src"
    math_dir.mkdir(parents=True)
    (math_dir / "calc.py").write_text(SAMPLE_BUGGY_MODULE)

    # A test that already passes on the buggy codebase is NOT a valid bug reproduction!
    passing_test = (
        "from src.calc import divide\ndef test_divide_normal():\n    assert divide(10, 2) == 5.0\n"
    )

    with pytest.raises(ReproductionFalsePositiveError, match="passed on unpatched codebase"):
        validate_red_baseline(
            base_repo_path=repo,
            test_rel_path="tests/test_repro.py",
            test_code=passing_test,
            python_executable=sys.executable,
        )
