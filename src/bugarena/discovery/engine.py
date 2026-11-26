"""Bug discovery engine tying together log parsing, AST slicing, and fault ranking."""

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


class BugDiscoveryEngine:
    """Discovers and localizes bugs in a repository using error logs and AST analysis."""

    def __init__(self, repo_path: Path | str):
        self.repo_path = Path(repo_path).resolve()
        if not self.repo_path.exists():
            raise FileNotFoundError(f"Repository path does not exist: {self.repo_path}")

    def discover_from_trace(
        self,
        error_log: str,
        hint: str | None = None,
        max_candidates: int = 3,
    ) -> BugSpec:
        """
        Analyze an error log/traceback and produce a structured BugSpec with suspects.
        """
        traces = parse_python_traceback(error_log)
        suspects: list[SuspectLocation] = []

        # Process frames in reverse order (closest to point of crash first)
        for idx, trace in enumerate(reversed(traces)):
            # Try to resolve file relative to repo_path with strict containment
            resolved_file = None
            try:
                candidate = Path(trace.file_path)
                if not candidate.is_absolute():
                    candidate_path = (self.repo_path / candidate).resolve()
                else:
                    candidate_path = candidate.resolve()

                if _is_safe_source_path(candidate, candidate_path, self.repo_path):
                    resolved_file = candidate_path
                else:
                    # Search by file name within repo only, excluding non-source/.env/.venv
                    for match in self.repo_path.rglob(Path(trace.file_path).name):
                        m_res = match.resolve()
                        if _is_safe_source_path(match, m_res, self.repo_path):
                            resolved_file = m_res
                            break
            except (OSError, ValueError):
                continue

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

            # Fault localization heuristic: bottom frame gets highest confidence
            confidence = max(0.5, 0.95 - (idx * 0.15))
            bug_type = trace.error_message.split(":", 1)[0].strip() or "RuntimeError"

            reasoning = scrub_sensitive_data(
                (
                    f"Stack frame {len(traces) - idx} crashed at line {trace.line_number} "
                    f"in function '{trace.function_name}'. {trace.error_message}"
                    + (f" (Hint correlation: {hint})" if hint else "")
                ),
                base_dir=self.repo_path,
            )

            line_range = (
                ast_slice["line_range"] if ast_slice else (trace.line_number, trace.line_number)
            )
            raw_snippet = ast_slice["code_snippet"] if ast_slice else trace.code
            snippet = scrub_sensitive_data(raw_snippet, base_dir=self.repo_path)

            suspect = SuspectLocation(
                file_path=rel_path,
                function_name=ast_slice["function_name"] if ast_slice else trace.function_name,
                line_range=line_range,
                confidence=round(confidence, 2),
                bug_type=bug_type,
                reasoning=reasoning,
                code_snippet=snippet,
            )
            suspects.append(suspect)

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
