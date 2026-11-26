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
            # Copy base repo files into temp_dir, strictly ignoring secrets and cache dirs
            def ignore_patterns(path: str, names: list[str]) -> set[str]:
                ignored = {
                    ".git",
                    ".venv",
                    "__pycache__",
                    ".pytest_cache",
                    ".ruff_cache",
                    "node_modules",
                    ".env",
                    ".env.local",
                    ".env.production",
                    ".aws",
                    ".ssh",
                }
                return {
                    name
                    for name in names
                    if name in ignored
                    or name.startswith(".env")
                    or name.endswith((".pyc", ".pyo"))
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

    @staticmethod
    def _clean_diff_path(raw_header_rest: str, prefix: str) -> str:
        """Strip optional timestamps/quotes/whitespace and remove a/ or b/ prefix once."""
        # Unified diffs often carry `path\t2026-01-01 ...`
        path_part = raw_header_rest.split("\t", 1)[0].strip()
        if path_part.endswith('"') and path_part.startswith('"'):
            path_part = path_part[1:-1]
        if path_part == "/dev/null":
            return "/dev/null"
        return path_part.removeprefix(prefix)

    def apply_patch(self, sandbox_path: Path, patch_diff: str) -> None:
        """
        Apply a unified diff patch to the target sandbox workspace using a strict hunk state machine.
        """
        if not patch_diff or not patch_diff.strip():
            return

        lines = patch_diff.replace("\r\n", "\n").splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            # File header detection requires paired --- and +++ lines outside hunks
            if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                old_rel = self._clean_diff_path(line[4:], "a/")
                new_rel = self._clean_diff_path(lines[i + 1][4:], "b/")
                i += 2

                is_delete = new_rel == "/dev/null"
                target_rel = old_rel if is_delete else new_rel
                if not target_rel or target_rel == "/dev/null":
                    raise ValueError("Patch header specifies invalid empty or /dev/null target")

                target_file = validate_safe_path(sandbox_path, target_rel)
                if not target_file.exists():
                    original_lines: list[str] = []
                    had_trailing_newline = True
                else:
                    raw_text = target_file.read_text(encoding="utf-8")
                    had_trailing_newline = raw_text.endswith("\n") if raw_text else True
                    original_lines = raw_text.splitlines()

                # Collect hunks via @@ counts until next paired header or EOF
                hunks: list[tuple[str, list[str]]] = []
                while i < len(lines) and not (
                    lines[i].startswith("--- ")
                    and i + 1 < len(lines)
                    and lines[i + 1].startswith("+++ ")
                ):
                    if lines[i].startswith("@@"):
                        hunk_header = lines[i]
                        m = re.match(
                            r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", hunk_header
                        )
                        if not m:
                            raise ValueError(f"Malformed hunk header: {hunk_header!r}")
                        old_count = int(m.group(2)) if m.group(2) is not None else 1
                        new_count = int(m.group(4)) if m.group(4) is not None else 1
                        i += 1
                        old_seen = 0
                        new_seen = 0
                        hunk_lines: list[str] = []
                        while old_seen < old_count or new_seen < new_count:
                            if i >= len(lines):
                                raise ValueError(
                                    f"Truncated hunk in '{target_rel}': expected {old_count}/{new_count}, got {old_seen}/{new_seen}"
                                )
                            hl = lines[i]
                            if hl.startswith("\\ No newline at end of file"):
                                i += 1
                                continue
                            if hl.startswith("-"):
                                old_seen += 1
                                hunk_lines.append(hl)
                            elif hl.startswith("+"):
                                new_seen += 1
                                hunk_lines.append(hl)
                            elif hl.startswith(" ") or hl == "":
                                old_seen += 1
                                new_seen += 1
                                hunk_lines.append(hl if hl else " ")
                            else:
                                raise ValueError(
                                    f"Unexpected line inside hunk for '{target_rel}': {hl!r}"
                                )
                            i += 1
                        hunks.append((hunk_header, hunk_lines))
                    else:
                        i += 1

                if not hunks:
                    raise ValueError(f"File diff for '{target_rel}' contains no valid @@ hunks")

                new_content = self._apply_hunks(original_lines, hunks)
                if is_delete:
                    if target_file.exists() and not new_content:
                        target_file.unlink()
                else:
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    rendered = "\n".join(new_content)
                    if new_content and had_trailing_newline:
                        rendered += "\n"
                    target_file.write_text(rendered, encoding="utf-8")
            else:
                i += 1

    def _apply_hunks(
        self, original_lines: list[str], hunks: list[tuple[str, list[str]]]
    ) -> list[str]:
        """Apply unified diff hunks sequentially with strict context verification."""
        res_lines = list(original_lines)
        offset = 0

        for header, hunk_lines in hunks:
            match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", header)
            if not match:
                raise ValueError(f"Malformed hunk header: {header!r}")

            old_start_1 = int(match.group(1))
            old_count = int(match.group(2)) if match.group(2) is not None else 1

            expected_old: list[str] = []
            new_block: list[str] = []
            for hline in hunk_lines:
                if hline.startswith("-"):
                    expected_old.append(hline[1:])
                elif hline.startswith("+"):
                    new_block.append(hline[1:])
                elif hline.startswith(" ") or not hline:
                    ctx_line = hline[1:] if hline.startswith(" ") else ""
                    expected_old.append(ctx_line)
                    new_block.append(ctx_line)

            # In unified diffs, @@ -0,0 +1,K @@ inserts at 0; @@ -N,0 +N+1,K @@ inserts after N (0-based N)
            start_idx = (old_start_1 + offset) if old_count == 0 else (old_start_1 - 1 + offset)
            end_idx = start_idx + len(expected_old)
            if start_idx < 0 or end_idx > len(res_lines):
                raise ValueError(
                    f"Hunk line range [{start_idx + 1}..{end_idx}] out of bounds for file with {len(res_lines)} lines"
                )

            actual_slice = res_lines[start_idx:end_idx]
            if actual_slice != expected_old:
                raise ValueError(
                    f"Patch context mismatch at line {old_start_1}: expected {expected_old!r}, found {actual_slice!r}"
                )

            res_lines[start_idx:end_idx] = new_block
            offset += len(new_block) - len(expected_old)

        return res_lines
