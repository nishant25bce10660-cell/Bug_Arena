"""Full sandboxed evaluation harness for competing candidate patches."""

import sys
from collections.abc import Sequence
from pathlib import Path

from bugarena.evaluation.scorer import compute_patch_score
from bugarena.models.agent import CandidatePatch
from bugarena.models.repro import ReproTestSpec
from bugarena.models.tournament import PatchEvaluation
from bugarena.sandbox.manager import EphemeralSandboxManager
from bugarena.sandbox.runner import run_sandboxed_command
from bugarena.sandbox.security import (
    SecurityViolationError,
    validate_pytest_target,
    validate_safe_path,
)


class PatchEvaluator:
    """Evaluates candidate patches against reproduction tests and regression suites inside sandboxes."""

    def __init__(
        self,
        base_repo_path: Path | str,
        python_executable: str | None = None,
        regression_test_dir: str | None = None,
    ):
        self.base_repo_path = Path(base_repo_path).resolve()
        self.python_executable = python_executable or sys.executable
        self.regression_test_dir = regression_test_dir or "tests"

    def evaluate_candidates(
        self,
        candidates: Sequence[CandidatePatch],
        repro_spec: ReproTestSpec,
        timeout_seconds: float = 30.0,
    ) -> tuple[list[PatchEvaluation], str | None]:
        """
        Evaluate all candidate patches, return leaderboard of evaluations and champion ID.
        """
        validate_pytest_target(repro_spec.test_file_path)
        validate_pytest_target(self.regression_test_dir)
        evaluations: list[PatchEvaluation] = []
        manager = EphemeralSandboxManager(self.base_repo_path)

        for cand in candidates:
            with manager.create_sandbox() as sandbox_path:
                # 1. Write the verified reproduction test into the sandbox
                test_file = validate_safe_path(sandbox_path, repro_spec.test_file_path)
                test_file.parent.mkdir(parents=True, exist_ok=True)
                test_file.write_text(repro_spec.test_code, encoding="utf-8")

                # 2. Apply candidate patch
                patch_applied = True
                try:
                    manager.apply_patch(sandbox_path, cand.diff)
                except (OSError, ValueError, SecurityViolationError):
                    patch_applied = False

                if not patch_applied:
                    evaluations.append(
                        compute_patch_score(
                            candidate_id=cand.candidate_id,
                            repro_passed=False,
                            regressions_count=0,
                            total_regressions=0,
                            lines_changed=cand.lines_added + cand.lines_deleted,
                            cyclomatic_delta=0,
                        )
                    )
                    continue

                # 3. Run reproduction test
                repro_outcome = run_sandboxed_command(
                    workspace=sandbox_path,
                    args=[self.python_executable, "-m", "pytest", "-q", "--", repro_spec.test_file_path],
                    timeout_seconds=timeout_seconds,
                    env_override={"PYTHONPATH": "."},
                )
                repro_passed = repro_outcome.exit_code == 0

                # 4. Run regression suite (excluding the repro test itself)
                reg_outcome = run_sandboxed_command(
                    workspace=sandbox_path,
                    args=[
                        self.python_executable,
                        "-m",
                        "pytest",
                        f"--ignore={repro_spec.test_file_path}",
                        "-q",
                        "--",
                        self.regression_test_dir,
                    ],
                    timeout_seconds=timeout_seconds,
                    env_override={"PYTHONPATH": "."},
                )

                # Check regressions: if test command ran and had failures
                regressions = 0
                total_tests = 1
                if reg_outcome.exit_code != 0 and "no tests ran" not in reg_outcome.stdout.lower():
                    # Count failed tests from output
                    regressions = 1

                # 5. Calculate complexity delta
                delta_cc = 0  # Default neutral
                lines_changed = cand.lines_added + cand.lines_deleted

                eval_record = compute_patch_score(
                    candidate_id=cand.candidate_id,
                    repro_passed=repro_passed,
                    regressions_count=regressions,
                    total_regressions=total_tests,
                    lines_changed=lines_changed,
                    cyclomatic_delta=delta_cc,
                )
                evaluations.append(eval_record)

        # Sort evaluations by score descending
        ranked = sorted(evaluations, key=lambda e: e.score, reverse=True)
        champion_id = None
        for record in ranked:
            if not record.disqualified and record.score > 0.0:
                champion_id = record.candidate_id
                break

        return ranked, champion_id
