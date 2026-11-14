"""Sandbox workspace lifecycle management and patch application."""

import re
import shutil
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from bugarena.sandbox.security import validate_safe_path


class EphemeralSandboxManager:
    """Manages isolated ephemeral workspace environments for running tests and patches."""

    def __init__(self, base_repo_path: Path | str):
        self.base_repo_path = Path(base_repo_path).resolve()
        if not self.base_repo_path.exists():
            raise FileNotFoundError(f"Base repository path not found: {self.base_repo_path}")

    @contextmanager
    def create_sandbox(self) -> Generator[Path, None, None]:
        """
        Create an isolated ephemeral copy of the base repository.
        Automatically cleaned up on context exit.
        """
        temp_dir = Path(tempfile.mkdtemp(prefix="bugarena_sandbox_")).resolve()
        try:
            # Copy base repo files into temp_dir
            def ignore_patterns(path: str, names: list[str]) -> set[str]:
                ignored = {
                    ".git",
                    ".venv",
                    "__pycache__",
                    ".pytest_cache",
                    ".ruff_cache",
                    "node_modules",
                }
                return {
                    name for name in names if name in ignored or name.endswith((".pyc", ".pyo"))
                }

            shutil.copytree(
                self.base_repo_path,
                temp_dir,
                dirs_exist_ok=True,
                ignore=ignore_patterns,
            )
            yield temp_dir
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def apply_patch(self, sandbox_path: Path, patch_diff: str) -> None:
        """
        Apply a unified diff patch to the target sandbox workspace.
        """
        if not patch_diff or not patch_diff.strip():
            return

        # Simple unified diff parser & applier
        # Format:
        # --- a/path
        # +++ b/path
        # @@ -start,count +start,count @@
        lines = patch_diff.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith(("--- a/", "--- ")):
                # Next line should be +++ b/path
                target_rel = None
                if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                    target_rel = lines[i + 1][4:].strip()
                    target_rel = target_rel.removeprefix("b/")
                    i += 2
                else:
                    i += 1
                    continue

                if not target_rel:
                    continue

                target_file = validate_safe_path(sandbox_path, target_rel)
                if not target_file.exists():
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    original_lines: list[str] = []
                else:
                    original_lines = target_file.read_text(encoding="utf-8").splitlines()

                # Process hunks for this file
                hunks = []
                while i < len(lines) and not (
                    lines[i].startswith("--- a/") or lines[i].startswith("--- ")
                ):
                    if lines[i].startswith("@@"):
                        hunk_header = lines[i]
                        i += 1
                        hunk_lines = []
                        while (
                            i < len(lines)
                            and not lines[i].startswith("@@")
                            and not lines[i].startswith("--- ")
                        ):
                            hunk_lines.append(lines[i])
                            i += 1
                        hunks.append((hunk_header, hunk_lines))
                    else:
                        i += 1

                # Apply hunks to original_lines
                new_content = self._apply_hunks(original_lines, hunks)
                target_file.write_text(
                    "\n".join(new_content) + ("\n" if new_content else ""), encoding="utf-8"
                )
            else:
                i += 1

    def _apply_hunks(
        self, original_lines: list[str], hunks: list[tuple[str, list[str]]]
    ) -> list[str]:
        """Apply unified diff hunks sequentially."""
        res_lines = list(original_lines)
        offset = 0

        for header, hunk_lines in hunks:
            # Parse header @@ -old_start,old_len +new_start,new_len @@
            match = re.search(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", header)
            if not match:
                continue

            old_start = int(match.group(1)) - 1  # 0-indexed
            old_count = int(match.group(2)) if match.group(2) is not None else 1

            # Extract old block and new block
            removals = 0
            additions = []
            for hline in hunk_lines:
                if hline.startswith("-"):
                    removals += 1
                elif hline.startswith("+"):
                    additions.append(hline[1:])
                elif hline.startswith(" ") or not hline:
                    additions.append(hline.removeprefix(" "))

            # Replace block
            actual_start = max(0, old_start + offset)
            actual_end = min(len(res_lines), actual_start + old_count)
            res_lines[actual_start:actual_end] = additions
            offset += len(additions) - old_count

        return res_lines
