"""Isolated probe runner: temp workspace copy, timeouts, process-tree cleanup, scrubbed output."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from bugarena.models.repro import ExecutionOutcome
from bugarena.sandbox.manager import EphemeralSandboxManager
from bugarena.sandbox.security import scrub_sensitive_data


def _kill_process_tree(proc: subprocess.Popen[str]) -> None:
    """Terminate a timed-out subprocess and its child process tree."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            proc.kill()


def _minimal_probe_env(sandbox_path: Path) -> dict[str, str]:
    """Allowlist-only environment for isolated probe execution (never leaks API keys)."""
    allowed = (
        "PATH",
        "SYSTEMROOT",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
        "LANG",
        "LC_ALL",
        "HOME",
        "USERPROFILE",
    )
    env = {k: os.environ[k] for k in allowed if k in os.environ}
    src_dir = sandbox_path / "src"
    env["PYTHONPATH"] = (
        f"{src_dir}{os.pathsep}{sandbox_path}" if src_dir.is_dir() else str(sandbox_path)
    )
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["BUGARENA_ISOLATED_PROBE"] = "1"
    return env


def run_isolated_probe(
    repo_path: Path | str,
    probe_script: str,
    *,
    timeout_seconds: float = 15.0,
    python_executable: str | None = None,
) -> ExecutionOutcome:
    """
    Execute an inline probe Python script inside a fresh ephemeral copy of repo_path.
    Never modifies the target repo, strips secrets from env, kills process groups on timeout,
    and scrubs output before returning.
    """
    repo = Path(repo_path).resolve()
    py_exec = python_executable or sys.executable
    manager = EphemeralSandboxManager(base_repo_path=repo)

    with manager.create_sandbox() as sandbox_path:
        probe_file = sandbox_path / "_bugarena_probe_runner.py"
        probe_file.write_text(probe_script, encoding="utf-8")

        env = _minimal_probe_env(sandbox_path)
        start = time.perf_counter()
        timed_out = False
        popen_kwargs: dict[str, object] = {
            "cwd": str(sandbox_path),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": env,
            "shell": False,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(
            [py_exec, str(probe_file)],
            **popen_kwargs,  # type: ignore[arg-type]
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
            exit_code = proc.returncode if proc.returncode is not None else -1
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", "Timed out and killed process tree."
            exit_code = -1

        duration = round(time.perf_counter() - start, 3)
        clean_out = scrub_sensitive_data(stdout or "", base_dir=sandbox_path)
        clean_err = scrub_sensitive_data(stderr or "", base_dir=sandbox_path)
        clean_out = clean_out.replace(str(repo), "[REPO]")
        clean_err = clean_err.replace(str(repo), "[REPO]")

        return ExecutionOutcome(
            exit_code=exit_code,
            stdout=clean_out[:8000],
            stderr=clean_err[:8000],
            duration_seconds=duration,
            timed_out=timed_out,
        )
