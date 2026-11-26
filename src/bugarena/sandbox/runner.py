"""Sandboxed command runner with optional container isolation, timeouts, and output scrubbing."""

import os
import shutil
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from bugarena.models.repro import ExecutionOutcome
from bugarena.sandbox.security import (
    BLOCKED_ENV_EXACT,
    BLOCKED_ENV_SUBSTRINGS,
    SecurityViolationError,
    sanitize_command_args,
    sanitize_env,
    scrub_sensitive_data,
)


def detect_container_runtime() -> str | None:
    """Return available container runtime executable ('docker' or 'podman'), or None."""
    return shutil.which("docker") or shutil.which("podman")


def build_container_command(
    runtime: str,
    workspace: Path,
    image: str,
    clean_args: Sequence[str],
) -> list[str]:
    """Construct a network-disabled, read-only, capability-dropped container invocation."""
    inner_args = list(clean_args)
    if inner_args and Path(inner_args[0]).stem.lower().startswith("python"):
        inner_args[0] = "python3"
    return [
        runtime,
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--pids-limit=64",
        "--memory=512m",
        "-v",
        f"{workspace.resolve()}:/work:rw",
        "-w",
        "/work",
        image,
        *inner_args,
    ]


def run_sandboxed_command(
    workspace: Path | str,
    args: Sequence[str],
    timeout_seconds: float = 30.0,
    env_override: Mapping[str, str] | None = None,
    isolation_mode: str = "auto",
    container_image: str = "python:3.11-slim",
) -> ExecutionOutcome:
    """
    Execute a command inside an ephemeral workspace safely.

    Uses optional container isolation (`docker`/`podman --network=none --read-only --cap-drop=ALL`)
    when `isolation_mode="container"` or `BUGARENA_SANDBOX_MODE=container` and a runtime exists;
    otherwise runs inside an isolated temporary host directory with strict env/arg sanitization.
    """
    ws_path = Path(workspace).resolve()
    if not ws_path.is_dir():
        raise SecurityViolationError(f"Workspace directory does not exist: {ws_path}")

    clean_args = sanitize_command_args(args)
    base_env = sanitize_env(dict(os.environ), allowlist_only=True)
    if env_override:
        base_env.update(sanitize_env(dict(env_override), allowlist_only=True))

    mode = isolation_mode
    if mode == "auto" and os.environ.get("BUGARENA_SANDBOX_MODE", "").lower() == "container":
        mode = "container"
    if mode == "container":
        runtime = detect_container_runtime()
        if not runtime:
            raise SecurityViolationError(
                "Container isolation requested but neither 'docker' nor 'podman' was found in PATH."
            )
        clean_args = build_container_command(runtime, ws_path, container_image, clean_args)

    sensitive_keys = [
        v
        for k, v in os.environ.items()
        if (
            k.upper() in BLOCKED_ENV_EXACT
            or any(s in k.upper() for s in BLOCKED_ENV_SUBSTRINGS)
        )
        and len(v) > 3
    ]
    start_time = time.perf_counter()
    extra_popen: dict[str, object] = {}
    if os.name == "nt":
        extra_popen["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    try:
        proc = subprocess.Popen(
            clean_args,
            cwd=str(ws_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=base_env,
            shell=False,
            start_new_session=os.name != "nt",
            **extra_popen,
        )

        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
            duration = time.perf_counter() - start_time
            return ExecutionOutcome(
                exit_code=proc.returncode,
                stdout=scrub_sensitive_data(stdout, sensitive_patterns=sensitive_keys, base_dir=ws_path),
                stderr=scrub_sensitive_data(stderr, sensitive_patterns=sensitive_keys, base_dir=ws_path),
                duration_seconds=round(duration, 3),
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    check=False,
                )
            else:
                killpg = getattr(os, "killpg", None)
                sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
                try:
                    if killpg is not None:
                        killpg(proc.pid, sigkill)
                    else:
                        proc.kill()
                except OSError:
                    proc.kill()
            try:
                stdout, stderr = proc.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = "", ""
            duration = time.perf_counter() - start_time
            return ExecutionOutcome(
                exit_code=-1,
                stdout=scrub_sensitive_data(stdout or "", sensitive_patterns=sensitive_keys, base_dir=ws_path),
                stderr=scrub_sensitive_data(
                    (stderr or "") + f"\nCommand timed out after {timeout_seconds} seconds",
                    sensitive_patterns=sensitive_keys,
                    base_dir=ws_path,
                ),
                duration_seconds=round(duration, 3),
                timed_out=True,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        duration = time.perf_counter() - start_time
        return ExecutionOutcome(
            exit_code=1,
            stdout="",
            stderr=scrub_sensitive_data(
                f"Execution error: {exc}",
                sensitive_patterns=sensitive_keys,
                base_dir=ws_path,
            ),
            duration_seconds=round(duration, 3),
            timed_out=False,
        )
