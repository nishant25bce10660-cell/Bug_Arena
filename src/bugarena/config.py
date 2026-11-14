"""Configuration and environment variable loader for BugArena."""

import os
from pathlib import Path


def load_env_file(dotenv_path: Path | str | None = None) -> None:
    """
    Load environment variables from a .env file into os.environ if not already set.
    Searches explicit path, project root, current working directory, and user config.
    """
    candidates: list[Path] = []
    if dotenv_path:
        candidates.append(Path(dotenv_path).resolve())

    # Candidate 1: BugArena project root directory (d:/MCP server/.env)
    candidates.append(Path(__file__).resolve().parent.parent.parent / ".env")
    # Candidate 2: Current working directory
    candidates.append(Path.cwd() / ".env")
    # Candidate 3: User home .gemini/.env
    candidates.append(Path.home() / ".gemini" / ".env")

    for target in candidates:
        if target.is_file():
            try:
                for line in target.read_text(encoding="utf-8").splitlines():
                    clean_line = line.strip()
                    if not clean_line or clean_line.startswith("#") or "=" not in clean_line:
                        continue
                    key, val = clean_line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
            except OSError:
                continue
