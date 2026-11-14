"""Sandboxed command runner with timeout enforcement and output scrubbing."""

import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from bugarena.models.repro import ExecutionOutcome
from bugarena.sandbox.security import (
    SecurityViolationError,
    sanitize_command_args,
    sanitize_env,
    scrub_sensitive_data,
)


def run_sandboxed_command(
    workspace: Path | str,
    args: Sequence[str],
    timeout_seconds: float = 30.0,
    env_override: Mapping[str, str] | None = None,
) -> ExecutionOutcome:
    """
    Execute a command inside a sandboxed workspace directory safely.

    Enforces argument sanitization, secret stripping from env, hard timeouts,
    and output scrubbing.
    """
    ws_path = Path(workspace).resolve()
    if not ws_path.is_dir():
        raise SecurityViolationError(f"Workspace directory does not exist: {ws_path}")

    clean_args = sanitize_command_args(args)
    base_env = sanitize_env(dict(os.environ))
    if env_override:
        base_env.update(env_override)

    start_time = time.perf_counter()
    try:
        proc = subprocess.Popen(
            clean_args,
            cwd=str(ws_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=base_env,
            shell=False,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
            duration = time.perf_counter() - start_time
            return ExecutionOutcome(
                exit_code=proc.returncode,
                stdout=scrub_sensitive_data(stdout),
                stderr=scrub_sensitive_data(stderr),
                duration_seconds=round(duration, 3),
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            duration = time.perf_counter() - start_time
            return ExecutionOutcome(
                exit_code=-1,
                stdout=scrub_sensitive_data(stdout or ""),
                stderr=scrub_sensitive_data(
                    (stderr or "") + f"\nCommand timed out after {timeout_seconds} seconds"
                ),
                duration_seconds=round(duration, 3),
                timed_out=True,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        duration = time.perf_counter() - start_time
        return ExecutionOutcome(
            exit_code=1,
            stdout="",
            stderr=f"Execution error: {exc}",
            duration_seconds=round(duration, 3),
            timed_out=False,
        )
