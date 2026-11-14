"""Configuration and environment variable loader for BugArena."""

import os
from pathlib import Path


def load_env_file(dotenv_path: Path | str | None = None) -> None:
    """
    Load environment variables from a .env file into os.environ if not already set.
    """
    if dotenv_path:
        target = Path(dotenv_path).resolve()
    else:
        # Default: check project root directory
        target = Path(__file__).resolve().parent.parent.parent / ".env"

    if target.is_file():
        for line in target.read_text(encoding="utf-8").splitlines():
            clean_line = line.strip()
            if not clean_line or clean_line.startswith("#") or "=" not in clean_line:
                continue
            key, val = clean_line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = val
