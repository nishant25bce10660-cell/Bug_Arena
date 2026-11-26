"""Test-first candidate fix loop engine (Red -> Candidates -> Gates -> Completeness -> Score)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from bugarena.audit.ledger import Finding, FindingState
from bugarena.audit.loop import LoopOperator
from bugarena.audit.probes import run_isolated_probe
from bugarena.evaluation.test_runner import PatchEvaluator
from bugarena.models.agent import CandidatePatch
from bugarena.models.bug import BugSpec
from bugarena.models.repro import ReproTestSpec
from bugarena.sandbox.security import scrub_sensitive_data
from bugarena.tournament.patch_parser import PatchValidationError, parse_and_validate_patch
from bugarena.tournament.runner import TournamentRunner


async def run_fix_loop_session(
    operator: LoopOperator,
    run_id: str,
    *,
    finding_ids: list[str] | None = None,
    auto_generate: bool = False,
    candidate_patches_by_id: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """
    Execute non-destructive sandbox evaluation/fix simulation for CONFIRMED ledger findings.
    If auto_generate=True, invokes TournamentRunner (MultiModelDispatcher) per finding;
    otherwise uses supplied candidate_patches_by_id or reports ready queue state cleanly.
    """
    _rdir, state, ledger, _coverage = operator.load_run(run_id)
    repo = Path(state.repo_path).resolve()

    targets: list[Finding] = []
    for f in ledger.findings:
        if finding_ids is not None and f.id not in finding_ids:
            continue
        if f.state == FindingState.CONFIRMED:
            targets.append(f)

    results: list[dict[str, Any]] = []
    runner = TournamentRunner() if auto_generate else None
    evaluator = PatchEvaluator(base_repo_path=repo)

    for finding in targets:
        # Step 1 (RED check): verify finding's probe reproduces in isolated sandbox
        if not finding.repro.probe_script.strip():
            results.append(
                {
                    "finding_id": finding.id,
                    "status": "SKIPPED_NO_PROBE",
                    "reason": "Finding has no executable probe_script for automated Red baseline.",
                }
            )
            continue

        red_outcome = await asyncio.to_thread(
            run_isolated_probe, repo, finding.repro.probe_script
        )
        if red_outcome.exit_code == 0 and "REPRODUCED:" not in red_outcome.stdout:
            results.append(
                {
                    "finding_id": finding.id,
                    "status": "ALREADY_GREEN",
                    "output": scrub_sensitive_data(red_outcome.stdout, base_dir=repo),
                }
            )
            continue

        # Step 2 (CANDIDATES): collect patches (only call paid LLM if auto_generate=True)
        candidates: list[CandidatePatch] = []
        raw_list = (candidate_patches_by_id or {}).get(finding.id, [])
        repro_rel = f"tests/regression/test_{finding.id.lower().replace('-', '_')}.py"
        for item in raw_list:
            try:
                candidates.append(
                    parse_and_validate_patch(
                        raw_diff=item["diff"],
                        persona=item.get("persona", "surgical_minimalist"),
                        explanation=item.get("explanation", ""),
                        candidate_id=item.get("candidate_id"),
                        protected_paths=[repro_rel],
                    )
                )
            except (KeyError, ValueError, PatchValidationError):
                continue

        if auto_generate and runner is not None and not candidates:
            bug_spec = BugSpec(
                bug_id=finding.id,
                repo_path=str(repo),
                error_log=f"{finding.what_it_is}\n{finding.repro.actual}",
                hint=finding.suggested_fix,
            )
            repro_spec = ReproTestSpec(
                test_file_path=repro_rel,
                test_code=finding.repro.probe_script,
                red_baseline_verified=True,
                initial_outcome=red_outcome,
            )
            _tid, gen_cands = await runner.run_tournament(bug_spec, repro_spec)
            candidates.extend(gen_cands)

        if not candidates:
            results.append(
                {
                    "finding_id": finding.id,
                    "status": "QUEUED_FOR_FIX",
                    "red_verified": True,
                    "auto_generate": auto_generate,
                }
            )
            continue

        repro_spec = ReproTestSpec(
            test_file_path=repro_rel,
            test_code=(
                "import subprocess, sys\n"
                f"def test_{finding.id.lower().replace('-', '_').replace('.', '_')}():\n"
                f"    script = {finding.repro.probe_script!r}\n"
                "    res = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)\n"
                "    assert res.returncode == 0 and 'REPRODUCED:' not in res.stdout, res.stdout + res.stderr\n"
            ),
            red_baseline_verified=True,
            initial_outcome=red_outcome,
        )
        evals, champion_id = await asyncio.to_thread(
            evaluator.evaluate_candidates, candidates, repro_spec
        )
        results.append(
            {
                "finding_id": finding.id,
                "status": "EVALUATED",
                "champion_candidate_id": champion_id,
                "evaluations": [e.model_dump() for e in evals],
            }
        )

    return {
        "run_id": run_id,
        "repo_path": str(repo),
        "auto_generate": auto_generate,
        "processed_count": len(results),
        "results": results,
    }
