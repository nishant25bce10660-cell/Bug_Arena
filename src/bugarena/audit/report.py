"""Evidence-graded audit report generator (Markdown + JSON) with appendices and git proof."""

from __future__ import annotations

import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bugarena.audit.coverage import CoverageMatrix
from bugarena.audit.evaluator import AgentScorecard
from bugarena.audit.ledger import EvidenceType, Finding, FindingLedger, FindingState, SeverityLevel
from bugarena.sandbox.security import scrub_sensitive_data

SEVERITY_ORDER = {
    SeverityLevel.CRITICAL: 0,
    SeverityLevel.HIGH: 1,
    SeverityLevel.MEDIUM: 2,
    SeverityLevel.LOW: 3,
}


def _git_integrity_info(repo: Path) -> dict[str, str]:
    def _run(args: list[str]) -> str:
        try:
            res = subprocess.run(
                args, cwd=str(repo), capture_output=True, text=True, timeout=5.0, check=False
            )
            return res.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return "unavailable"

    return {
        "head": _run(["git", "rev-parse", "HEAD"]),
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "status_short": _run(["git", "status", "--short"]),
    }


def _cluster_findings(findings: tuple[Finding, ...]) -> dict[str, list[str]]:
    clusters: dict[str, list[str]] = {
        "Injection & Execution Containment": [],
        "Path Boundary & Secret Scrubbing": [],
        "Patch Parsing & Application": [],
        "Evaluation, AST & Red-Baseline Gates": [],
        "LLM Dispatcher, Server State & Models": [],
        "Tests, Packaging & Documentation": [],
    }
    for f in findings:
        if f.state == FindingState.DISMISSED:
            continue
        cat = f.category.lower()
        file_l = f.location.file.lower()
        if any(k in file_l for k in ("test_generator", "red_validator", "runner.py", "evaluation")):
            if "security" in cat or "rce" in f.title.lower() or "option" in f.title.lower():
                clusters["Injection & Execution Containment"].append(f.id)
            else:
                clusters["Evaluation, AST & Red-Baseline Gates"].append(f.id)
        elif "security" in file_l or "config.py" in file_l or "secret" in f.title.lower():
            clusters["Path Boundary & Secret Scrubbing"].append(f.id)
        elif "patch_parser" in file_l or "manager.py" in file_l:
            clusters["Patch Parsing & Application"].append(f.id)
        elif any(k in file_l for k in ("dispatcher", "server.py", "models/")):
            clusters["LLM Dispatcher, Server State & Models"].append(f.id)
        else:
            clusters["Tests, Packaging & Documentation"].append(f.id)
    return clusters


def generate_audit_report(
    repo_path: Path | str,
    ledger: FindingLedger,
    coverage: CoverageMatrix,
    *,
    baseline_head: str = "",
    rounds_run: int = 0,
    agents_used: list[str] | tuple[str, ...] = (),
    agents_unavailable: list[str] | tuple[str, ...] = (),
    commands_run: list[str] | tuple[str, ...] = (),
    scorecards: list[AgentScorecard] | tuple[AgentScorecard, ...] = (),
    read_only_mode: bool = True,
    format: str = "markdown",
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Build and optionally write the evidence-graded Markdown or JSON audit report."""
    repo = Path(repo_path).resolve()
    git_info = _git_integrity_info(repo)
    findings = ledger.findings

    # Counts by severity and evidence type
    sev_by_ev: dict[str, dict[str, int]] = {
        s.value: {e.value: 0 for e in EvidenceType} for s in SeverityLevel
    }
    for f in findings:
        if f.state == FindingState.DISMISSED:
            continue
        sev_by_ev[f.proposed_severity.value][f.evidence_type.value] += 1

    active = [
        f
        for f in findings
        if f.state not in (FindingState.DISMISSED, FindingState.UNVERIFIED)
    ]
    active.sort(key=lambda f: (SEVERITY_ORDER.get(f.proposed_severity, 9), f.id))
    dismissed = [f for f in findings if f.state == FindingState.DISMISSED]
    unverified = [f for f in findings if f.state == FindingState.UNVERIFIED]
    clusters = _cluster_findings(findings)

    top_risks = [
        f"`{f.id}` ({f.proposed_severity.value}): {f.title}"
        for f in active[:5]
    ]

    lines: list[str] = [
        "# BugArena Audit Report",
        "",
        "## 1. Executive Summary",
        f"- **Project:** `{repo.name}`",
        f"- **Stack:** Python {platform.python_version()}, MCPServer, Pydantic v2, pytest, ruff, radon",
        f"- **Baseline HEAD:** `{baseline_head or ledger.baseline_head or git_info['head']}`",
        f"- **Current HEAD:** `{git_info['head']}` (`{git_info['branch']}`)",
        f"- **Generated:** `{datetime.now(UTC).isoformat()}`",
        f"- **Rounds Run:** `{rounds_run}`",
        f"- **Coverage:** `{coverage.coverage_pct}%` across `{len(coverage.areas)}` areas",
        "",
        "### Severity Counts by Evidence Type",
        "| Severity | DYNAMIC | STATIC | DOC_COMPARE |",
        "| :--- | :---: | :---: | :---: |",
    ]
    for s in SeverityLevel:
        row = sev_by_ev[s.value]
        lines.append(
            f"| **{s.value}** | {row['DYNAMIC']} | {row['STATIC']} | {row['DOC_COMPARE']} |"
        )
    lines.append("")
    lines.append("### Top Risks")
    if top_risks:
        for r in top_risks:
            lines.append(f"- {r}")
    else:
        lines.append("- None open.")
    lines.append("")

    lines.extend([
        "## 2. Coverage and Method",
        f"- **Agents Used ({len(agents_used)}):** {', '.join(f'`{a}`' for a in agents_used) or 'none'}",
        f"- **Agents Unavailable / Skipped:** {', '.join(f'`{a}`' for a in agents_unavailable) or 'none'}",
        f"- **Commands Run:** {', '.join(f'`{c}`' for c in commands_run) or 'none'}",
        "",
        "| Area | Files | Static | Dynamic Probe | Test Exists | Findings |",
        "| :--- | :---: | :---: | :---: | :---: | :--- |",
    ])
    for area in coverage.areas:
        lines.append(
            f"| `{area.area}` | {len(area.files)} | {'YES' if area.static_read else 'NO'} "
            f"| {'YES' if area.dynamic_probe else 'NO'} | {'YES' if area.test_exists else 'NO'} "
            f"| {', '.join(area.findings_ids) or '-'} |"
        )
    lines.append("")

    lines.append("## 3. Confirmed & Tracked Findings")
    if not active:
        lines.append("No active findings.")
    for f in active:
        lines.extend([
            f"### {f.id} — {f.title}",
            f"- **Severity:** {f.proposed_severity.value} ({f.severity_justification}) | **State:** `{f.state.value}` | **Evidence:** `{f.evidence_type.value}`",
            f"- **Location:** `{f.location.file}:{f.location.line_start}-{f.location.line_end}` (`{f.location.symbol}`)",
            f"- **Found by:** `{f.found_by}` | **Verified by:** `{f.verified_by or 'pending'}` | **Cross-refs:** `{', '.join(f.cross_refs) or '-'}`",
            f"- **What it is:** {f.what_it_is}",
            f"- **What it does:** {f.what_it_does}",
            f"- **Root cause:** {f.root_cause}",
            f"- **How to reproduce:** Inputs: `{f.repro.inputs}` -> Expected: `{f.repro.expected}` -> Actual: `{f.repro.actual}`",
            f"- **Evidence (`{f.evidence_type.value}`):**",
            "```text",
            scrub_sensitive_data(f.verification_output or "STATIC observation (not dynamically executed)")[:1200],
            "```",
            f"- **Fix applied / commit:** `{f.commit_hash or 'NOT APPLIED (audit/queued)'}`",
            f"- **Regression test path:** `{f.regression_test_path or f.regression_test_idea}`",
            f"- **Risks:** {f.risks}",
            "",
        ])

    lines.append("## 4. Appendix A — Dismissed Hypotheses")
    if not dismissed:
        lines.append("None.")
    for f in dismissed:
        lines.extend([
            f"- **`{f.id}` — {f.title}** (`found_by={f.found_by}`, `verified_by={f.verified_by}`)",
            f"  - Disproving output: `{scrub_sensitive_data(f.verification_output)[:400]}`",
        ])
    lines.append("")

    lines.append("## 5. Appendix B — Unverified Claims")
    if not unverified:
        lines.append("None.")
    for f in unverified:
        lines.append(
            f"- **`{f.id}` — {f.title}** (`{f.evidence_type.value}`): {f.verification_output[:300]}"
        )
    lines.append("")

    lines.append("## 6. Appendix C — Systemic Clusters & Agent-Evaluator Scorecard")
    for cname, cids in clusters.items():
        if cids:
            lines.append(f"- **{cname}:** {', '.join(cids)}")
    lines.append("")
    if scorecards:
        lines.extend([
            "| Agent | Submitted | Confirmed | Dismissed | Dupes | Dynamic % | Precision % | Status |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
        ])
        for sc in scorecards:
            lines.append(
                f"| `{sc.agent_name}` | {sc.submitted} | {sc.confirmed} | {sc.dismissed} "
                f"| {sc.duplicates} | {sc.evidence_quality_pct}% | {sc.precision_pct}% | `{sc.recommendation}` |"
            )
    lines.append("")

    lines.extend([
        "## 7. Integrity Check",
        f"- **Baseline HEAD:** `{baseline_head or ledger.baseline_head or git_info['head']}`",
        f"- **Final HEAD:** `{git_info['head']}`",
        f"- **Branch:** `{git_info['branch']}`",
        "- **`git status --short`:**",
        "```text",
        git_info["status_short"] or "<clean>",
        "```",
    ])
    if read_only_mode:
        lines.append("- **Integrity statement:** Audit ran strictly read-only on tracked repository files.")

    markdown = scrub_sensitive_data("\n".join(lines), base_dir=repo)
    json_payload = {
        "baseline_head": baseline_head or ledger.baseline_head or git_info["head"],
        "final_head": git_info["head"],
        "branch": git_info["branch"],
        "rounds_run": rounds_run,
        "coverage_pct": coverage.coverage_pct,
        "severity_counts_by_evidence": sev_by_ev,
        "state_counts": ledger.counts(),
        "findings": [f.model_dump() for f in findings],
        "scorecards": [sc.model_dump() for sc in scorecards],
        "clusters": clusters,
    }

    written_path: str | None = None
    if output_path is not None:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        if format == "json":
            out_p.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")
        else:
            out_p.write_text(markdown, encoding="utf-8")
        written_path = str(out_p)

    return {
        "format": format,
        "report_path": written_path,
        "markdown": markdown if format != "json" else "",
        "report_json": json_payload,
    }
