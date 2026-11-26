"""Regression test for ECC-005: container command builder & honest isolation documentation."""

from pathlib import Path

from bugarena.sandbox import runner


def test_ecc_005_container_command_builder_and_honest_docs():
    assert hasattr(runner, "build_container_command")
    cmd = runner.build_container_command(
        "docker",
        Path("/tmp/ws"),
        "python:3.11-slim",
        ["python", "-m", "pytest", "-q"],
    )
    assert "--network=none" in cmd
    assert "--read-only" in cmd
    assert "--cap-drop=ALL" in cmd

    readme = Path("README.md").read_text(encoding="utf-8")
    assert "isolated subshell/tempfs" not in readme
    assert "optional" in readme.lower() or "host" in readme.lower()
