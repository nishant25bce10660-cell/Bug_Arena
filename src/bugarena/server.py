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
from bugarena.inspect.site_audit import SiteAuditCoordinator
from bugarena.linking import link_site_and_project_findings
from bugarena.models.agent import PersonaType
from bugarena.models.bug import BugSpec, SuspectLocation
from bugarena.models.report import FixReport
from bugarena.models.repro import ReproTestSpec
from bugarena.models.tournament import TournamentRecord
from bugarena.reporting.markdown_formatter import (
    format_bug_diagnostic_markdown,
    format_markdown_report,
    save_markdown_report,
)
from bugarena.reporting.v2_report import build_v2_report_bundle
from bugarena.sandbox.security import (
    SecurityViolationError,
    scrub_sensitive_data,
    validate_safe_path,
)
from bugarena.skills_merge import merge_both_skills as _merge_both_skills_impl
from bugarena.synthesizer.red_validator import ReproductionFalsePositiveError, validate_red_baseline
from bugarena.synthesizer.test_generator import generate_reproduction_test_code
from bugarena.tournament.patch_parser import PatchValidationError, parse_and_validate_patch
from bugarena.tournament.providers.cross_vendor import analyze_findings_cross_vendor
from bugarena.tournament.runner import TournamentRunner
from bugarena.truth import AgentScoreboard, ClaimLedger, EvidenceVault
from bugarena.verify import build_verify_pack

# Load .env file if present
load_env_file()

mcp = MCPServer("bugarena")
_LOOP_OPERATOR = LoopOperator()
_SITE_COORDINATOR = SiteAuditCoordinator()

# Bounded, thread-safe in-memory registries for multi-step tool sessions (max 100 entries to prevent memory leaks)
MAX_REGISTRY_SIZE = 100
_REGISTRY_LOCK = threading.Lock()
_TOURNAMENT_REGISTRY: OrderedDict[str, TournamentRecord] = OrderedDict()
_REPRO_REGISTRY: OrderedDict[str, ReproTestSpec] = OrderedDict()
_BUG_REGISTRY: OrderedDict[str, BugSpec] = OrderedDict()


def _store_tournament(t_id: str, tournament: TournamentRecord) -> None:
    with _REGISTRY_LOCK:
        _TOURNAMENT_REGISTRY[t_id] = tournament
        _TOURNAMENT_REGISTRY.move_to_end(t_id)
        while len(_TOURNAMENT_REGISTRY) > MAX_REGISTRY_SIZE:
            _TOURNAMENT_REGISTRY.popitem(last=False)


def _get_tournament(t_id: str) -> TournamentRecord | None:
    with _REGISTRY_LOCK:
        rec = _TOURNAMENT_REGISTRY.get(t_id)
        if rec is not None:
            _TOURNAMENT_REGISTRY.move_to_end(t_id)
        return rec


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
        _BUG_REGISTRY.move_to_end(bug_id)
        while len(_BUG_REGISTRY) > MAX_REGISTRY_SIZE:
            _BUG_REGISTRY.popitem(last=False)


def _get_bug(bug_id: str) -> BugSpec | None:
    with _REGISTRY_LOCK:
        spec = _BUG_REGISTRY.get(bug_id)
        if spec is not None:
            _BUG_REGISTRY.move_to_end(bug_id)
        return spec


@mcp.tool(description="Analyze an error log or traceback, map AST scopes, and locate suspect bug positions.")
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


@mcp.tool(description="Synthesize a minimal pytest reproduction test and verify Red-baseline failure in an isolated sandbox.")
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
    if repo_path.startswith("-"):
        raise ValueError(f"Invalid repo_path: '{repo_path}' cannot start with '-'")
    bounded_desc = bug_description[:65536] if len(bug_description) > 65536 else bug_description
    suspect = SuspectLocation(
        file_path=suspect_file,
        function_name=function_name or "target",
        line_range=(1, 1),
        confidence=0.9,
        bug_type="Defect",
        reasoning=bounded_desc,
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
        failure_parts = []
        if spec.initial_outcome:
            if spec.initial_outcome.stdout.strip():
                failure_parts.append(spec.initial_outcome.stdout.strip())
            if spec.initial_outcome.stderr.strip():
                failure_parts.append(spec.initial_outcome.stderr.strip())
        return {
            "status": "REPRODUCED_RED",
            "test_file_path": spec.test_file_path,
            "test_code": spec.test_code,
            "red_baseline_verified": spec.red_baseline_verified,
            "failure_output": "\n".join(failure_parts),
        }
    except ReproductionFalsePositiveError as err:
        return {
            "status": "FALSE_POSITIVE_REPRO",
            "test_file_path": test_rel_path,
            "test_code": test_code,
            "red_baseline_verified": False,
            "error": str(err),
        }


@mcp.tool(description="Register, validate, or generate competing candidate patches across bug-fixing personas.")
def agent_fix_tournament(
    repo_path: str,
    repro_test_file: str,
    candidate_patches_raw: list[dict[str, Any]],
    auto_generate: bool = False,
) -> dict[str, Any]:
    """
    Register and validate candidate patches generated by competing agent personas.
    """
    if repo_path.startswith("-"):
        return {"error": f"Invalid repo_path: '{repo_path}' cannot start with '-'"}
    if len(candidate_patches_raw) > 20:
        return {"error": f"Too many candidate patches ({len(candidate_patches_raw)} > 20 max)."}

    tournament_id = f"tourn_{uuid.uuid4().hex[:8]}"
    linked_repro = _lookup_repro(repo_path, repro_test_file)

    if auto_generate and not candidate_patches_raw and linked_repro is not None:
        t_runner = TournamentRunner()
        b_spec = BugSpec(bug_id=f"bug_{uuid.uuid4().hex[:8]}", repo_path=str(Path(repo_path).resolve()))
        _tid, candidates = asyncio.run(t_runner.run_tournament(b_spec, linked_repro))
    else:
        candidates = []
        seen_ids: set[str] = set()
        for item in candidate_patches_raw:
            if not isinstance(item, dict) or not isinstance(item.get("diff"), str):
                return {
                    "error": "Each candidate patch must be a dictionary containing a 'diff' string."
                }
            if len(item["diff"]) > 200_000:
                return {"error": "Candidate diff exceeds 200KB limit."}
            raw_persona = item.get("persona")
            persona_key = "surgical_minimalist" if raw_persona is None else raw_persona
            try:
                persona = PersonaType(persona_key)
            except ValueError:
                return {
                    "error": f"Invalid persona '{raw_persona}'. Allowed personas: {[p.value for p in PersonaType]}"
                }

            raw_expl = item.get("explanation")
            clean_expl = "" if raw_expl is None else str(raw_expl)
            raw_cid = item.get("candidate_id")
            if raw_cid is not None and not isinstance(raw_cid, str):
                return {"error": f"candidate_id must be a string, got {type(raw_cid).__name__}"}

            try:
                cand = parse_and_validate_patch(
                    raw_diff=item["diff"],
                    persona=persona,
                    explanation=clean_expl,
                    candidate_id=raw_cid,
                    protected_paths=[repro_test_file],
                )
            except (PatchValidationError, ValueError) as err:
                return {
                    "error": f"Invalid diff syntax in candidate '{raw_cid}': {err}"
                }

            if cand.candidate_id in seen_ids:
                return {"error": f"Duplicate candidate_id: '{cand.candidate_id}'"}
            seen_ids.add(cand.candidate_id)
            candidates.append(cand)

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


@mcp.tool(description="Evaluate tournament candidate patches in isolated sandboxes for Red-to-Green, regressions, AST syntax, and CC delta.")
def evaluate_patches(
    repo_path: str,
    tournament_id: str,
    repro_test_file: str,
    repro_code: str,
) -> dict[str, Any]:
    """
    Evaluate all tournament candidate patches inside isolated ephemeral sandboxes.
    """
    tournament = _get_tournament(tournament_id)
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

    with _REGISTRY_LOCK:
        latest = _TOURNAMENT_REGISTRY.get(tournament_id) or tournament
        updated_tournament = TournamentRecord(
            tournament_id=latest.tournament_id,
            repo_path=latest.repo_path,
            candidates=latest.candidates,
            evaluations=evaluations,
            champion_candidate_id=champion_id,
            bug_spec=latest.bug_spec,
            repro_spec=latest.repro_spec or repro_spec,
            bug_description=latest.bug_description,
            report_file_path=latest.report_file_path,
        )
        _TOURNAMENT_REGISTRY[tournament_id] = updated_tournament
        _TOURNAMENT_REGISTRY.move_to_end(tournament_id)

    return {
        "tournament_id": tournament_id,
        "champion_candidate_id": champion_id,
        "leaderboard": [e.model_dump() for e in evaluations],
    }


@mcp.tool(description="Generate a tournament diagnostic report in markdown, json, or diff format and optionally save it inside repo_path.")
def generate_fix_report(
    tournament_id: str,
    format: str = "markdown",
    output_file: str = "",
) -> dict[str, Any]:
    """
    Generate an actionable tournament diagnostic report and git patch,
    and save the report to a markdown (.md) file on disk.
    """
    tournament = _get_tournament(tournament_id)
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


@mcp.tool(description="Generate and save a standalone Markdown diagnostic report covering suspects, traces, and reproduction status.")
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
    if repo_path.startswith("-"):
        raise ValueError(f"Invalid repo_path: '{repo_path}' cannot start with '-'")
    bounded_log = error_log[-65536:] if len(error_log) > 65536 else error_log
    engine = BugDiscoveryEngine(repo_path)
    bug_spec = engine.discover_from_trace(error_log=bounded_log, hint=hint or None)
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


@mcp.tool(description="Run the end-to-end autonomous repair lifecycle: detect, reproduce, tournament, evaluate, and report.")
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


_PRESERVED_PATH_KEYS = frozenset({
    "run_dir",
    "scope_file",
    "report_md",
    "report_pdf",
    "report_json",
    "verify_dir",
    "verify_script",
    "verify_prompt",
    "claims_file",
    "report_path",
    "manifest_path",
    "package_dir",
})


_SENSITIVE_DICT_KEYS = frozenset({
    "cookie",
    "set-cookie",
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "x-goog-api-key",
    "x-auth-token",
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
})


def _scrub_payload(obj: Any, base_dir: Path | str | None = None) -> Any:
    from bugarena.truth.vault import scrub_evidence_text

    if isinstance(obj, str):
        scrubbed, _ = scrub_evidence_text(obj, base_dir=base_dir)
        return scrubbed
    if isinstance(obj, tuple):
        return [_scrub_payload(item, base_dir=base_dir) for item in obj]
    if isinstance(obj, list):
        return [_scrub_payload(item, base_dir=base_dir) for item in obj]
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            if k in _PRESERVED_PATH_KEYS:
                out[k] = v
            elif isinstance(k, str) and k.lower() in _SENSITIVE_DICT_KEYS and isinstance(v, str) and v:
                out[k] = "[REDACTED]"
            else:
                out[k] = _scrub_payload(v, base_dir=base_dir)
        return out
    return obj


def _authorize_v2_tool(run_id: str, tool_name: str, session_token: str) -> dict[str, Any]:
    import secrets

    sess = _SITE_COORDINATOR.sessions.get_session(run_id)
    if not session_token or not secrets.compare_digest(session_token, sess["session_token"]):
        raise PermissionError("Invalid session_token; run session_confirm first.")
    active_tools = sess.get("active_tools")
    if active_tools is not None and (sess.get("enforce_tool_acl") or active_tools) and tool_name not in active_tools:
        raise PermissionError(f"Tool '{tool_name}' is not permitted by session active_tools / tools_denied.")
    return sess


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


@mcp.tool(description="Detect installed Chrome/Brave/Helium browsers, check API key presence, and return the 13-question pre-start gate without launching any browser.")
async def session_prepare(user_hint: str | None = None) -> dict[str, Any]:
    """Prepare site audit questionnaire and environment inventory (launches nothing)."""
    res = await asyncio.to_thread(_SITE_COORDINATOR.sessions.session_prepare, user_hint)
    return _scrub_payload(res)


@mcp.tool(description="Validate questionnaire answers, enforce passive mode when unauthorized, write scope_and_authorization.md, and issue a session token.")
async def session_confirm(answers: dict[str, Any]) -> dict[str, Any]:
    """Validate pre-start answers and authorize a scoped audit session."""
    registered = await mcp.list_tools()
    tool_names = tuple(t.name for t in registered)
    res = await asyncio.to_thread(
        _SITE_COORDINATOR.sessions.session_confirm,
        answers,
        all_tool_names=tool_names,
    )
    return _scrub_payload(res)


@mcp.tool(description="Start a multi-browser site audit run for a confirmed session_token and run the initial DevTools sweep.")
async def site_audit_start(
    url: str,
    run_id: str,
    session_token: str,
    headless: bool = True,
    panels: str | list[str] = "all",
) -> dict[str, Any]:
    """Begin multi-browser DevTools site audit strictly after session_confirm authorization."""
    sess = _authorize_v2_tool(run_id, "site_audit_start", session_token)
    sess["policy"].assert_action_allowed("navigate", target_url=url)
    res = await _SITE_COORDINATOR.start_and_run_round(run_id, headless=headless, panels=panels, target_url=url)
    return _scrub_payload(res)


@mcp.tool(description="Execute another multi-browser DevTools inspection, verification, and honesty-audit round for an active site_audit run_id.")
async def site_audit_round(
    run_id: str,
    headless: bool = True,
    panels: str | list[str] = "all",
    session_token: str = "",
) -> dict[str, Any]:
    """Execute one multi-browser site audit round on an existing confirmed session."""
    _authorize_v2_tool(run_id, "site_audit_round", session_token)
    res = await _SITE_COORDINATOR.start_and_run_round(run_id, headless=headless, panels=panels)
    return _scrub_payload(res)


@mcp.tool(description="Return confirmed/retracted/rejected claim counts, vault integrity, and details for a site_audit run_id.")
async def site_audit_status(run_id: str, session_token: str = "") -> dict[str, Any]:
    """Inspect status and EvidenceVault chain validity for a site audit run."""
    _authorize_v2_tool(run_id, "site_audit_status", session_token)
    res = await asyncio.to_thread(_SITE_COORDINATOR.status, run_id)
    return _scrub_payload(res)


@mcp.tool(description="List live or registered [mcp_<browser>] cursor workers, PIDs, ports, and states for a run_id.")
async def browser_cursor_list(run_id: str, session_token: str = "") -> dict[str, Any]:
    """List [mcp_<browser>] cursor instances belonging to run_id."""
    _authorize_v2_tool(run_id, "browser_cursor_list", session_token)
    res = await asyncio.to_thread(_SITE_COORDINATOR.sessions.browser_cursor_list, run_id)
    return _scrub_payload(res)


@mcp.tool(description="Run targeted DevTools panel inspection (Elements, Console, Network, Application, Performance/Sensors) on one granted browser.")
async def inspect_panel(
    run_id: str,
    browser: str,
    panel: str,
    args: dict[str, Any] | None = None,
    session_token: str = "",
) -> dict[str, Any]:
    """Inspect one specific DevTools panel on a granted browser cursor."""
    _authorize_v2_tool(run_id, "inspect_panel", session_token)
    res = await _SITE_COORDINATOR.inspect_panel(run_id, browser, panel, args)
    return _scrub_payload(res)


@mcp.tool(description="Run a read-only project audit and optionally link site stack frames to local source files via source maps.")
async def project_audit_start(
    project_path: str,
    site_run_id: str = "",
    mode: str = "read_only",
    session_token: str = "",
) -> dict[str, Any]:
    """Audit a local project and optionally link findings to an existing site run via source maps."""
    if mode != "read_only":
        raise PermissionError("project_audit_start enforces read_only mode only.")
    if project_path.startswith("-"):
        raise ValueError("Invalid project_path")
    sess: dict[str, Any] | None = None
    if site_run_id:
        sess = _authorize_v2_tool(site_run_id, "project_audit_start", session_token)
    started = await asyncio.to_thread(_LOOP_OPERATOR.start, project_path, mode="read_only", max_rounds=2)
    rnd = await _LOOP_OPERATOR.run_round(started["run_id"], auto_generate=False)
    _rdir, _st, ledger, _cov = await asyncio.to_thread(_LOOP_OPERATOR.load_run, started["run_id"])
    proj_findings = [
        {"id": f.id, "file": f.location.file, "line": f.location.line_start, "title": f.title}
        for f in ledger.findings
    ]
    linked: list[dict[str, Any]] = []
    if site_run_id and sess is not None:
        rdir = Path(sess["run_dir"])
        v = EvidenceVault(rdir)
        sb = AgentScoreboard(rdir)
        cl = ClaimLedger(rdir, vault=v, scoreboard=sb)
        site_list = [c.model_dump() for c in cl.claims]
        smaps_path = rdir / "source_maps.json"
        source_maps: dict[str, dict[str, Any]] = {}
        if smaps_path.is_file():
            import json

            source_maps = json.loads(smaps_path.read_text(encoding="utf-8"))
        linked = link_site_and_project_findings(
            site_findings=site_list,
            project_findings=proj_findings,
            source_maps=source_maps,
            project_path=project_path,
        )
    return _scrub_payload(
        {
            "project_run_id": started["run_id"],
            "round": rnd,
            "project_findings_count": len(proj_findings),
            "linked_findings": linked or proj_findings,
        },
        base_dir=project_path,
    )


@mcp.tool(description="Build Section 1 & 12 REPORT.md, Chromium REPORT.pdf, report.json, per-finding folders, and unverified_leads.md from CONFIRMED claims only.")
async def report_build(
    run_id: str,
    formats: list[str] | None = None,
    use_llm_analysis: bool = False,
    session_token: str = "",
) -> dict[str, Any]:
    """Render REPORT.md and REPORT.pdf strictly from verified CONFIRMED findings."""
    sess = _authorize_v2_tool(run_id, "report_build", session_token)
    rdir = Path(sess["run_dir"])
    vault = EvidenceVault(rdir)
    sb = AgentScoreboard(rdir)
    ledger = ClaimLedger(rdir, vault=vault, scoreboard=sb)
    analysis = None
    if use_llm_analysis:
        analysis = await analyze_findings_cross_vendor(ledger=ledger, vault=vault)
    res = await asyncio.to_thread(
        build_v2_report_bundle,
        rdir,
        formats=tuple(formats or ["md", "pdf"]),
        analysis_summary=analysis,
        allow_fallback_pdf=True,
    )
    if analysis is not None:
        res["analysis"] = analysis
    return _scrub_payload(res)


@mcp.tool(description="Build standalone verification pack (verify/verify.py stdlib-only, VERIFY_PROMPT.md, claims.json, README.txt) for an audit run folder.")
async def verify_pack_build(run_id: str, session_token: str = "") -> dict[str, Any]:
    """Generate offline verify/ pack and VERIFY_PROMPT.md for independent coding-agent verification."""
    sess = _authorize_v2_tool(run_id, "verify_pack_build", session_token)
    res = await asyncio.to_thread(build_verify_pack, Path(sess["run_dir"]))
    return _scrub_payload(res)


@mcp.tool(description="Retract a claim from an audit run; entries are preserved permanently in agents/corrections_log.md and raise self-correction honesty score.")
async def claim_retract(
    run_id: str,
    claim_id: str,
    reason: str,
    agent_name: str = "self",
    session_token: str = "",
) -> dict[str, Any]:
    """Retract an inaccurate or uncertain claim without deleting history."""
    sess = _authorize_v2_tool(run_id, "claim_retract", session_token)
    rdir = Path(sess["run_dir"])
    vault = EvidenceVault(rdir)
    sb = AgentScoreboard(rdir)
    ledger = ClaimLedger(rdir, vault=vault, scoreboard=sb)
    updated = await asyncio.to_thread(ledger.retract_claim, claim_id, reason=reason, by_agent=agent_name)
    return _scrub_payload(updated.model_dump())


@mcp.tool(description="Return agent honesty, precision, Brier calibration, self-correction rate, and quarantine status for a run or cumulative scoreboard.")
async def agent_scoreboard(run_id: str | None = None, session_token: str = "") -> dict[str, Any]:
    """Return agent reliability scoreboard for run_id or cumulative .bugarena/agent_scores.json."""
    if run_id:
        sess = _authorize_v2_tool(run_id, "agent_scoreboard", session_token)
        sb = AgentScoreboard(Path(sess["run_dir"]))
        return _scrub_payload({"run_id": run_id, "agents": {k: v.model_dump() for k, v in sb.all_scores().items()}})
    import json

    gpath = Path(".bugarena/agent_scores.json")
    if gpath.is_file():
        txt = await asyncio.to_thread(gpath.read_text, encoding="utf-8")
        return _scrub_payload(json.loads(txt))
    return {"agents": {}}


@mcp.tool(description="Quarantine, security-scan, compatibility-test, and merge an external bug-detecting skill while keeping BugArena as immutable primary MCP.")
async def merge_both_skills(
    skill_source: str,
    name: str | None = None,
    dry_run: bool = True,
    approved: bool = False,
    output_root: str = "merged",
) -> dict[str, Any]:
    """Safely inspect (dry_run=True default) or merge a third-party skill into merged/<name>/."""
    res = await asyncio.to_thread(
        _merge_both_skills_impl,
        skill_source,
        name=name,
        dry_run=dry_run,
        approved=approved,
        output_root=output_root,
    )
    return _scrub_payload(res)


def main():
    """CLI server entrypoint."""
    mcp.run()


if __name__ == "__main__":
    main()
