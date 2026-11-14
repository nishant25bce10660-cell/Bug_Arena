import sys

from bugarena.models.repro import ExecutionOutcome
from bugarena.sandbox.manager import EphemeralSandboxManager
from bugarena.sandbox.runner import run_sandboxed_command


def test_run_sandboxed_command_success(tmp_path):
    outcome = run_sandboxed_command(
        workspace=tmp_path, args=[sys.executable, "-c", "print('sandbox_ok')"], timeout_seconds=5.0
    )
    assert isinstance(outcome, ExecutionOutcome)
    assert outcome.exit_code == 0
    assert "sandbox_ok" in outcome.stdout
    assert not outcome.timed_out
    assert outcome.duration_seconds >= 0.0


def test_run_sandboxed_command_timeout(tmp_path):
    outcome = run_sandboxed_command(
        workspace=tmp_path,
        args=[sys.executable, "-c", "import time; time.sleep(5)"],
        timeout_seconds=0.5,
    )
    assert outcome.timed_out is True
    assert outcome.exit_code != 0


def test_run_sandboxed_command_captures_failure(tmp_path):
    outcome = run_sandboxed_command(
        workspace=tmp_path,
        args=[sys.executable, "-c", "raise ValueError('intentional_fail')"],
        timeout_seconds=5.0,
    )
    assert outcome.exit_code != 0
    assert "ValueError: intentional_fail" in outcome.stderr
    assert not outcome.timed_out


def test_ephemeral_sandbox_manager_lifecycle(tmp_path):
    # Setup a mock repository
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "calc.py").write_text("def add(a, b): return a + b\n")

    manager = EphemeralSandboxManager(base_repo_path=repo_dir)
    with manager.create_sandbox() as sandbox_path:
        assert sandbox_path.exists()
        calc_file = sandbox_path / "src" / "calc.py"
        assert calc_file.exists()
        assert "def add(a, b):" in calc_file.read_text()

        # Verify mutation in sandbox does NOT touch original repo
        calc_file.write_text("def add(a, b): return a - b\n")
        assert "return a - b" in calc_file.read_text()
        assert "return a + b" in (repo_dir / "src" / "calc.py").read_text()

    # After exit, sandbox directory should be cleaned up
    assert not sandbox_path.exists()


def test_ephemeral_sandbox_apply_patch(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    file_to_patch = repo_dir / "main.py"
    file_to_patch.write_text("def hello():\n    return 'old'\n")

    manager = EphemeralSandboxManager(base_repo_path=repo_dir)
    diff = (
        "--- a/main.py\n"
        "+++ b/main.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def hello():\n"
        "-    return 'old'\n"
        "+    return 'new'\n"
    )

    with manager.create_sandbox() as sandbox_path:
        manager.apply_patch(sandbox_path, diff)
        patched_content = (sandbox_path / "main.py").read_text()
        assert "return 'new'" in patched_content
