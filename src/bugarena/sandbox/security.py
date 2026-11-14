"""Security policies, path traversal validation, and sanitization utilities."""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path


class SecurityViolationError(Exception):
    """Raised when an operation violates security policies."""


BLOCKED_ENV_SUBSTRINGS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "AUTH",
    "PRIVATE",
    "SIGNATURE",
    "URL",
    "DSN",
    "CONNECTION",
    "PASS",
)

BLOCKED_ENV_EXACT = {
    "DATABASE_URL",
    "SENTRY_DSN",
    "STRIPE_SK",
    "MONGO_URI",
    "REDIS_URL",
}

DANGEROUS_SHELL_PATTERNS = re.compile(r"[;&|`$><]")


def validate_safe_path(base_dir: Path | str, target_path: str) -> Path:
    """
    Validate that target_path resides safely within base_dir.

    Prevents path traversal attacks (e.g. '../', absolute path escapes).
    """
    base_resolved = Path(base_dir).resolve()

    # If target_path is absolute, check directly, otherwise join
    target_p = Path(target_path)
    if not target_p.is_absolute():
        candidate = (base_resolved / target_p).resolve()
    else:
        candidate = target_p.resolve()

    try:
        candidate.relative_to(base_resolved)
    except ValueError as e:
        raise SecurityViolationError(
            f"Path traversal detected: '{target_path}' escapes base directory '{base_resolved}'"
        ) from e

    return candidate


def sanitize_env(base_env: Mapping[str, str]) -> dict[str, str]:
    """
    Create a sanitized copy of environment variables, stripping secrets, URLs, and tokens.
    """
    clean_env: dict[str, str] = {}
    for key, val in base_env.items():
        key_upper = key.upper()
        if key_upper in BLOCKED_ENV_EXACT or any(blocked in key_upper for blocked in BLOCKED_ENV_SUBSTRINGS):
            continue
        clean_env[key] = val
    clean_env["PYTHONUNBUFFERED"] = "1"
    clean_env["PYTHONDONTWRITEBYTECODE"] = "1"
    return clean_env


def sanitize_command_args(args: Sequence[str]) -> list[str]:
    """
    Validate and sanitize command argument vector.

    Ensures no command injection metacharacters are embedded in arguments,
    while permitting valid Python code arguments following '-c'.
    """
    if not args:
        raise SecurityViolationError("Empty command argument vector is disallowed.")

    sanitized: list[str] = []
    for i, arg in enumerate(args):
        # If argument immediately follows '-c', treat as code payload
        is_code_arg = i > 0 and args[i - 1] == "-c"

        if not is_code_arg and DANGEROUS_SHELL_PATTERNS.search(arg):
            raise SecurityViolationError(
                f"Dangerous shell operator or metacharacter detected in command arg: '{arg}'"
            )
        sanitized.append(arg)

    return sanitized


def scrub_sensitive_data(
    text: str,
    sensitive_patterns: Sequence[str] | None = None,
    base_dir: str | Path | None = None,
) -> str:
    """
    Scrub sensitive tokens, API keys, URLs, and absolute paths from output or error logs.
    """
    if not text:
        return ""

    scrubbed = text
    if sensitive_patterns:
        for pat in sensitive_patterns:
            if pat and len(pat) > 3:
                scrubbed = scrubbed.replace(pat, "[REDACTED]")

    # Redact provider API keys
    scrubbed = re.sub(r"gh[pousr]_[A-Za-z0-9_]{16,}", "[REDACTED_GITHUB_TOKEN]", scrubbed)
    scrubbed = re.sub(r"sk-[A-Za-z0-9_-]{20,}", "[REDACTED_API_KEY]", scrubbed)
    scrubbed = re.sub(r"AIza[0-9A-Za-z-_]{35}", "[REDACTED_GEMINI_KEY]", scrubbed)
    scrubbed = re.sub(r"gsk_[A-Za-z0-9]{48,}", "[REDACTED_GROQ_KEY]", scrubbed)
    scrubbed = re.sub(r"AKIA[0-9A-Z]{16}", "[REDACTED_AWS_KEY]", scrubbed)
    scrubbed = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.~+/]+=*", "Bearer [REDACTED_TOKEN]", scrubbed, flags=re.IGNORECASE)

    # Redact absolute paths exposing host user or environment
    scrubbed = re.sub(r"[a-zA-Z]:\\[Uu]sers\\[^\/\s\\]+", "[REDACTED_PATH]", scrubbed)
    scrubbed = re.sub(r"/(?:home|Users)/[^/\s]+", "[REDACTED_PATH]", scrubbed)
    if base_dir:
        scrubbed = scrubbed.replace(str(base_dir), "[WORKSPACE]")

    return scrubbed
