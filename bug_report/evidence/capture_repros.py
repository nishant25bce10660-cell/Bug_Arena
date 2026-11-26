"""Capture genuine Red baseline terminal output for BUG-002..BUG-021 in one sandbox."""

import sys
from pathlib import Path

from bugarena.sandbox.manager import EphemeralSandboxManager
from bugarena.sandbox.runner import run_sandboxed_command

repro_dir = Path("bug_report/evidence/repro")
out_dir = Path("bug_report/evidence")
mgr = EphemeralSandboxManager(".")

with mgr.create_sandbox() as sb:
    for idx in range(2, 22):
        bug_id = f"BUG-{idx:03d}"
        src_file = repro_dir / f"{bug_id}_repro.py"
        if not src_file.is_file():
            continue
        rel = f"tests/repro/test_{bug_id.lower()}.py"
        dst = sb / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src_file.read_text(encoding="utf-8"), encoding="utf-8")
        res = run_sandboxed_command(
            sb,
            [sys.executable, "-m", "pytest", rel, "-q"],
            timeout_seconds=30.0,
            env_override={"PYTHONPATH": "."},
        )
        txt = (
            f"$ python -m pytest {rel} -q\n"
            f"EXIT: {res.exit_code}\n"
            f"{res.stdout}\n"
            f"{res.stderr}\n"
        )
        (out_dir / f"{bug_id}-terminal.txt").write_text(txt, encoding="utf-8")
        print(f"{bug_id}: exit={res.exit_code} first_fail={next((l for l in res.stdout.splitlines() if l.startswith(('E ', 'FAILED'))), '')[:100]}")
