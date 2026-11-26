"""Security policies, path traversal validation, and sanitization utilities."""

import os
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
    "PROXY",
    "STARTUP",
    "PRELOAD",
    "COOKIE",
    "SESSION",
)

BLOCKED_ENV_EXACT = {
    "DATABASE_URL",
    "SENTRY_DSN",
    "STRIPE_SK",
    "MONGO_URI",
    "REDIS_URL",
    "MYSQL_PWD",
    "PGPASSFILE",
    "PYTHONSTARTUP",
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "DYLD_INSERT_LIBRARIES",
    "GH_PAT",
    "CI_JOB_JWT",
    "NPM_TOKEN",
}

ENV_ALLOWLIST = frozenset({
    "PATH",
    "SYSTEMROOT",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "WINDIR",
    "HOME",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
    "TERM",
    "PYTHONPATH",
    "PYTHONHOME",
    "VIRTUAL_ENV",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PROCESSOR_ARCHITECTURE",
})

DANGEROUS_SHELL_PATTERNS = re.compile(r"[;&|`$><]")


def validate_pytest_target(target_path: str) -> str:
    """Reject empty, option-like ('-...'), or NUL pytest target paths."""
    if not target_path or not target_path.strip() or "\x00" in target_path:
        raise SecurityViolationError(f"Invalid pytest target path: {target_path!r}")
    if target_path.lstrip().startswith("-"):
        raise SecurityViolationError(
            f"Option injection rejected in pytest target path: {target_path!r}"
        )
    return target_path


def validate_safe_path(
    base_dir: Path | str, target_path: str, *, allow_root: bool = False
) -> Path:
    """
    Validate that target_path resides safely within base_dir.

    Prevents path traversal attacks (e.g. '../', absolute path escapes),
    empty/dot root self-targets, and NUL-byte smuggling.
    """
    if not target_path or not target_path.strip() or "\x00" in target_path:
        raise SecurityViolationError(f"Invalid target path: {target_path!r}")

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

    if not allow_root and candidate == base_resolved:
        raise SecurityViolationError(
            f"Target path resolves to base directory itself: '{target_path}'"
        )

    return candidate


def sanitize_env(base_env: Mapping[str, str], *, allowlist_only: bool = False) -> dict[str, str]:
    """
    Create a sanitized copy of environment variables.
    When allowlist_only=True, retains only safe minimal OS/runtime variables from ENV_ALLOWLIST.
    """
    clean_env: dict[str, str] = {}
    for key, val in base_env.items():
        key_upper = key.upper()
        if allowlist_only and key_upper not in ENV_ALLOWLIST:
            continue
        if (
            key_upper in BLOCKED_ENV_EXACT
            or key_upper.endswith(("_PAT", "_JWT"))
            or any(blocked in key_upper for blocked in BLOCKED_ENV_SUBSTRINGS)
        ):
            continue
        clean_env[key] = val
    clean_env["PYTHONUNBUFFERED"] = "1"
    clean_env["PYTHONDONTWRITEBYTECODE"] = "1"
    return clean_env


def sanitize_command_args(args: Sequence[str]) -> list[str]:
    """
    Validate and sanitize command argument vector.

    Blocks shell operators/newlines across arguments, permitting inline `-c` code payloads
    strictly for approved Python executables without embedded newlines/NUL bytes.
    """
    if not args:
        raise SecurityViolationError("Empty command argument vector is disallowed.")

    exe_stem = Path(args[0]).stem.lower()
    is_python_exe = exe_stem.startswith("python") or exe_stem in {"py", "pypy3"}

    sanitized: list[str] = []
    for i, arg in enumerate(args):
        if "\x00" in arg or "\n" in arg or "\r" in arg:
            raise SecurityViolationError(
                f"Disallowed control character or newline in command arg at index {i}"
            )
        is_python_code_arg = is_python_exe and i > 0 and args[i - 1] == "-c"
        if not is_python_code_arg and DANGEROUS_SHELL_PATTERNS.search(arg):
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

    # Redact base_dir variants BEFORE generic home-directory regexes
    if base_dir:
        raw_base = str(base_dir)
        base_p = Path(raw_base)
        candidates = {
            raw_base,
            raw_base.replace("\\", "/"),
            raw_base.replace("/", "\\"),
            base_p.as_posix(),
            str(base_p.resolve()),
            base_p.resolve().as_posix(),
        }
        flags = re.IGNORECASE if os.name == "nt" else 0
        for variant in sorted((c for c in candidates if c), key=len, reverse=True):
            scrubbed = re.sub(re.escape(variant), "[WORKSPACE]", scrubbed, flags=flags)

    # Redact provider API keys and tokens
    scrubbed = re.sub(r"gh[pousr]_[A-Za-z0-9_]{16,}", "[REDACTED_GITHUB_TOKEN]", scrubbed)
    scrubbed = re.sub(r"glpat-[A-Za-z0-9_-]{12,}", "[REDACTED_GITLAB_TOKEN]", scrubbed)
    scrubbed = re.sub(r"xox[baprs]-[A-Za-z0-9-]{10,}", "[REDACTED_SLACK_TOKEN]", scrubbed)
    scrubbed = re.sub(r"hf_[A-Za-z0-9]{16,}", "[REDACTED_HF_TOKEN]", scrubbed)
    scrubbed = re.sub(r"sk-[A-Za-z0-9_-]{20,}", "[REDACTED_API_KEY]", scrubbed)
    scrubbed = re.sub(r"AIza[0-9A-Za-z_-]{16,}", "[REDACTED_GEMINI_KEY]", scrubbed)
    scrubbed = re.sub(r"gsk_[A-Za-z0-9]{48,}", "[REDACTED_GROQ_KEY]", scrubbed)
    scrubbed = re.sub(r"AKIA[0-9A-Z]{16}", "[REDACTED_AWS_KEY]", scrubbed)
    scrubbed = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.~+/]+=*", "Bearer [REDACTED_TOKEN]", scrubbed, flags=re.IGNORECASE)

    # Redact remaining absolute home paths (both '\' and '/' on Windows/POSIX)
    scrubbed = re.sub(r"[a-zA-Z]:[/\\][Uu]sers[/\\][^/\s\\]+", "[REDACTED_PATH]", scrubbed)
    scrubbed = re.sub(r"/(?:home|Users)/[^/\s]+", "[REDACTED_PATH]", scrubbed)

    return scrubbed
