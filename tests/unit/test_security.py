import ast

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
    raw_output = (
        "Error: Authentication failed with token ghp_secret12345678 at host\n"
        "Key: AIzaSyD12345678901234567890123456789012\n"
        "Groq: gsk_123456789012345678901234567890123456789012345678\n"
        "Bearer: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-ID\n"
        "User file: C:\\Users\\nisha\\AppData\\Local\\secret.py\n"
    )
    scrubbed = scrub_sensitive_data(raw_output, sensitive_patterns=["ghp_secret12345678"])
    assert "ghp_secret12345678" not in scrubbed
    assert "AIzaSyD" not in scrubbed
    assert "gsk_12345" not in scrubbed
    assert "eyJhbGciOi" not in scrubbed
    assert "nisha" not in scrubbed
    assert "[REDACTED_GEMINI_KEY]" in scrubbed
    assert "[REDACTED_GROQ_KEY]" in scrubbed
    assert "[REDACTED_TOKEN]" in scrubbed
    assert "[REDACTED_PATH]" in scrubbed


def test_sanitize_env_blocks_database_and_dsn():
    dirty_env = {
        "PATH": "C:\\Windows\\system32",
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
        "SENTRY_DSN": "https://xyz@sentry.io/123",
        "STRIPE_SK": "sk_live_123456",
        "PYTHONPATH": "src",
    }
    clean = sanitize_env(dirty_env)
    assert "PATH" in clean
    assert "PYTHONPATH" in clean
    assert "DATABASE_URL" not in clean
    assert "SENTRY_DSN" not in clean
    assert "STRIPE_SK" not in clean
    assert clean["PYTHONUNBUFFERED"] == "1"
    assert clean["PYTHONDONTWRITEBYTECODE"] == "1"


def test_docstring_injection_sanitization():
    from bugarena.models.bug import SuspectLocation
    from bugarena.synthesizer.test_generator import generate_reproduction_test_code

    suspect = SuspectLocation(
        file_path="src/main.py",
        function_name="calc",
        line_range=(1, 5),
        code_snippet="def calc(): pass",
        reasoning="Test",
        confidence=0.9,
        bug_type="ZeroDivisionError",
    )
    malicious_desc = '"""\nimport os\nos.system("whoami")\n"""'
    test_code = generate_reproduction_test_code(suspect, malicious_desc)
    tree = ast.parse(test_code)
    imported_modules = {
        *(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names),
        *(node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module),
    }
    assert "os" not in imported_modules
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "system"
        for node in ast.walk(tree)
    )
