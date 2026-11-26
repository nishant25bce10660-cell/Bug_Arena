"""Full sandboxed evaluation harness for competing candidate patches."""

from __future__ import annotations

import ast
import concurrent.futures
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from bugarena.evaluation.ast_metrics import calculate_cyclomatic_delta
from bugarena.evaluation.scorer import compute_patch_score
from bugarena.models.agent import CandidatePatch
from bugarena.models.repro import ExecutionOutcome, ReproTestSpec
from bugarena.models.tournament import PatchEvaluation
from bugarena.sandbox.manager import EphemeralSandboxManager
from bugarena.sandbox.runner import run_sandboxed_command
from bugarena.sandbox.security import (
    SecurityViolationError,
    scrub_sensitive_data,
    validate_pytest_target,
    validate_safe_path,
)
from bugarena.tournament.patch_parser import _parse_header_path


def _extract_modified_py_files(diff_text: str) -> list[str]:
    """Extract unique normalized relative paths of modified .py files from a unified diff."""
    lines = diff_text.replace("\r\n", "\n").splitlines()
    files: list[str] = []
    i = 0
    while i < len(lines):
        if (
            lines[i].startswith("--- ")
            and i + 1 < len(lines)
            and lines[i + 1].startswith("+++ ")
        ):
            new_rel = _parse_header_path(lines[i + 1][4:], "b/")
            if new_rel != "/dev/null" and new_rel.endswith(".py") and new_rel not in files:
                files.append(new_rel)
            i += 2
        else:
            i += 1
    return files


def _parse_pytest_counts(outcome: ExecutionOutcome) -> tuple[int, int]:
    """
    Parse (regressions_count, total_regressions_checked) from pytest output cleanly.
    Disqualifies timeouts and collection errors (exit 2); flags missing/empty tests (exit 4/5) as 0/0.
    """
    text = f"{outcome.stdout}\n{outcome.stderr}"
    passed_m = re.search(r"(\d+)\s+passed", text)
    failed_m = re.search(r"(\d+)\s+failed", text)
    error_m = re.search(r"(\d+)\s+errors?", text)

    passed = int(passed_m.group(1)) if passed_m else 0
    failed = int(failed_m.group(1)) if failed_m else 0
    errors = int(error_m.group(1)) if error_m else 0

    if outcome.timed_out:
        return max(1, failed + errors), max(1, passed + failed + errors)
    if outcome.exit_code == 2:
        return max(1, failed + errors), max(1, passed + failed + errors)
    if outcome.exit_code in (4, 5):
        return 0, 0

    total = passed + failed + errors
    regs = failed + errors
    if outcome.exit_code != 0 and regs == 0:
        regs = 1
        total = max(1, total)
    return regs, max(total, regs)


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
        max_workers: int = 4,
        total_deadline_seconds: float | None = 180.0,
    ) -> tuple[list[PatchEvaluation], str | None]:
        """
        Evaluate all candidate patches concurrently inside bounded sandboxes with an overall deadline,
        returning ranked evaluations and champion ID.
        """
        validate_pytest_target(repro_spec.test_file_path)
        validate_pytest_target(self.regression_test_dir)
        manager = EphemeralSandboxManager(self.base_repo_path)

        def _evaluate_one(cand: CandidatePatch) -> PatchEvaluation:
            lines_changed = cand.lines_added + cand.lines_deleted
            with manager.create_sandbox() as sandbox_path:
                # 1. Write the verified reproduction test into the sandbox
                test_file = validate_safe_path(sandbox_path, repro_spec.test_file_path)
                test_file.parent.mkdir(parents=True, exist_ok=True)
                test_file.write_text(repro_spec.test_code, encoding="utf-8")

                # 2. Apply candidate patch (record real failure reason on error)
                try:
                    manager.apply_patch(sandbox_path, cand.diff)
                except (OSError, ValueError, SecurityViolationError) as exc:
                    clean_err = scrub_sensitive_data(str(exc), base_dir=sandbox_path)
                    return PatchEvaluation(
                        candidate_id=cand.candidate_id,
                        repro_passed=False,
                        regressions_count=0,
                        total_regressions_checked=0,
                        diff_churn=lines_changed,
                        cyclomatic_delta=0,
                        mutation_kill_ratio=None,
                        score=0.0,
                        disqualified=True,
                        disqualification_reason=f"Patch application failed: {clean_err}",
                    )

                # 3. Hard AST/Syntax Gate & Cyclomatic Complexity Delta across modified .py files
                delta_cc = 0
                for rel_py in _extract_modified_py_files(cand.diff):
                    orig_p = self.base_repo_path / rel_py
                    patched_p = sandbox_path / rel_py
                    if not patched_p.is_file():
                        continue
                    orig_src = orig_p.read_text(encoding="utf-8", errors="replace") if orig_p.is_file() else ""
                    new_src = patched_p.read_text(encoding="utf-8", errors="replace")
                    try:
                        ast.parse(new_src, filename=rel_py)
                        delta_cc += calculate_cyclomatic_delta(orig_src, new_src)
                    except (SyntaxError, ValueError) as exc:
                        return PatchEvaluation(
                            candidate_id=cand.candidate_id,
                            repro_passed=False,
                            regressions_count=0,
                            total_regressions_checked=0,
                            diff_churn=lines_changed,
                            cyclomatic_delta=delta_cc,
                            mutation_kill_ratio=None,
                            score=0.0,
                            disqualified=True,
                            disqualification_reason=f"Syntax/AST gate failed in '{rel_py}': {exc}",
                        )

                # 4. Run reproduction test
                repro_outcome = run_sandboxed_command(
                    workspace=sandbox_path,
                    args=[self.python_executable, "-m", "pytest", "-q", "--", repro_spec.test_file_path],
                    timeout_seconds=timeout_seconds,
                    env_override={"PYTHONPATH": "."},
                )
                repro_passed = repro_outcome.exit_code == 0 and not repro_outcome.timed_out

                # 5. Run regression suite (excluding the repro test itself)
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
                regressions, total_tests = _parse_pytest_counts(reg_outcome)

                eval_record = compute_patch_score(
                    candidate_id=cand.candidate_id,
                    repro_passed=repro_passed,
                    regressions_count=regressions,
                    total_regressions=total_tests,
                    lines_changed=lines_changed,
                    cyclomatic_delta=delta_cc,
                )
                if reg_outcome.timed_out and not eval_record.disqualified:
                    return eval_record.model_copy(
                        update={
                            "score": 0.0,
                            "disqualified": True,
                            "disqualification_reason": "Regression test suite timed out.",
                        }
                    )
                return eval_record

        if not candidates:
            return [], None

        workers = max(1, min(max_workers, os.cpu_count() or 2, len(candidates)))
        evaluations: list[PatchEvaluation] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {pool.submit(_evaluate_one, cand): cand for cand in candidates}
            done, _not_done = concurrent.futures.wait(
                future_map.keys(), timeout=total_deadline_seconds
            )
            for fut, cand in future_map.items():
                if fut in done:
                    evaluations.append(fut.result())
                else:
                    fut.cancel()
                    evaluations.append(
                        PatchEvaluation(
                            candidate_id=cand.candidate_id,
                            repro_passed=False,
                            regressions_count=0,
                            total_regressions_checked=0,
                            diff_churn=cand.lines_added + cand.lines_deleted,
                            cyclomatic_delta=0,
                            mutation_kill_ratio=None,
                            score=0.0,
                            disqualified=True,
                            disqualification_reason="Evaluation exceeded total tournament deadline.",
                        )
                    )

        ranked = sorted(evaluations, key=lambda e: e.score, reverse=True)
        champion_id = next((e.candidate_id for e in ranked if not e.disqualified), None)
        return ranked, champion_id
