"""Configuration and environment variable loader for BugArena."""

import os
from pathlib import Path


def _read_env_text(target: Path) -> str | None:
    """Read a .env file with utf-8-sig -> utf-16 fallback; return None on failure."""
    for enc in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            return target.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
        except OSError:
            return None
    return None


def _parse_env_value(raw_val: str) -> str:
    """Parse matching quotes and inline comments (whitespace + #) for unquoted values."""
    val = raw_val.strip()
    if not val:
        return ""
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        return val[1:-1]
    if val[0] in ("'", '"'):
        quote = val[0]
        end_idx = val.find(quote, 1)
        if end_idx != -1:
            return val[1:end_idx]
    # Unquoted value: strip whitespace-prefixed inline comment (# preceded by whitespace)
    for i, ch in enumerate(val):
        if ch == "#" and i > 0 and val[i - 1].isspace():
            return val[:i].strip()
    return val


def load_env_file(dotenv_path: Path | str | None = None) -> None:
    """
    Load environment variables from a .env file into os.environ if not already set.

    When dotenv_path is explicitly provided, loads ONLY that file. Otherwise checks
    BugArena's package root `.env` and `~/.gemini/.env` (never untrusted CWD `.env`).
    """
    if dotenv_path is not None:
        candidates = [Path(dotenv_path).resolve()]
    else:
        candidates = [
            Path(__file__).resolve().parent.parent.parent / ".env",
            Path.home() / ".gemini" / ".env",
        ]

    for target in candidates:
        if not target.is_file():
            continue
        text = _read_env_text(target)
        if not text:
            continue
        for line in text.splitlines():
            clean_line = line.strip()
            if not clean_line or clean_line.startswith("#") or "=" not in clean_line:
                continue
            if clean_line.startswith("export "):
                clean_line = clean_line[7:].lstrip()
            key, raw_val = clean_line.split("=", 1)
            key = key.strip()
            val = _parse_env_value(raw_val)
            if key and val and (not os.environ.get(key)):
                os.environ[key] = val
