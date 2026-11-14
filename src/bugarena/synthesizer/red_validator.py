"""Red-First baseline reproduction validator enforcing that candidate repro tests fail."""

import sys
from pathlib import Path

from bugarena.models.repro import ReproTestSpec
from bugarena.sandbox.manager import EphemeralSandboxManager
from bugarena.sandbox.runner import run_sandboxed_command
from bugarena.sandbox.security import validate_safe_path


class ReproductionFalsePositiveError(Exception):
    """Raised when a candidate reproduction test passes on the untouched buggy codebase."""


def validate_red_baseline(
    base_repo_path: Path | str,
    test_rel_path: str,
    test_code: str,
    python_executable: str | None = None,
    timeout_seconds: float = 30.0,
) -> ReproTestSpec:
    """
    Validate that a synthesized reproduction test fails on the original codebase (Red-First guarantee).

    If the test passes on the original codebase, it is a false positive and rejected.
    """
    repo = Path(base_repo_path).resolve()
    py_exec = python_executable or sys.executable

    manager = EphemeralSandboxManager(base_repo_path=repo)
    with manager.create_sandbox() as sandbox_path:
        # Write candidate test into sandbox
        test_file = validate_safe_path(sandbox_path, test_rel_path)
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(test_code, encoding="utf-8")

        # Execute pytest on the newly synthesized test
        outcome = run_sandboxed_command(
            workspace=sandbox_path,
            args=[py_exec, "-m", "pytest", test_rel_path, "-q"],
            timeout_seconds=timeout_seconds,
            env_override={"PYTHONPATH": "."},
        )

        if outcome.exit_code == 0:
            raise ReproductionFalsePositiveError(
                f"Candidate reproduction test '{test_rel_path}' passed on unpatched codebase. "
                "A valid reproduction test must fail to prove defect existence."
            )

        return ReproTestSpec(
            test_file_path=test_rel_path,
            test_code=test_code,
            red_baseline_verified=True,
            initial_outcome=outcome,
        )
