"""Regression test for ECC-041 and ECC-029 (BA-019): validate_safe_path & scrub_sensitive_data."""

import os
from unittest.mock import patch

import pytest

from bugarena.sandbox.runner import run_sandboxed_command
from bugarena.sandbox.security import (
    SecurityViolationError,
    scrub_sensitive_data,
    validate_safe_path,
)


def test_ecc_041_validate_safe_path_rejects_empty_dot_and_nul(tmp_path):
    for bad in ("", ".", "   ", "a.py\x00.txt"):
        with pytest.raises(SecurityViolationError):
            validate_safe_path(tmp_path, bad)


def test_ecc_029_scrub_sensitive_data_order_slashes_and_tokens():
    # Base dir must be scrubbed BEFORE Windows home regex; handle mixed slashes & case
    s1 = scrub_sensitive_data(
        r"C:\Users\alice\AppData\Local\Temp\box\a.py",
        base_dir=r"C:\Users\alice\AppData\Local\Temp\box",
    )
    assert s1.replace("\\", "/") == "[WORKSPACE]/a.py"

    s2 = scrub_sensitive_data("C:/Users/alice/work/a.py")
    assert "alice" not in s2 and s2 == "[REDACTED_PATH]/work/a.py"

    s3 = scrub_sensitive_data("d:/MCP server/src/a.py", base_dir="d:\\MCP server")
    assert s3 == "[WORKSPACE]/src/a.py"

    tokens = "xoxb-1234567890-abcdef glpat-abcdefghijklmnop hf_1234567890abcdefghij AIzaShort123456789012"
    scrubbed = scrub_sensitive_data(tokens)
    for secret in ("xoxb-", "glpat-", "hf_1234", "AIzaShort"):
        assert secret not in scrubbed


def test_ecc_029_runner_error_and_env_scrubbing(tmp_path):
    with patch.dict(os.environ, {"STRIPE_SK": "sk_test_custom_secret_val_123"}):
        out = run_sandboxed_command(
            tmp_path,
            ["nonexistent_binary_for_test_xyz"],
        )
        assert out.exit_code != 0
        assert str(tmp_path) not in out.stderr
