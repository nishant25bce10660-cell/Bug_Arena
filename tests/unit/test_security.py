import pytest

from bugarena.sandbox.security import (
    SecurityViolationError,
    sanitize_command_args,
    sanitize_env,
    scrub_sensitive_data,
    validate_safe_path,
)


def test_validate_safe_path_valid(tmp_path):
    safe_file = tmp_path / "src" / "test.py"
    safe_file.parent.mkdir(parents=True)
    safe_file.write_text("print('hello')")

    resolved = validate_safe_path(tmp_path, "src/test.py")
    assert resolved == safe_file.resolve()


def test_validate_safe_path_traversal_attack(tmp_path):
    with pytest.raises(SecurityViolationError, match="Path traversal detected"):
        validate_safe_path(tmp_path, "../../etc/passwd")

    with pytest.raises(SecurityViolationError, match="Path traversal detected"):
        validate_safe_path(tmp_path, "src/../../outside.txt")


def test_sanitize_env():
    dirty_env = {
        "PATH": "C:\\Windows\\system32",
        "GITHUB_TOKEN": "ghp_1234567890abcdef",
        "OPENAI_API_KEY": "sk-proj-xyz",
        "AWS_SECRET_ACCESS_KEY": "supersecret",
        "PYTHONPATH": "src",
        "SAFE_VAR": "clean_value",
    }
    clean = sanitize_env(dirty_env)
    assert "PATH" in clean
    assert "PYTHONPATH" in clean
    assert "SAFE_VAR" in clean
    assert "GITHUB_TOKEN" not in clean
    assert "OPENAI_API_KEY" not in clean
    assert "AWS_SECRET_ACCESS_KEY" not in clean


def test_sanitize_command_args():
    # Valid arg vectors
    valid = ["pytest", "-q", "tests/test_calc.py"]
    assert sanitize_command_args(valid) == valid

    # Disallow empty commands
    with pytest.raises(SecurityViolationError, match="Empty command"):
        sanitize_command_args([])

    # Disallow command chaining attempts in single arguments
    with pytest.raises(SecurityViolationError, match="Dangerous shell operator"):
        sanitize_command_args(["pytest", "tests; rm -rf /"])

    with pytest.raises(SecurityViolationError, match="Dangerous shell operator"):
        sanitize_command_args(["python", "app.py && calc.exe"])


def test_scrub_sensitive_data():
    raw_output = "Error: Authentication failed with token ghp_secret12345678 at host"
    scrubbed = scrub_sensitive_data(raw_output, sensitive_patterns=["ghp_secret12345678"])
    assert "ghp_secret12345678" not in scrubbed
    assert "[REDACTED]" in scrubbed
