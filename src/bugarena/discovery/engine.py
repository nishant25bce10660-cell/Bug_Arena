"""Bug discovery engine tying together log parsing, AST slicing, and fault ranking."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from bugarena.discovery.ast_analyzer import locate_faulty_ast_slice
from bugarena.discovery.log_parser import parse_python_traceback
from bugarena.models.bug import BugSpec, FaultTrace, SuspectLocation
from bugarena.sandbox.security import scrub_sensitive_data

ALLOWED_SOURCE_EXTENSIONS = frozenset({".py", ".pyi"})
EXCLUDED_DIR_PARTS = frozenset({
    ".git",
    ".venv",
    "venv",
    ".ssh",
    ".aws",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
    ".bugarena",
})


def _is_safe_source_path(rel_or_abs: Path, resolved: Path, repo_root: Path) -> bool:
    """Return True only when resolved is a regular source file inside repo_root, excluding .env/secrets."""
    if not resolved.is_file() or not resolved.is_relative_to(repo_root):
        return False
    if resolved.suffix.lower() not in ALLOWED_SOURCE_EXTENSIONS:
        return False
    rel_parts = resolved.relative_to(repo_root).parts
    orig_parts = rel_or_abs.parts
    for part in (*rel_parts, *orig_parts):
        if part.startswith(".env") or part in EXCLUDED_DIR_PARTS:
            return False
    return True


def _build_repo_source_index(repo_root: Path) -> dict[str, list[tuple[str, Path]]]:
    """Walk repo_root once pruning excluded directories and map filename -> [(rel_posix, resolved)]."""
    by_name: dict[str, list[tuple[str, Path]]] = {}
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = sorted(
            d for d in dirs if not d.startswith(".env") and d not in EXCLUDED_DIR_PARTS
        )
        root_p = Path(root)
        for fname in sorted(files):
            if fname.startswith(".env"):
                continue
            full_p = root_p / fname
            if full_p.suffix.lower() not in ALLOWED_SOURCE_EXTENSIONS:
                continue
            try:
                resolved = full_p.resolve()
                if not _is_safe_source_path(full_p, resolved, repo_root):
                    continue
                rel_posix = resolved.relative_to(repo_root).as_posix()
                by_name.setdefault(fname, []).append((rel_posix, resolved))
            except (OSError, ValueError):
                continue
    return by_name


def _suffix_overlap_score(frame_parts: tuple[str, ...], repo_rel_parts: tuple[str, ...]) -> int:
    score = 0
    for f_seg, r_seg in zip(reversed(frame_parts), reversed(repo_rel_parts), strict=False):
        if f_seg.lower() != r_seg.lower():
            break
        score += 1
    return score


class BugDiscoveryEngine:
    """Discovers and localizes bugs in a repository using error logs and AST analysis."""

    def __init__(self, repo_path: Path | str):
        self.repo_path = Path(repo_path).resolve()
        if not self.repo_path.exists():
            raise FileNotFoundError(f"Repository path does not exist: {self.repo_path}")
        self._source_index: dict[str, list[tuple[str, Path]]] | None = None

    def _get_source_index(self) -> dict[str, list[tuple[str, Path]]]:
        if self._source_index is None:
            self._source_index = _build_repo_source_index(self.repo_path)
        return self._source_index

    def _resolve_frame_file(self, raw_frame_path: str) -> tuple[Path | None, float]:
        """Resolve frame path to safe repo file with match-quality weight in (0, 1]."""
        try:
            candidate = Path(raw_frame_path)
            cand_resolved = (
                (self.repo_path / candidate).resolve()
                if not candidate.is_absolute()
                else candidate.resolve()
            )
            if _is_safe_source_path(candidate, cand_resolved, self.repo_path):
                return cand_resolved, 1.0
        except (OSError, ValueError):
            pass

        # Normalized suffix match against indexed repo files (prune excluded dirs)
        norm_parts = tuple(
            p for p in raw_frame_path.replace("\\", "/").split("/") if p and p != "."
        )
        if any(p.startswith(".env") or p in EXCLUDED_DIR_PARTS for p in norm_parts):
            return None, 0.0
        if not norm_parts:
            return None, 0.0

        index = self._get_source_index()
        candidates = index.get(norm_parts[-1], [])
        if not candidates:
            return None, 0.0

        best_overlap = 0
        best_path: Path | None = None
        for rel_posix, resolved in candidates:
            overlap = _suffix_overlap_score(norm_parts, tuple(rel_posix.split("/")))
            if overlap > best_overlap:
                best_overlap = overlap
                best_path = resolved
        if best_path is None:
            return None, 0.0
        quality = 0.9 if best_overlap >= 2 else 0.72
        return best_path, quality

    def discover_from_trace(
        self,
        error_log: str,
        hint: str | None = None,
        max_candidates: int = 3,
    ) -> BugSpec:
        """
        Analyze an error log/traceback and produce a structured BugSpec with deduplicated suspects.
        """
        traces = parse_python_traceback(error_log)
        suspects: list[SuspectLocation] = []
        seen_keys: set[tuple[str, str, tuple[int, int]]] = set()

        # Process frames in reverse order (closest to point of crash first)
        for idx, trace in enumerate(reversed(traces)):
            resolved_file, match_quality = self._resolve_frame_file(trace.file_path)
            if not resolved_file or not resolved_file.is_file():
                continue

            try:
                rel_path = resolved_file.relative_to(self.repo_path).as_posix()
            except ValueError:
                rel_path = resolved_file.name

            content = resolved_file.read_text(encoding="utf-8", errors="replace")
            ast_slice = locate_faulty_ast_slice(
                content, trace.line_number, function_name=trace.function_name
            )

            func_name = ast_slice["function_name"] if ast_slice else trace.function_name
            line_range = (
                ast_slice["line_range"] if ast_slice else (trace.line_number, trace.line_number)
            )
            dedupe_key = (rel_path, func_name, line_range)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            raw_conf = max(0.5, 0.95 - (idx * 0.15)) * match_quality
            confidence = round(max(0.4, min(1.0, raw_conf)), 2)
            bug_type = trace.error_message.split(":", 1)[0].strip() or "RuntimeError"

            reasoning = scrub_sensitive_data(
                (
                    f"Stack frame {len(traces) - idx} crashed at line {trace.line_number} "
                    f"in function '{trace.function_name}'. {trace.error_message}"
                    + (f" (Hint correlation: {hint})" if hint else "")
                ),
                base_dir=self.repo_path,
            )
            raw_snippet = ast_slice["code_snippet"] if ast_slice else trace.code
            snippet = scrub_sensitive_data(raw_snippet, base_dir=self.repo_path)

            suspects.append(
                SuspectLocation(
                    file_path=rel_path,
                    function_name=func_name,
                    line_range=line_range,
                    confidence=confidence,
                    bug_type=bug_type,
                    reasoning=reasoning,
                    code_snippet=snippet,
                )
            )

            if len(suspects) >= max_candidates:
                break

        scrubbed_traces = [
            FaultTrace(
                file_path=t.file_path,
                line_number=t.line_number,
                function_name=t.function_name,
                code=scrub_sensitive_data(t.code, base_dir=self.repo_path),
                error_message=scrub_sensitive_data(t.error_message, base_dir=self.repo_path),
            )
            for t in traces
        ]
        bug_id = f"bug_{uuid.uuid4().hex[:8]}"
        return BugSpec(
            bug_id=bug_id,
            repo_path=str(self.repo_path),
            error_log=scrub_sensitive_data(error_log, base_dir=self.repo_path),
            hint=hint,
            suspects=suspects,
            traces=scrubbed_traces,
        )
