"""Read-only grounding tools available to audit subagents, gated by allowed_tools."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from bugarena.audit.probes import run_isolated_probe
from bugarena.sandbox.security import scrub_sensitive_data

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    ".bugarena",
    "bug-report ECC",
    "bug_report",
}


def _iter_source_files(repo: Path, suffix: str | None = ".py") -> list[Path]:
    files: list[Path] = []
    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(repo).parts
        if any(part in EXCLUDED_DIRS or part.startswith(".env") for part in rel_parts):
            continue
        if suffix is None or path.suffix == suffix:
            files.append(path)
    return sorted(files)


def tool_git_ls(repo_path: Path | str) -> list[str]:
    """List repository files (tracked via git ls-files, falling back to safe walk)."""
    repo = Path(repo_path).resolve()
    try:
        res = subprocess.run(
            ["git", "ls-files"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return [
                line.strip()
                for line in res.stdout.splitlines()
                if line.strip() and not line.strip().startswith((".bugarena/", "bug-report", "bug_report"))
            ]
    except (OSError, subprocess.SubprocessError):
        pass
    return [p.relative_to(repo).as_posix() for p in _iter_source_files(repo, suffix=None)]


def tool_ast_scan(repo_path: Path | str, rel_paths: list[str] | None = None) -> dict[str, Any]:
    """Scan Python files via AST for classes, functions, swallowed excepts, and unsafe calls."""
    repo = Path(repo_path).resolve()
    targets = (
        [repo / p for p in rel_paths if (repo / p).is_file()]
        if rel_paths
        else _iter_source_files(repo, suffix=".py")
    )
    results: list[dict[str, Any]] = []
    for path in targets:
        rel = path.relative_to(repo).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError as exc:
            results.append({"file": rel, "syntax_error": f"line {exc.lineno}: {exc.msg}"})
            continue

        funcs: list[dict[str, Any]] = []
        swallowed_excepts: list[int] = []
        subprocess_calls: list[int] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append(
                    {
                        "name": node.name,
                        "async": isinstance(node, ast.AsyncFunctionDef),
                        "lineno": node.lineno,
                        "end_lineno": getattr(node, "end_lineno", node.lineno),
                    }
                )
            elif isinstance(node, ast.ExceptHandler):
                if len(node.body) == 1 and isinstance(
                    node.body[0], (ast.Pass, ast.Continue, ast.Return)
                ):
                    swallowed_excepts.append(node.lineno)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("Popen", "run", "call", "check_output")
            ):
                subprocess_calls.append(node.lineno)

        results.append(
            {
                "file": rel,
                "lines": len(text.splitlines()),
                "functions": funcs,
                "swallowed_except_lines": swallowed_excepts,
                "subprocess_lines": subprocess_calls,
            }
        )
    return {"files_scanned": len(results), "results": results}


def tool_ruff_json(repo_path: Path | str, targets: tuple[str, ...] = ("src", "tests", "scripts")) -> dict[str, Any]:
    """Run ruff check read-only with JSON output."""
    repo = Path(repo_path).resolve()
    existing_targets = [t for t in targets if (repo / t).exists()]
    if not existing_targets:
        existing_targets = ["."]
    ruff_bin = str(Path(sys.executable).parent / ("ruff.exe" if sys.platform == "win32" else "ruff"))
    cmd = [ruff_bin if Path(ruff_bin).exists() else "ruff", "check", "--output-format=json", *existing_targets]
    try:
        res = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, timeout=30.0, check=False)
        issues = json.loads(res.stdout) if res.stdout.strip() else []
        return {"exit_code": res.returncode, "issue_count": len(issues), "issues": issues[:100]}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"exit_code": -1, "issue_count": -1, "error": str(exc), "issues": []}


def tool_radon_cc(repo_path: Path | str, target: str = "src") -> dict[str, Any]:
    """Compute cyclomatic complexity metrics across src/ using radon."""
    repo = Path(repo_path).resolve()
    target_dir = repo / target if (repo / target).exists() else repo
    try:
        from radon.complexity import cc_visit

        blocks: list[dict[str, Any]] = []
        for py_file in _iter_source_files(target_dir, suffix=".py"):
            rel = py_file.relative_to(repo).as_posix()
            content = py_file.read_text(encoding="utf-8", errors="replace")
            for block in cc_visit(content):
                blocks.append(
                    {
                        "file": rel,
                        "name": block.name,
                        "lineno": block.lineno,
                        "complexity": block.complexity,
                    }
                )
        blocks.sort(key=lambda b: b["complexity"], reverse=True)
        avg = round(sum(b["complexity"] for b in blocks) / len(blocks), 3) if blocks else 0.0
        return {"blocks_analyzed": len(blocks), "average_cc": avg, "top_blocks": blocks[:20]}
    except (ImportError, OSError, SyntaxError, ValueError) as exc:
        return {"blocks_analyzed": 0, "error": str(exc), "top_blocks": []}


def tool_grep(
    repo_path: Path | str, pattern: str, *, path_prefix: str = ""
) -> list[dict[str, Any]]:
    """Safe regex search across repository files (excludes .venv, .git, .env*)."""
    repo = Path(repo_path).resolve()
    regex = re.compile(pattern)
    matches: list[dict[str, Any]] = []
    for path in _iter_source_files(repo, suffix=None):
        rel = path.relative_to(repo).as_posix()
        if path_prefix and not rel.startswith(path_prefix):
            continue
        if path.suffix in {".png", ".jpg", ".whl", ".pyc", ".zip"}:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if regex.search(line):
                matches.append({"file": rel, "line": lineno, "text": scrub_sensitive_data(line[:200])})
                if len(matches) >= 200:
                    return matches
    return matches


def tool_pytest_run(repo_path: Path | str, target: str | None = None, timeout: float = 45.0) -> dict[str, Any]:
    """Run pytest read-only in repo_path and return structured counts + scrubbed tail."""
    repo = Path(repo_path).resolve()
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short"]
    if target:
        if target.startswith("-"):
            raise ValueError(f"Refusing option-like pytest target: {target!r}")
        cmd.extend(["--", target])
    try:
        res = subprocess.run(
            cmd, cwd=str(repo), capture_output=True, text=True, timeout=timeout, check=False
        )
        out = scrub_sensitive_data(res.stdout + "\n" + res.stderr, base_dir=repo)
        passed_m = re.search(r"(\d+)\s+passed", out)
        failed_m = re.search(r"(\d+)\s+failed", out)
        error_m = re.search(r"(\d+)\s+error", out)
        return {
            "exit_code": res.returncode,
            "passed": int(passed_m.group(1)) if passed_m else 0,
            "failed": int(failed_m.group(1)) if failed_m else 0,
            "errors": int(error_m.group(1)) if error_m else 0,
            "output_tail": out[-2500:],
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "passed": 0, "failed": 0, "errors": 1, "output_tail": "TIMEOUT"}


def execute_grounding_tool(
    tool_name: str,
    allowed_tools: tuple[str, ...],
    repo_path: Path | str,
    **kwargs: Any,
) -> Any:
    """Enforce per-agent tool permissions before dispatching a grounding tool."""
    if "all" not in allowed_tools and tool_name not in allowed_tools:
        raise PermissionError(
            f"Tool {tool_name!r} is not permitted for agent with allowed_tools={allowed_tools}"
        )

    dispatch = {
        "ast_scan": lambda: tool_ast_scan(repo_path, rel_paths=kwargs.get("rel_paths")),
        "ruff_json": lambda: tool_ruff_json(repo_path),
        "radon_cc": lambda: tool_radon_cc(repo_path),
        "grep": lambda: tool_grep(repo_path, kwargs["pattern"], path_prefix=kwargs.get("path_prefix", "")),
        "git_ls": lambda: tool_git_ls(repo_path),
        "pytest_run": lambda: tool_pytest_run(repo_path, target=kwargs.get("target")),
        "probe_run": lambda: run_isolated_probe(
            repo_path, kwargs["probe_script"], timeout_seconds=kwargs.get("timeout", 15.0)
        ).model_dump(),
    }
    if tool_name not in dispatch:
        raise KeyError(f"Unknown grounding tool: {tool_name!r}")
    return dispatch[tool_name]()
