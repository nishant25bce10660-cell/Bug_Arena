"""Regression test for ECC-018: pytest '--' option injection, env allowlist, and -c bypass."""

import pytest

from bugarena.evaluation.test_runner import PatchEvaluator
from bugarena.models.agent import CandidatePatch, PersonaType
from bugarena.models.repro import ReproTestSpec
from bugarena.sandbox.security import (
    SecurityViolationError,
    sanitize_command_args,
    sanitize_env,
)
from bugarena.synthesizer.red_validator import validate_red_baseline


def test_ecc_018_rejects_option_prefixed_test_paths(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("x = 1\n")

    with pytest.raises((SecurityViolationError, ValueError)):
        validate_red_baseline(repo, "--version", "assert False")

    repro = ReproTestSpec(
        test_file_path="--version",
        test_code="assert False",
        red_baseline_verified=True,
    )
    cand = CandidatePatch(
        candidate_id="c1",
        persona=PersonaType.SURGICAL_MINIMALIST,
        explanation="noop",
        diff="--- a/m.py\n+++ b/m.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n",
        lines_added=1,
        lines_deleted=1,
    )
    with pytest.raises((SecurityViolationError, ValueError)):
        PatchEvaluator(repo).evaluate_candidates([cand], repro)


def test_ecc_018_sanitize_env_and_allowlist():
    dirty = {
        "PATH": "/usr/bin",
        "MYSQL_PWD": "secret",
        "PYTHONSTARTUP": "/tmp/evil.py",
        "GH_PAT": "ghp_xyz",
        "HTTP_PROXY": "http://127.0.0.1:8888",
        "CI_JOB_JWT": "jwt_tok",
        "PGPASSFILE": "/home/u/.pgpass",
    }
    clean = sanitize_env(dirty)
    for bad in ("MYSQL_PWD", "PYTHONSTARTUP", "GH_PAT", "HTTP_PROXY", "CI_JOB_JWT", "PGPASSFILE"):
        assert bad not in clean

    strict = sanitize_env({"PATH": "/usr/bin", "RANDOM_LEAK": "abc", **dirty}, allowlist_only=True)
    assert "PATH" in strict
    assert "RANDOM_LEAK" not in strict


def test_ecc_018_sanitize_command_args_blocks_shell_dash_c():
    with pytest.raises(SecurityViolationError):
        sanitize_command_args(["bash", "-c", "id; cat /etc/passwd"])
    with pytest.raises(SecurityViolationError):
        sanitize_command_args(["python", "-c", "print(1)\nimport os"])
    # Safe python -c without shell operators or newlines still works
    ok = sanitize_command_args(["python", "-c", "print('ok')"])
    assert ok == ["python", "-c", "print('ok')"]
