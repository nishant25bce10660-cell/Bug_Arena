"""BugArena MCP Server exposing tools, resources, and repair tournament workflows."""

import ast
import asyncio
import threading
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from bugarena.audit.fix_loop import run_fix_loop_session
from bugarena.audit.loop import LoopOperator
from bugarena.config import load_env_file
from bugarena.discovery.engine import BugDiscoveryEngine
from bugarena.evaluation.test_runner import PatchEvaluator
from bugarena.models.agent import CandidatePatch, PersonaType
from bugarena.models.bug import BugSpec, SuspectLocation
from bugarena.models.report import FixReport
from bugarena.models.repro import ReproTestSpec
from bugarena.models.tournament import TournamentRecord
from bugarena.reporting.markdown_formatter import (
    format_bug_diagnostic_markdown,
    format_markdown_report,
    save_markdown_report,
)
from bugarena.sandbox.security import (
    SecurityViolationError,
    scrub_sensitive_data,
    validate_safe_path,
)
from bugarena.synthesizer.red_validator import ReproductionFalsePositiveError, validate_red_baseline
from bugarena.synthesizer.test_generator import generate_reproduction_test_code
from bugarena.tournament.patch_parser import PatchValidationError, parse_and_validate_patch
from bugarena.tournament.runner import TournamentRunner

# Load .env file if present
load_env_file()

mcp = MCPServer("bugarena")
_LOOP_OPERATOR = LoopOperator()

# Bounded, thread-safe in-memory registries for multi-step tool sessions (max 100 entries to prevent memory leaks)
MAX_REGISTRY_SIZE = 100
_REGISTRY_LOCK = threading.Lock()
_TOURNAMENT_REGISTRY: OrderedDict[str, TournamentRecord] = OrderedDict()
_REPRO_REGISTRY: OrderedDict[str, ReproTestSpec] = OrderedDict()
_BUG_REGISTRY: OrderedDict[str, BugSpec] = OrderedDict()


def _store_tournament(t_id: str, tournament: TournamentRecord) -> None:
    with _REGISTRY_LOCK:
        _TOURNAMENT_REGISTRY[t_id] = tournament
        if len(_TOURNAMENT_REGISTRY) > MAX_REGISTRY_SIZE:
            _TOURNAMENT_REGISTRY.popitem(last=False)


def _repro_key(repo_path: Path | str, test_rel_path: str) -> str:
    return f"{Path(repo_path).resolve()}::{test_rel_path}"


def _store_repro(repo_path: Path | str, test_rel_path: str, spec: ReproTestSpec) -> None:
    key = _repro_key(repo_path, test_rel_path)
    with _REGISTRY_LOCK:
        _REPRO_REGISTRY[key] = spec
        _REPRO_REGISTRY.move_to_end(key)
        if len(_REPRO_REGISTRY) > MAX_REGISTRY_SIZE:
            _REPRO_REGISTRY.popitem(last=False)


def _lookup_repro(repo_path: Path | str, test_rel_path: str | None = None) -> ReproTestSpec | None:
    resolved_prefix = f"{Path(repo_path).resolve()}::"
    with _REGISTRY_LOCK:
        if test_rel_path is not None:
            key = f"{resolved_prefix}{test_rel_path}"
            spec = _REPRO_REGISTRY.get(key)
            if spec is not None:
                _REPRO_REGISTRY.move_to_end(key)
            return spec
        for key in reversed(list(_REPRO_REGISTRY.keys())):
            if key.startswith(resolved_prefix):
                _REPRO_REGISTRY.move_to_end(key)
                return _REPRO_REGISTRY[key]
        return None


def _store_bug(bug_id: str, spec: BugSpec) -> None:
    with _REGISTRY_LOCK:
        _BUG_REGISTRY[bug_id] = spec
        if len(_BUG_REGISTRY) > MAX_REGISTRY_SIZE:
            _BUG_REGISTRY.popitem(last=False)


@mcp.tool()
def bug_detect(
    repo_path: str,
    error_log: str,
    hint: str = "",
    max_candidates: int = 3,
) -> dict[str, Any]:
    """
    Analyze error log or stack trace, parse AST, and locate suspect bug positions.
    """
    if repo_path.startswith("-"):
        raise ValueError(f"Invalid repo_path: '{repo_path}' cannot start with '-'")

    bounded_error_log = error_log[-65536:] if len(error_log) > 65536 else error_log
    bounded_max = min(max(1, max_candidates), 10)

    engine = BugDiscoveryEngine(repo_path)
    bug_spec = engine.discover_from_trace(
        error_log=bounded_error_log, hint=hint or None, max_candidates=bounded_max
    )
    _store_bug(bug_spec.bug_id, bug_spec)
    return {
        "bug_id": bug_spec.bug_id,
        "repo_path": bug_spec.repo_path,
        "suspects": _scrub_payload([s.model_dump() for s in bug_spec.suspects], base_dir=repo_path),
        "trace_count": len(bug_spec.traces),
    }


@mcp.tool()
def bug_reproduce(
    repo_path: str,
    suspect_file: str,
    bug_description: str,
    function_name: str = "",
    call_expr: str = "",
    expected_behavior: str = "",
) -> dict[str, Any]:
    """
    Synthesize an automated minimal reproduction test and verify Red-baseline failure.
    """
    suspect = SuspectLocation(
        file_path=suspect_file,
        function_name=function_name or "target",
        line_range=(1, 1),
        confidence=0.9,
        bug_type="Defect",
        reasoning=bug_description,
        code_snippet="",
    )
    test_code = generate_reproduction_test_code(
        suspect=suspect,
        bug_description=bug_description,
        call_expr=call_expr or None,
        expected_behavior=expected_behavior or None,
    )
    test_rel_path = f"tests/repro/test_issue_{uuid.uuid4().hex[:6]}.py"

    try:
        spec = validate_red_baseline(
            base_repo_path=repo_path,
            test_rel_path=test_rel_path,
            test_code=test_code,
        )
        _store_repro(repo_path, test_rel_path, spec)
        return {
            "status": "REPRODUCED_RED",
            "test_file_path": spec.test_file_path,
            "test_code": spec.test_code,
            "red_baseline_verified": spec.red_baseline_verified,
            "failure_output": spec.initial_outcome.stderr if spec.initial_outcome else "",
        }
    except ReproductionFalsePositiveError as err:
        return {
            "status": "FALSE_POSITIVE_REPRO",
            "test_file_path": test_rel_path,
            "test_code": test_code,
            "red_baseline_verified": False,
            "error": str(err),
        }


@mcp.tool()
def agent_fix_tournament(
    repo_path: str,
    repro_test_file: str,
    candidate_patches_raw: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Register and validate candidate patches generated by competing agent personas.
    """
    tournament_id = f"tourn_{uuid.uuid4().hex[:8]}"
    candidates: list[CandidatePatch] = []

    for item in candidate_patches_raw:
        if not isinstance(item, dict) or "diff" not in item:
            return {
                "error": "Each candidate patch must be a dictionary containing a 'diff' string."
            }
        try:
            persona = PersonaType(item.get("persona", "surgical_minimalist"))
        except ValueError:
            return {
                "error": f"Invalid persona '{item.get('persona')}'. Allowed personas: {[p.value for p in PersonaType]}"
            }

        try:
            cand = parse_and_validate_patch(
                raw_diff=item["diff"],
                persona=persona,
                explanation=item.get("explanation", ""),
                candidate_id=item.get("candidate_id"),
                protected_paths=[repro_test_file],
            )
            candidates.append(cand)
        except PatchValidationError as err:
            return {
                "error": f"Invalid diff syntax in candidate '{item.get('candidate_id')}': {err}"
            }

    linked_repro = _lookup_repro(repo_path, repro_test_file)

    tournament = TournamentRecord(
        tournament_id=tournament_id,
        repo_path=repo_path,
        candidates=candidates,
        evaluations=[],
        champion_candidate_id=None,
        repro_spec=linked_repro,
    )
    _store_tournament(tournament_id, tournament)

    return {
        "tournament_id": tournament_id,
        "candidate_count": len(candidates),
        "candidates": [c.model_dump() for c in candidates],
    }


_UNSAFE_REPRO_CALLS = frozenset({
    "__import__",
    "eval",
    "exec",
    "compile",
    "open",
    "system",
    "popen",
    "write_text",
    "write_bytes",
    "unlink",
    "rmdir",
})
_UNSAFE_REPRO_IMPORTS = frozenset({
    "os",
    "subprocess",
    "shutil",
    "socket",
    "ctypes",
    "importlib",
    "http",
    "urllib",
    "requests",
    "httpx",
})


def _validate_repro_code_ast(repro_code: str) -> None:
    """Validate caller-supplied repro_code AST when no pre-verified tournament.repro_spec exists."""
    try:
        tree = ast.parse(repro_code)
    except SyntaxError as exc:
        raise ValueError(f"Invalid syntax in repro_code: {exc}") from exc

    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign, ast.AnnAssign, ast.Expr)):
            raise SecurityViolationError(f"Unsupported top-level statement {type(node).__name__} in repro_code")
        if isinstance(node, ast.Expr) and not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            raise SecurityViolationError("Top-level executable expressions are disallowed in repro_code")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _UNSAFE_REPRO_IMPORTS:
                    raise SecurityViolationError(f"Unsafe module import {alias.name!r} in repro_code")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in _UNSAFE_REPRO_IMPORTS:
                raise SecurityViolationError(f"Unsafe module import {node.module!r} in repro_code")
        elif isinstance(node, ast.Name) and node.id in _UNSAFE_REPRO_CALLS:
            raise SecurityViolationError(f"Unsafe identifier {node.id!r} in repro_code")
        elif isinstance(node, ast.Attribute) and (node.attr.startswith("__") or node.attr in _UNSAFE_REPRO_CALLS):
            raise SecurityViolationError(f"Unsafe attribute {node.attr!r} in repro_code")


@mcp.tool()
def evaluate_patches(
    repo_path: str,
    tournament_id: str,
    repro_test_file: str,
    repro_code: str,
) -> dict[str, Any]:
    """
    Evaluate all tournament candidate patches inside isolated ephemeral sandboxes.
    """
    with _REGISTRY_LOCK:
        tournament = _TOURNAMENT_REGISTRY.get(tournament_id)
    if not tournament:
        return {"error": f"Tournament ID '{tournament_id}' not found."}

    if tournament.repro_spec is not None:
        if (
            repro_test_file != tournament.repro_spec.test_file_path
            or repro_code != tournament.repro_spec.test_code
        ):
            raise SecurityViolationError(
                "repro_test_file or repro_code does not match the tournament's verified repro_spec."
            )
        repro_spec = tournament.repro_spec
    else:
        _validate_repro_code_ast(repro_code)
        repro_spec = validate_red_baseline(
            base_repo_path=repo_path,
            test_rel_path=repro_test_file,
            test_code=repro_code,
        )

    evaluator = PatchEvaluator(base_repo_path=repo_path)
    evaluations, champion_id = evaluator.evaluate_candidates(
        candidates=tournament.candidates,
        repro_spec=repro_spec,
    )

    updated_tournament = TournamentRecord(
        tournament_id=tournament.tournament_id,
        repo_path=tournament.repo_path,
        candidates=tournament.candidates,
        evaluations=evaluations,
        champion_candidate_id=champion_id,
        bug_spec=tournament.bug_spec,
        repro_spec=tournament.repro_spec or repro_spec,
        bug_description=tournament.bug_description,
    )
    _store_tournament(tournament_id, updated_tournament)

    return {
        "tournament_id": tournament_id,
        "champion_candidate_id": champion_id,
        "leaderboard": [e.model_dump() for e in evaluations],
    }


@mcp.tool()
def generate_fix_report(
    tournament_id: str,
    format: str = "markdown",
    output_file: str = "",
) -> dict[str, Any]:
    """
    Generate an actionable tournament diagnostic report and git patch,
    and save the report to a markdown (.md) file on disk.
    """
    with _REGISTRY_LOCK:
        tournament = _TOURNAMENT_REGISTRY.get(tournament_id)
    if not tournament:
        return {"error": f"Tournament ID '{tournament_id}' not found."}

    report_md = format_markdown_report(tournament)
    champion_patch = None
    if tournament.champion_candidate_id:
        champion_patch = next(
            (
                c.diff
                for c in tournament.candidates
                if c.candidate_id == tournament.champion_candidate_id
            ),
            None,
        )

    # Format validation & path-confined report persistence
    if format not in ("markdown", "json", "diff"):
        raise ValueError(f"Unsupported format {format!r}; expected 'markdown', 'json', or 'diff'.")

    saved_path: Path | None = None
    if format == "json":
        import json as _json

        default_json = str(
            Path(tournament.repo_path) / "reports" / f"bug_report_{tournament.tournament_id}.json"
        )
        out_path = output_file or default_json
        safe_out = validate_safe_path(tournament.repo_path, out_path)
        json_payload = {
            "tournament_id": tournament.tournament_id,
            "champion_candidate_id": tournament.champion_candidate_id,
            "evaluations": [e.model_dump() for e in tournament.evaluations],
            "champion_diff": champion_patch,
        }
        saved_path = save_markdown_report(
            _json.dumps(json_payload, indent=2), safe_out, base_dir=tournament.repo_path
        )
    elif format == "markdown":
        out_path = output_file or str(
            Path(tournament.repo_path) / "reports" / f"bug_report_{tournament.tournament_id}.md"
        )
        safe_out = validate_safe_path(tournament.repo_path, out_path)
        saved_path = save_markdown_report(report_md, safe_out, base_dir=tournament.repo_path)
    elif output_file:
        safe_out = validate_safe_path(tournament.repo_path, output_file)
        saved_path = save_markdown_report(
            champion_patch or "", safe_out, base_dir=tournament.repo_path
        )

    champion_cand = (
        next((c for c in tournament.candidates if c.candidate_id == tournament.champion_candidate_id), None)
        if tournament.champion_candidate_id
        else None
    )
    champion_eval = (
        next((e for e in tournament.evaluations if e.candidate_id == tournament.champion_candidate_id), None)
        if tournament.champion_candidate_id
        else None
    )

    fix_report = FixReport(
        tournament_id=tournament.tournament_id,
        champion_patch=champion_cand,
        champion_eval=champion_eval,
        summary_markdown=report_md,
        git_patch_diff=champion_patch or "",
        report_file_path=str(saved_path) if saved_path else None,
    )
    if saved_path is not None:
        _store_tournament(
            tournament.tournament_id,
            tournament.model_copy(update={"report_file_path": str(saved_path)}),
        )

    if format == "json":
        return {
            "tournament_id": tournament.tournament_id,
            "champion_candidate_id": tournament.champion_candidate_id,
            "evaluations": [e.model_dump() for e in tournament.evaluations],
            "champion_diff": champion_patch,
            "report_file_path": str(saved_path) if saved_path else "",
            "report": fix_report.model_dump(),
        }
    elif format == "diff":
        return {
            "diff": champion_patch or "",
            "git_patch_diff": champion_patch or "",
            "report_file_path": str(saved_path) if saved_path else "",
        }
    else:
        return {
            "report_markdown": report_md,
            "summary_markdown": report_md,
            "champion_diff": champion_patch or "",
            "git_patch_diff": champion_patch or "",
            "report_file_path": str(saved_path) if saved_path else "",
            "report": fix_report.model_dump(),
        }


@mcp.tool()
def generate_bug_report(
    repo_path: str,
    error_log: str,
    bug_description: str = "",
    hint: str = "",
    output_file: str = "",
) -> dict[str, Any]:
    """
    Generate and save a standalone markdown (.md) diagnostic report of a detected bug,
    including suspect code locations, AST analysis, and stack trace.
    """
    engine = BugDiscoveryEngine(repo_path)
    bug_spec = engine.discover_from_trace(error_log=error_log, hint=hint or None)
    _store_bug(bug_spec.bug_id, bug_spec)

    repro_spec = _lookup_repro(repo_path)

    report_md = (
        f"# Bug Diagnostic Report\n"
        f"**Bug ID**: `{bug_spec.bug_id}`  \n"
        f"**Repository**: `{bug_spec.repo_path}`  \n\n"
    )
    report_md += format_bug_diagnostic_markdown(
        bug_spec=bug_spec,
        repro_spec=repro_spec,
        bug_description=bug_description,
    )

    report_md = scrub_sensitive_data(report_md, base_dir=repo_path)
    out_path = output_file or str(Path(repo_path) / "reports" / f"bug_report_{bug_spec.bug_id}.md")
    safe_out = validate_safe_path(repo_path, out_path)
    saved_path = save_markdown_report(report_md, safe_out, base_dir=repo_path)

    return {
        "bug_id": bug_spec.bug_id,
        "report_markdown": report_md,
        "report_file_path": str(saved_path),
        "suspects": _scrub_payload([s.model_dump() for s in bug_spec.suspects], base_dir=repo_path),
    }


@mcp.tool()
def bugarena_autonomous_repair(
    repo_path: str,
    error_log: str,
    bug_description: str,
    candidate_patches_raw: list[dict[str, Any]],
    hint: str = "",
    call_expr: str = "",
    expected_behavior: str = "",
    output_report_file: str = "",
    auto_generate: bool = False,
) -> dict[str, Any]:
    """
    Composite end-to-end autonomous repair workflow:
    Detection -> Reproduction -> Tournament -> Sandbox Verification -> Report.
    """
    bounded_error = error_log[-65536:] if len(error_log) > 65536 else error_log
    bounded_desc = bug_description[:65536] if len(bug_description) > 65536 else bug_description
    candidate_warning = ""
    if len(candidate_patches_raw) > 20:
        candidate_warning = (
            f"Truncated candidate_patches_raw from {len(candidate_patches_raw)} to 20."
        )
        bounded_candidates = candidate_patches_raw[:20]
    else:
        bounded_candidates = candidate_patches_raw

    # 1. Detection
    detect_res = bug_detect(repo_path, bounded_error, hint=hint)
    suspects = detect_res["suspects"]
    if not suspects:
        return {
            "status": "NO_SUSPECTS_FOUND",
            "bug_id": detect_res["bug_id"],
            "error": "No source suspect locations could be localized from error_log.",
        }
    primary_file = suspects[0]["file_path"]
    primary_func = suspects[0]["function_name"]

    # 2. Reproduction
    repro_res = bug_reproduce(
        repo_path=repo_path,
        suspect_file=primary_file,
        bug_description=bounded_desc,
        function_name=primary_func,
        call_expr=call_expr,
        expected_behavior=expected_behavior,
    )
    if repro_res.get("status") != "REPRODUCED_RED":
        return {
            "status": repro_res.get("status", "FAILED_REPRO"),
            "error": repro_res.get("error", "Reproduction test did not verify a Red-baseline."),
            "repro_res": repro_res,
        }

    test_rel_path = repro_res["test_file_path"]
    test_code = repro_res["test_code"]

    # Optional gated LLM candidate generation via TournamentRunner
    if not bounded_candidates and auto_generate:
        b_spec = _BUG_REGISTRY.get(detect_res["bug_id"])
        r_spec = _lookup_repro(repo_path, test_rel_path)
        if b_spec and r_spec:
            t_runner = TournamentRunner()
            _tid, gen_cands = asyncio.run(t_runner.run_tournament(b_spec, r_spec))
            bounded_candidates = [
                {
                    "candidate_id": c.candidate_id,
                    "persona": c.persona.value,
                    "explanation": c.explanation,
                    "diff": c.diff,
                }
                for c in gen_cands
            ]

    # 3. Tournament registration
    tourn_res = agent_fix_tournament(
        repo_path=repo_path,
        repro_test_file=test_rel_path,
        candidate_patches_raw=bounded_candidates,
    )
    if "error" in tourn_res:
        return tourn_res
    t_id = tourn_res["tournament_id"]

    # Enrich tournament record with bug and repro specs for comprehensive reporting
    r_spec_linked = _lookup_repro(repo_path, test_rel_path)
    with _REGISTRY_LOCK:
        existing_t = _TOURNAMENT_REGISTRY.get(t_id)
        if existing_t:
            updated_t = TournamentRecord(
                tournament_id=existing_t.tournament_id,
                repo_path=existing_t.repo_path,
                candidates=existing_t.candidates,
                evaluations=existing_t.evaluations,
                champion_candidate_id=existing_t.champion_candidate_id,
                bug_spec=_BUG_REGISTRY.get(detect_res["bug_id"]),
                repro_spec=r_spec_linked,
                bug_description=bounded_desc,
            )
            _TOURNAMENT_REGISTRY[t_id] = updated_t

    # 4. Evaluation
    eval_res = evaluate_patches(
        repo_path=repo_path,
        tournament_id=t_id,
        repro_test_file=test_rel_path,
        repro_code=test_code,
    )
    if "error" in eval_res:
        return eval_res

    # 5. Report
    report_res = generate_fix_report(t_id, format="markdown", output_file=output_report_file)

    out_dict: dict[str, Any] = {
        "tournament_id": t_id,
        "champion_candidate_id": eval_res["champion_candidate_id"],
        "leaderboard": eval_res["leaderboard"],
        "report_markdown": report_res["report_markdown"],
        "summary_markdown": report_res["summary_markdown"],
        "champion_diff": report_res["champion_diff"],
        "git_patch_diff": report_res["git_patch_diff"],
        "report_file_path": report_res["report_file_path"],
    }
    if candidate_warning:
        out_dict["warning"] = candidate_warning
    return out_dict


def _scrub_payload(obj: Any, base_dir: Path | str | None = None) -> Any:
    if isinstance(obj, str):
        return scrub_sensitive_data(obj, base_dir=base_dir)
    if isinstance(obj, list):
        return [_scrub_payload(item, base_dir=base_dir) for item in obj]
    if isinstance(obj, dict):
        return {k: _scrub_payload(v, base_dir=base_dir) for k, v in obj.items()}
    return obj


@mcp.tool()
async def audit_start(
    repo_path: str,
    mode: str = "read_only",
    max_rounds: int = 6,
    agents: list[str] | None = None,
) -> dict[str, Any]:
    """Initialize a multi-agent read-only or fix audit run and return its run_id."""
    if repo_path.startswith("-"):
        raise ValueError(f"Invalid repo_path: '{repo_path}' cannot start with '-'")
    res = await asyncio.to_thread(
        _LOOP_OPERATOR.start,
        repo_path,
        mode=mode,
        max_rounds=max_rounds,
        agents=agents,
    )
    return _scrub_payload(res, base_dir=repo_path)


@mcp.tool()
async def audit_round(
    run_id: str,
    auto_generate: bool = False,
) -> dict[str, Any]:
    """Execute one multi-agent sweep, independent verification, dedupe, and coverage round."""
    if not run_id or run_id.startswith("-"):
        raise ValueError("Invalid run_id")
    res = await _LOOP_OPERATOR.run_round(run_id, auto_generate=auto_generate)
    return _scrub_payload(res)


@mcp.tool()
async def audit_status(run_id: str) -> dict[str, Any]:
    """Return ledger counts, coverage percentage, and stop-condition state for an audit run."""
    if not run_id or run_id.startswith("-"):
        raise ValueError("Invalid run_id")
    res = await asyncio.to_thread(_LOOP_OPERATOR.status, run_id)
    return _scrub_payload(res)


@mcp.tool()
async def finding_verify(run_id: str, finding_id: str) -> dict[str, Any]:
    """Force independent second-agent dynamic re-verification of one ledger finding."""
    if not run_id or not finding_id:
        raise ValueError("run_id and finding_id are required")
    res = await asyncio.to_thread(_LOOP_OPERATOR.verify_one, run_id, finding_id)
    return _scrub_payload(res)


@mcp.tool()
async def audit_report(
    run_id: str,
    format: str = "markdown",
    output_file: str | None = None,
) -> dict[str, Any]:
    """Generate an evidence-graded audit report; output_file is confined by validate_safe_path."""
    if format not in ("markdown", "json"):
        raise ValueError(f"Invalid format {format!r}; expected 'markdown' or 'json'")
    _rdir, state, _ledger, _cov = await asyncio.to_thread(_LOOP_OPERATOR.load_run, run_id)
    validated_out: Path | None = None
    if output_file:
        validated_out = validate_safe_path(state.repo_path, output_file)
    res = await asyncio.to_thread(
        _LOOP_OPERATOR.report,
        run_id,
        format=format,
        output_file=validated_out,
    )
    return _scrub_payload(res, base_dir=state.repo_path)


@mcp.tool()
async def fix_loop_start(
    run_id: str,
    finding_ids: list[str] | None = None,
    auto_generate: bool = False,
) -> dict[str, Any]:
    """Execute test-first fix evaluation over confirmed ledger findings (LLM generation gated by auto_generate)."""
    if not run_id or run_id.startswith("-"):
        raise ValueError("Invalid run_id")
    res = await run_fix_loop_session(
        _LOOP_OPERATOR,
        run_id,
        finding_ids=finding_ids,
        auto_generate=auto_generate,
    )
    return _scrub_payload(res)


def main():
    """CLI server entrypoint."""
    mcp.run()


if __name__ == "__main__":
    main()
