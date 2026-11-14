"""Bug discovery engine tying together log parsing, AST slicing, and fault ranking."""

import uuid
from pathlib import Path

from bugarena.discovery.ast_analyzer import locate_faulty_ast_slice
from bugarena.discovery.log_parser import parse_python_traceback
from bugarena.models.bug import BugSpec, SuspectLocation


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

                if candidate_path.is_file() and candidate_path.is_relative_to(self.repo_path):
                    resolved_file = candidate_path
                else:
                    # Search by file name within repo only
                    matches = list(self.repo_path.rglob(Path(trace.file_path).name))
                    if (
                        matches
                        and matches[0].is_file()
                        and matches[0].resolve().is_relative_to(self.repo_path)
                    ):
                        resolved_file = matches[0].resolve()
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

            reasoning = (
                f"Stack frame {len(traces) - idx} crashed at line {trace.line_number} "
                f"in function '{trace.function_name}'. {trace.error_message}"
            )
            if hint:
                reasoning += f" (Hint correlation: {hint})"

            line_range = (
                ast_slice["line_range"] if ast_slice else (trace.line_number, trace.line_number)
            )
            snippet = ast_slice["code_snippet"] if ast_slice else trace.code

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

        bug_id = f"bug_{uuid.uuid4().hex[:8]}"
        return BugSpec(
            bug_id=bug_id,
            repo_path=str(self.repo_path),
            error_log=error_log,
            hint=hint,
            suspects=suspects,
            traces=traces,
        )
