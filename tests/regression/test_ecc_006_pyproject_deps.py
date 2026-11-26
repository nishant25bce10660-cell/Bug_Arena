"""Regression test for ECC-006: declare runtime httpx dependency in pyproject.toml."""

import tomllib
from pathlib import Path


def test_ecc_006_pyproject_declares_httpx_runtime_dependency():
    repo_root = Path(__file__).resolve().parents[2]
    data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    deps = [d.lower() for d in data["project"]["dependencies"]]
    assert any(d.startswith("httpx") for d in deps), f"Missing httpx in dependencies: {deps}"
