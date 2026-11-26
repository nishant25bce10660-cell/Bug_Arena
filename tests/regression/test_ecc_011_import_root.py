"""Regression test for ECC-011 (BA-003): repo root & src sys.path without swallowing ImportError."""

import subprocess
import sys

from bugarena.models.bug import SuspectLocation
from bugarena.synthesizer.test_generator import generate_reproduction_test_code


def test_ecc_011_no_swallowed_importerror_and_correct_root(tmp_path):
    suspect = SuspectLocation(
        file_path="src/calc.py",
        function_name="divide",
        line_range=(1, 3),
        confidence=0.9,
        bug_type="ZeroDivisionError",
        reasoning="div zero",
        code_snippet="return a / b",
    )
    code = generate_reproduction_test_code(
        suspect, "div zero", call_expr="divide(10, 0)", expected_behavior="divide(10, 0) == 0.0"
    )
    assert "except ImportError:\n    pass" not in code
    assert "except ImportError:" not in code

    # Write under nested tests/repro/test_issue_x.py against missing module -> ImportError (exit 1 with ImportError, NOT NameError)
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    repro_dir = repo / "tests" / "repro"
    repro_dir.mkdir(parents=True)
    test_file = repro_dir / "test_issue_miss.py"
    test_file.write_text(code, encoding="utf-8")

    res = subprocess.run(
        [sys.executable, "-m", "pytest", "--", str(test_file)],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    assert "ImportError" in res.stdout or "ModuleNotFoundError" in res.stdout
    assert "NameError" not in res.stdout
