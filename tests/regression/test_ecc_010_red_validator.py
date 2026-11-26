"""Regression test for ECC-010: validate_red_baseline accepts ONLY pytest exit 1 and no timeout."""

import sys

import pytest

from bugarena.synthesizer.red_validator import (
    ReproductionFalsePositiveError,
    validate_red_baseline,
)


def test_ecc_010_rejects_syntax_error_empty_and_timeout(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("x = 1\n")

    # Exit code 2 (collection/syntax error) MUST fail, not return REPRODUCED_RED
    with pytest.raises((ReproductionFalsePositiveError, ValueError)):
        validate_red_baseline(repo, "tests/repro/test_bad_syntax.py", "def broken( :")

    # Exit code 5 (no tests collected) MUST fail
    with pytest.raises((ReproductionFalsePositiveError, ValueError)):
        validate_red_baseline(repo, "tests/repro/test_empty.py", "x = 1\n")

    # Timeout MUST fail
    with pytest.raises((ReproductionFalsePositiveError, TimeoutError, ValueError)):
        validate_red_baseline(
            repo,
            "tests/repro/test_timeout.py",
            "import time\ndef test_slow():\n    time.sleep(2.0)\n    assert False\n",
            python_executable=sys.executable,
            timeout_seconds=0.3,
        )
