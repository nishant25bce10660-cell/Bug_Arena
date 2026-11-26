"""Regression test for ECC-043: gitignore coverage for secrets/reports/cache and .env.example placeholders."""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_ecc_043_gitignore_and_env_example_placeholders():
    for sample in (".env.local", "reports/x.md", ".ruff_cache/x", ".bugarena/x"):
        res = subprocess.run(
            ["git", "check-ignore", sample],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, f"Expected {sample} to be gitignored"

    ex_ignored = subprocess.run(
        ["git", "check-ignore", ".env.example"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ex_ignored.returncode != 0, ".env.example must remain tracked"

    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    uncommented_blanks = [
        ln
        for ln in env_example.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#") and ln.rstrip().endswith("=")
    ]
    assert not uncommented_blanks, f"Found uncommented blank keys in .env.example: {uncommented_blanks}"
