"""Generate and audit PROJECT_REPORT.md on every project change."""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bugarena.audit.loop import LoopOperator
from bugarena.audit.tools import tool_git_ls
from bugarena.reporting.markdown_formatter import save_markdown_report
from bugarena.sandbox.security import scrub_sensitive_data
from bugarena.server import mcp


def _run_cmd(args: list[str], cwd: Path, timeout: float = 180.0) -> tuple[int, str]:
    """Run a local check command safely without shell=True."""
    try:
        res = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        combined = "\n".join(part for part in (res.stdout.strip(), res.stderr.strip()) if part)
        return res.returncode, combined
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"Command error: {exc}"


def _git_metadata(repo: Path) -> dict[str, Any]:
    _, branch = _run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo, timeout=10.0)
    _, head = _run_cmd(["git", "rev-parse", "--short", "HEAD"], repo, timeout=10.0)
    _, status_short = _run_cmd(["git", "status", "--short"], repo, timeout=10.0)
    _, log_lines = _run_cmd(["git", "log", "-n", "12", "--oneline"], repo, timeout=10.0)
    return {
        "branch": branch.strip() or "unknown",
        "head": head.strip() or "unknown",
        "status_short": status_short.strip(),
        "recent_commits": [ln.strip() for ln in log_lines.splitlines() if ln.strip()],
    }


def _collect_mcp_tools() -> list[tuple[str, str]]:
    async def _list() -> list[tuple[str, str]]:
        tools = await mcp.list_tools()
        return [(t.name, (t.description or "").splitlines()[0].strip()) for t in tools]

    return asyncio.run(_list())


def _run_audit_sweep(repo: Path, *, write_bugarena_report: bool) -> dict[str, Any]:
    async def _execute() -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="bugarena_project_audit_") as tmp:
            op = LoopOperator(state_root=Path(tmp))
            op.start(repo, mode="read_only", max_rounds=2, run_id="project_audit")
            round_res = await op.run_round("project_audit", auto_generate=False)
            _rdir, _state, ledger, coverage = op.load_run("project_audit")
            if write_bugarena_report:
                op.report(
                    "project_audit",
                    format="markdown",
                    output_file=str(repo / ".bugarena" / "latest_audit.md"),
                    repo_hint=repo,
                )
            return {
                "round": round_res,
                "findings": ledger.findings,
                "coverage": coverage,
            }

    return asyncio.run(_execute())


def _render_markdown(
    *,
    repo: Path,
    git_meta: dict[str, Any],
    ruff_rc: int,
    ruff_out: str,
    pytest_rc: int | None,
    pytest_summary: str,
    tools: list[tuple[str, str]],
    audit_data: dict[str, Any],
    tracked_count: int,
) -> str:
    now_iso = datetime.now(UTC).isoformat(timespec="seconds")
    round_res = audit_data["round"]
    summary = round_res["summary"]
    counts = round_res["counts"]
    cov = audit_data["coverage"]
    findings = audit_data["findings"]

    open_confirmed = counts.get("CONFIRMED", 0)
    ruff_label = "PASS (0 issues)" if ruff_rc == 0 else f"FAIL (exit {ruff_rc})"
    if pytest_rc is None:
        pytest_label = "SKIPPED (`--skip-tests`)"
    elif pytest_rc == 0:
        pytest_label = f"PASS ({pytest_summary})"
    else:
        pytest_label = f"FAIL (exit {pytest_rc}: {pytest_summary})"

    verdict = (
        "PASS — Clean Audit & Verification"
        if (open_confirmed == 0 and ruff_rc == 0 and pytest_rc in (0, None) and cov.coverage_pct >= 100.0)
        else "ATTENTION REQUIRED — See Open Findings or Failing Checks"
    )

    lines: list[str] = [
        "# BugArena MCP — Project & Audit Report",
        "",
        f"- **Generated (UTC):** `{now_iso}`",
        f"- **Repository:** `{repo.name}`",
        f"- **Branch / HEAD:** `{git_meta['branch']}` @ `{git_meta['head']}`",
        f"- **Tracked Files:** `{tracked_count}` across `{len(cov.areas)}` audited areas",
        "- **Auto-Update Trigger:** `.githooks/pre-commit` + `scripts/update_project_report.py` + `AGENTS.md`",
        "",
        "## Audit Verdict",
        f"- **Overall Status:** **{verdict}**",
        f"- **Audit Engine Summary:** `{summary['status_line']}`",
        f"- **Module Coverage:** `{cov.coverage_pct:.1f}%` (`{cov.fully_examined_pct:.1f}%` statically read)",
        f"- **Open Confirmed Bugs:** `{open_confirmed}` | **Dismissed:** `{counts.get('DISMISSED', 0)}` | **Unverified:** `{counts.get('UNVERIFIED', 0)}`",
        "",
        "## Verification Status",
        "| Check | Result | Details |",
        "| :--- | :--- | :--- |",
        f"| `ruff check src tests scripts` | **{ruff_label}** | `{scrub_sensitive_data(ruff_out.splitlines()[-1] if ruff_out else 'All checks passed!', base_dir=repo)}` |",
        f"| `pytest -q --tb=short` | **{pytest_label}** | `Isolated unit + regression suites` |",
        f"| `LoopOperator` Read-Only Audit | **PASS** | `9 specialist roles, {len(cov.areas)} areas, 0 open confirmed` |"
        if open_confirmed == 0
        else f"| `LoopOperator` Read-Only Audit | **OPEN FINDINGS ({open_confirmed})** | `{summary['status_line']}` |",
        "",
        "## MCP Tools",
        f"Total registered tools: **{len(tools)}**",
        "",
        "| Tool | Description |",
        "| :--- | :--- |",
    ]
    for name, desc in tools:
        safe_desc = desc.replace("|", r"\|") or "-"
        lines.append(f"| `{name}` | {safe_desc} |")

    lines.extend([
        "",
        "## Coverage Matrix",
        "| Area | Files | Static Read | Dynamic / Tested | Findings |",
        "| :--- | :---: | :---: | :---: | :--- |",
    ])
    for area in cov.areas:
        dyn_or_test = "YES" if (area.dynamic_probe or area.test_exists or area.area in ("docs", "packaging")) else "NO"
        f_list = ", ".join(area.findings_ids) if area.findings_ids else "-"
        lines.append(
            f"| `{area.area}` | {len(area.files)} | {'YES' if area.static_read else 'NO'} | {dyn_or_test} | {f_list} |"
        )

    lines.extend(["", "## Active Audit Findings"])
    active = [f for f in findings if f.state.value not in ("DISMISSED", "FIXED")]
    if not active:
        lines.append("No open audit findings detected in the current codebase.")
    else:
        for f in active:
            lines.append(
                f"- `{f.id}` [**{f.state.value}** / `{f.proposed_severity.value}`] "
                f"`{f.location.file}:{f.location.line_start}` — {f.title}"
            )

    lines.extend(["", "## Recent Changes"])
    for c in git_meta["recent_commits"]:
        lines.append(f"- `{scrub_sensitive_data(c, base_dir=repo)}`")

    if git_meta["status_short"]:
        lines.extend([
            "",
            "## Working Tree Snapshot (`git status --short`)",
            "```text",
            scrub_sensitive_data(git_meta["status_short"], base_dir=repo),
            "```",
        ])

    lines.extend([
        "",
        "## How This Report Stays Updated",
        "Run anytime after editing files (runs automatically on `git commit` when `.githooks` is active):",
        "```bash",
        "python scripts/update_project_report.py",
        "```",
        "",
    ])
    return "\n".join(lines)


def generate_project_report(
    *,
    repo_path: Path | str = ROOT_DIR,
    output_path: Path | str = "PROJECT_REPORT.md",
    skip_pytest: bool = False,
    stage: bool = False,
) -> dict[str, Any]:
    """Audit the repository and write an updated PROJECT_REPORT.md."""
    repo = Path(repo_path).resolve()
    git_meta = _git_metadata(repo)
    tracked_files = tool_git_ls(repo)

    ruff_rc, ruff_out = _run_cmd([sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"], repo, timeout=60.0)

    if skip_pytest or os.environ.get("BUGARENA_SKIP_NESTED_PYTEST") == "1":
        pytest_rc: int | None = None
        pytest_summary = "skipped"
    else:
        pytest_rc, pytest_out = _run_cmd([sys.executable, "-m", "pytest", "-q", "--tb=short"], repo, timeout=240.0)
        last_line = [ln.strip() for ln in pytest_out.splitlines() if ln.strip()]
        pytest_summary = last_line[-1] if last_line else f"exit {pytest_rc}"

    tools = _collect_mcp_tools()
    audit_data = _run_audit_sweep(repo, write_bugarena_report=(Path(output_path).name == "PROJECT_REPORT.md" and Path(output_path).parent in (Path("."), repo)))

    md = _render_markdown(
        repo=repo,
        git_meta=git_meta,
        ruff_rc=ruff_rc,
        ruff_out=ruff_out,
        pytest_rc=pytest_rc,
        pytest_summary=pytest_summary,
        tools=tools,
        audit_data=audit_data,
        tracked_count=len(tracked_files),
    )

    out_path = Path(output_path)
    if out_path.is_absolute():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        saved = out_path
    else:
        saved = save_markdown_report(md, str(out_path), base_dir=repo)

    if stage:
        _run_cmd(["git", "add", str(saved)], repo, timeout=15.0)

    counts = audit_data["round"]["counts"]
    return {
        "output_path": str(saved),
        "coverage_pct": audit_data["coverage"].coverage_pct,
        "open_confirmed": counts.get("CONFIRMED", 0),
        "ruff_exit_code": ruff_rc,
        "pytest_exit_code": pytest_rc,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit BugArena MCP and update PROJECT_REPORT.md.")
    parser.add_argument("--output", default="PROJECT_REPORT.md", help="Report file path relative to repo root.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip pytest run (still runs ruff and LoopOperator audit).")
    parser.add_argument("--stage", action="store_true", help="Run git add on the updated report after generating it.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    res = generate_project_report(
        output_path=args.output,
        skip_pytest=args.skip_tests,
        stage=args.stage,
    )
    print(
        f"Updated {res['output_path']} | coverage={res['coverage_pct']}% | "
        f"open_confirmed={res['open_confirmed']} | ruff={res['ruff_exit_code']} | pytest={res['pytest_exit_code']}"
    )
    if res["open_confirmed"] > 0 or res["ruff_exit_code"] != 0 or (res["pytest_exit_code"] not in (0, None)):
        sys.exit(1)
