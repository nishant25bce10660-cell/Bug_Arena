"""LoopOperator: multi-round, resume-safe audit orchestrator with stop conditions."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from bugarena.audit.coverage import (
    CoverageMatrix,
    build_coverage_matrix,
    classify_area,
    mark_area_coverage,
    save_coverage_matrix,
)
from bugarena.audit.dedupe import merge_or_insert_draft
from bugarena.audit.evaluator import AgentEvaluator, AgentScorecard
from bugarena.audit.ledger import Finding, FindingLedger, FindingState
from bugarena.audit.report import generate_audit_report
from bugarena.audit.tools import tool_git_ls
from bugarena.audit.verify import verify_finding

if TYPE_CHECKING:
    from bugarena.agents.runner import AgentLLMCaller


class RoundSummary(BaseModel):
    """Per-round metrics matching Section 11 status reporting."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    round_num: int
    new: int
    confirmed: int
    dismissed: int
    fixed: int
    open_confirmed: int
    coverage_pct: float
    agents_used: tuple[str, ...] = ()
    scorecards: tuple[AgentScorecard, ...] = ()
    status_line: str = ""


class LoopState(BaseModel):
    """Persisted resume-safe loop state stored under .bugarena/loop_state.json."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    repo_path: str
    mode: str = "read_only"
    max_rounds: int = 6
    current_round: int = 0
    baseline_head: str = ""
    agents: tuple[str, ...] = ()
    quarantined_agents: tuple[str, ...] = ()
    invalid_json_counts: dict[str, int] = Field(default_factory=dict)
    round_history: tuple[RoundSummary, ...] = ()
    last_ledger_digest: str = ""
    consecutive_identical_rounds: int = 0
    stop_reason: str = ""
    updated_at: str = ""


def _git_head(repo: Path) -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        return res.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _ledger_digest(ledger: FindingLedger) -> str:
    summary = [(f.id, f.state.value, f.location.file, f.title) for f in ledger.findings]
    return json.dumps(summary, sort_keys=True)


class LoopOperator:
    """Orchestrates multi-round specialist sweeps, independent verification, dedupe, and reporting."""

    def __init__(self, state_root: Path | str | None = None):
        from bugarena.agents.registry import build_agent_registry
        from bugarena.agents.runner import AgentRunner

        self.state_root = Path(state_root) if state_root else None
        self.registry = build_agent_registry()
        self.runner = AgentRunner()
        self.evaluator = AgentEvaluator()
        self._run_dirs: dict[str, Path] = {}

    def _run_dir(self, repo_path: Path, run_id: str) -> Path:
        base = self.state_root or (repo_path / ".bugarena")
        return base / "runs" / run_id

    @staticmethod
    def _atomic_write_json(target: Path, payload: str) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".state_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_name, target)
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
        return target

    def _find_run_dir(self, run_id: str, repo_hint: Path | str | None = None) -> Path:
        if run_id in self._run_dirs and (self._run_dirs[run_id] / "loop_state.json").is_file():
            return self._run_dirs[run_id]
        candidates: list[Path] = []
        if self.state_root:
            candidates.append(self.state_root / "runs" / run_id)
        if repo_hint:
            candidates.append(Path(repo_hint).resolve() / ".bugarena" / "runs" / run_id)
        candidates.append(Path(".bugarena").resolve() / "runs" / run_id)
        for cand in candidates:
            if (cand / "loop_state.json").is_file():
                return cand
        # Scan .bugarena/runs under cwd just in case
        cwd_runs = Path(".bugarena/runs")
        if cwd_runs.is_dir():
            target = cwd_runs / run_id
            if (target / "loop_state.json").is_file():
                return target
        raise FileNotFoundError(f"Audit run_id '{run_id}' not found.")

    def load_run(
        self, run_id: str, repo_hint: Path | str | None = None
    ) -> tuple[Path, LoopState, FindingLedger, CoverageMatrix]:
        """Load LoopState, FindingLedger, and CoverageMatrix for an existing run_id."""
        rdir = self._find_run_dir(run_id, repo_hint=repo_hint)
        state = LoopState.model_validate_json((rdir / "loop_state.json").read_text(encoding="utf-8"))
        ledger = FindingLedger(rdir / "ledger.json")
        cov_raw = (rdir / "coverage.json").read_text(encoding="utf-8")
        coverage = CoverageMatrix.model_validate_json(cov_raw)
        return rdir, state, ledger, coverage

    def start(
        self,
        repo_path: Path | str,
        *,
        mode: str = "read_only",
        max_rounds: int = 6,
        agents: list[str] | tuple[str, ...] | None = None,
        initial_findings: tuple[Finding, ...] = (),
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Initialize a new audit run, baseline snapshot, ledger, and coverage matrix."""
        if mode not in ("read_only", "fix"):
            raise ValueError(f"Unsupported mode {mode!r}; expected 'read_only' or 'fix'")
        repo = Path(repo_path).resolve()
        if not repo.is_dir():
            raise FileNotFoundError(f"Repository directory does not exist: {repo}")

        from bugarena.agents.registry import SWEEP_ROLES

        rid = run_id or f"audit_{uuid.uuid4().hex[:8]}"
        selected = tuple(agents) if agents is not None else SWEEP_ROLES
        for name in selected:
            if name not in self.registry:
                raise KeyError(f"Unknown agent role '{name}'")

        rdir = self._run_dir(repo, rid)
        rdir.mkdir(parents=True, exist_ok=True)
        self._run_dirs[rid] = rdir
        head = _git_head(repo)
        tracked = tool_git_ls(repo)

        ledger = FindingLedger(rdir / "ledger.json")
        for f in initial_findings:
            ledger.upsert(f)
        ledger.save(baseline_head=head, branch="")

        coverage = build_coverage_matrix(repo, tracked, ledger.findings)
        save_coverage_matrix(coverage, rdir / "coverage.json")

        state = LoopState(
            run_id=rid,
            repo_path=str(repo),
            mode=mode,
            max_rounds=max(1, min(max_rounds, 6)),
            current_round=0,
            baseline_head=head,
            agents=selected,
            last_ledger_digest=_ledger_digest(ledger),
            updated_at=datetime.now(UTC).isoformat(),
        )
        self._atomic_write_json(rdir / "loop_state.json", state.model_dump_json(indent=2))

        return {
            "run_id": rid,
            "repo_path": str(repo),
            "mode": mode,
            "max_rounds": state.max_rounds,
            "baseline_head": head,
            "areas_count": len(coverage.areas),
            "initial_findings_count": len(ledger.findings),
            "agents": list(selected),
        }

    async def run_round(
        self,
        run_id: str,
        *,
        auto_generate: bool = False,
        llm_caller: AgentLLMCaller | None = None,
        repo_hint: Path | str | None = None,
    ) -> dict[str, Any]:
        """Execute one full round: sweep -> verify -> dedupe -> coverage -> evaluate."""
        rdir, state, ledger, coverage = self.load_run(run_id, repo_hint=repo_hint)

        if state.current_round >= state.max_rounds:
            return {
                "run_id": run_id,
                "stopped": True,
                "stop_reason": f"Hard cap {state.max_rounds} rounds reached.",
                "status": self.status(run_id, repo_hint=state.repo_path),
            }

        next_round = state.current_round + 1
        repo = Path(state.repo_path)
        quarantined = set(state.quarantined_agents)
        bad_json = dict(state.invalid_json_counts)
        active_agents = [a for a in state.agents if a not in quarantined]

        sem = asyncio.Semaphore(4)

        async def _run_one(role_name: str):
            async with sem:
                spec = self.registry[role_name]
                return await self.runner.run_agent(
                    spec,
                    repo,
                    existing_findings=ledger.findings,
                    auto_generate=auto_generate,
                    llm_caller=llm_caller,
                )

        results = await asyncio.gather(*[_run_one(a) for a in active_agents])

        # Track invalid JSON quarantine (Section 9 anti-stall rule)
        for res in results:
            if res.invalid_json_error:
                bad_json[res.agent_name] = bad_json.get(res.agent_name, 0) + 1
                if bad_json[res.agent_name] >= 2:
                    quarantined.add(res.agent_name)

        # Dedupe + insert drafts
        new_count = 0
        touched_ids: list[str] = []
        for res in results:
            for draft in res.findings:
                finding, is_new = merge_or_insert_draft(ledger, draft, round_num=next_round)
                touched_ids.append(finding.id)
                if is_new:
                    new_count += 1

        # Verify all unverified / suspected findings using independent agent != found_by
        confirmed_this_round = 0
        dismissed_this_round = 0
        to_verify = [
            f.id
            for f in ledger.findings
            if f.state in (FindingState.SUSPECTED, FindingState.REPRODUCED)
        ]
        for fid in to_verify:
            before_state = ledger.get(fid).state if ledger.get(fid) else None
            updated = await asyncio.to_thread(verify_finding, repo, ledger, fid)
            if updated.state == FindingState.CONFIRMED and before_state != FindingState.CONFIRMED:
                confirmed_this_round += 1
            elif updated.state == FindingState.DISMISSED and before_state != FindingState.DISMISSED:
                dismissed_this_round += 1

        # Update coverage matrix across every discovered area (all areas read during full sweep)
        for area in coverage.areas:
            coverage = mark_area_coverage(coverage, area.area, static_read=True)
        for f in ledger.findings:
            f_area = classify_area(f.location.file)
            coverage = mark_area_coverage(
                coverage,
                f_area,
                static_read=True,
                dynamic_probe=True if f.evidence_type.value == "DYNAMIC" else None,
                agent_name=f.found_by,
                finding_id=f.id,
            )

        scorecards = self.evaluator.evaluate_round(
            results, ledger.findings, invalid_json_counts=bad_json
        )

        # Anti-stall check & stop condition check
        new_digest = _ledger_digest(ledger)
        identical = (new_digest == state.last_ledger_digest) and state.current_round > 0
        consec = (state.consecutive_identical_rounds + 1) if identical else 0

        counts = ledger.counts()
        open_conf = counts.get(FindingState.CONFIRMED.value, 0)
        fixed_cnt = counts.get(FindingState.FIXED.value, 0)

        stop_reason = ""
        if consec >= 2:
            stop_reason = "Anti-stall: two consecutive rounds produced identical ledgers."
        elif new_count == 0 and confirmed_this_round == 0 and coverage.coverage_pct >= 100.0 and next_round >= 2:
            stop_reason = "Converged: zero new confirmed findings and 100% coverage."
        elif next_round >= state.max_rounds:
            stop_reason = f"Reached max rounds ({state.max_rounds})."

        status_line = (
            f"ROUND {next_round} | new: {new_count} | confirmed: {confirmed_this_round} "
            f"| dismissed: {dismissed_this_round} | fixed: {fixed_cnt} | open: {open_conf}"
        )
        summary = RoundSummary(
            round_num=next_round,
            new=new_count,
            confirmed=confirmed_this_round,
            dismissed=dismissed_this_round,
            fixed=fixed_cnt,
            open_confirmed=open_conf,
            coverage_pct=coverage.coverage_pct,
            agents_used=tuple(active_agents),
            scorecards=tuple(scorecards),
            status_line=status_line,
        )

        new_state = state.model_copy(
            update={
                "current_round": next_round,
                "quarantined_agents": tuple(sorted(quarantined)),
                "invalid_json_counts": bad_json,
                "round_history": (*state.round_history, summary),
                "last_ledger_digest": new_digest,
                "consecutive_identical_rounds": consec,
                "stop_reason": stop_reason,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        ledger.save()
        save_coverage_matrix(coverage, rdir / "coverage.json")
        self._atomic_write_json(rdir / "loop_state.json", new_state.model_dump_json(indent=2))

        return {
            "run_id": run_id,
            "round": next_round,
            "summary": summary.model_dump(),
            "counts": counts,
            "coverage_pct": coverage.coverage_pct,
            "stop_reason": stop_reason,
            "quarantined_agents": list(new_state.quarantined_agents),
        }

    def verify_one(
        self, run_id: str, finding_id: str, *, repo_hint: Path | str | None = None
    ) -> dict[str, Any]:
        """Force independent re-verification of one ledger finding."""
        _rdir, state, ledger, _coverage = self.load_run(run_id, repo_hint=repo_hint)
        updated = verify_finding(state.repo_path, ledger, finding_id)
        ledger.save()
        return {
            "run_id": run_id,
            "finding": updated.model_dump(),
        }

    def status(self, run_id: str, *, repo_hint: Path | str | None = None) -> dict[str, Any]:
        """Return ledger counts, coverage %, and stop-condition state."""
        _rdir, state, ledger, coverage = self.load_run(run_id, repo_hint=repo_hint)
        counts = ledger.counts()
        last_summary = state.round_history[-1].model_dump() if state.round_history else None
        stop_met = bool(state.stop_reason) or (
            state.current_round >= state.max_rounds
        )
        return {
            "run_id": run_id,
            "repo_path": state.repo_path,
            "mode": state.mode,
            "current_round": state.current_round,
            "max_rounds": state.max_rounds,
            "coverage_pct": coverage.coverage_pct,
            "counts": counts,
            "stop_condition_met": stop_met,
            "stop_reason": state.stop_reason,
            "quarantined_agents": list(state.quarantined_agents),
            "last_round": last_summary,
        }

    def report(
        self,
        run_id: str,
        *,
        format: str = "markdown",
        output_file: Path | str | None = None,
        repo_hint: Path | str | None = None,
    ) -> dict[str, Any]:
        """Generate evidence-graded Markdown or JSON report for run_id."""
        rdir, state, ledger, coverage = self.load_run(run_id, repo_hint=repo_hint)
        last_cards = state.round_history[-1].scorecards if state.round_history else ()
        target = output_file or (rdir / ("report.json" if format == "json" else "report.md"))
        return generate_audit_report(
            state.repo_path,
            ledger,
            coverage,
            baseline_head=state.baseline_head,
            rounds_run=state.current_round,
            agents_used=state.agents,
            agents_unavailable=state.quarantined_agents,
            commands_run=("ast_scan", "ruff_json", "radon_cc", "pytest_run", "probe_run"),
            scorecards=last_cards,
            read_only_mode=(state.mode == "read_only"),
            format=format,
            output_path=target,
        )
