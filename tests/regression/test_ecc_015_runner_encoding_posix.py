"""Regression test for ECC-015: explicit UTF-8 replacement, POSIX process-group kill, bounded wait."""

import inspect
import sys

from bugarena.sandbox import runner


def test_ecc_015_runner_preserves_invalid_utf8_and_sets_posix_kill(tmp_path):
    # Child emits invalid UTF-8 byte 0xff alongside valid text: must NOT drop output silently!
    out = runner.run_sandboxed_command(
        tmp_path,
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'before:\\xff:after\\n')"],
        timeout_seconds=5.0,
    )
    assert out.exit_code == 0
    assert "before:" in out.stdout and "after" in out.stdout

    src = inspect.getsource(runner.run_sandboxed_command)
    assert 'errors="replace"' in src
    assert "start_new_session" in src
    assert "killpg" in src or "_kill_process_tree" in src
