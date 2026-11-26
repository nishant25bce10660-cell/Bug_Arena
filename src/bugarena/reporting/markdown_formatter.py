"""Markdown report generator for bug diagnostics and multi-agent repair tournaments."""

import re
from pathlib import Path

from bugarena.models.bug import BugSpec
from bugarena.models.repro import ReproTestSpec
from bugarena.models.tournament import TournamentRecord
from bugarena.sandbox.security import validate_safe_path


def _md_cell(value: object) -> str:
    """Normalize line breaks and escape Markdown table delimiters inside cells."""
    flattened = " ".join(str(value).replace("\r\n", "\n").replace("\r", "\n").splitlines())
    return flattened.replace("|", r"\|")


def fenced_markdown_block(content: str, lang: str = "") -> str:
    """Wrap content in a Markdown code fence longer than any internal backtick run."""
    longest = max((len(m.group(0)) for m in re.finditer(r"`+", content)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{lang}\n{content.strip()}\n{fence}"


def save_markdown_report(
    report_markdown: str,
    output_path: str | Path,
    base_dir: Path | str | None = None,
) -> Path:
    """
    Save generated report text to disk, enforcing base_dir containment when supplied.
    """
    if base_dir is not None:
        target = validate_safe_path(base_dir, str(output_path))
    else:
        target = Path(output_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report_markdown, encoding="utf-8")
    return target


def format_bug_diagnostic_markdown(
    bug_spec: BugSpec,
    repro_spec: ReproTestSpec | None = None,
    bug_description: str | None = None,
) -> str:
    """
    Format a detailed diagnostic markdown section describing the bug, suspects, and repro.
    """
    lines = []
    lines.append("## 1. Bug Description & Diagnostics")
    lines.append(f"- **Bug ID**: `{bug_spec.bug_id}`")
    desc = bug_description or bug_spec.hint or "No additional description provided."
    lines.append(f"- **Description**: {desc}")
    if bug_spec.hint:
        lines.append(f"- **Diagnostic Hint**: {bug_spec.hint}")
    lines.append(f"- **Repository Path**: `{bug_spec.repo_path}`")
    lines.append("")

    if bug_spec.suspects:
        lines.append("### Identified Suspect Locations")
        lines.append("| File | Function | Lines | Bug Type | Confidence | Fault Diagnosis |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for s in bug_spec.suspects:
            conf_pct = f"{s.confidence * 100:.0f}%"
            line_str = f"L{s.line_range[0]}-L{s.line_range[1]}"
            lines.append(
                f"| `{_md_cell(s.file_path)}` | `{_md_cell(s.function_name)}` | {line_str} | `{_md_cell(s.bug_type)}` | {conf_pct} | {_md_cell(s.reasoning)} |"
            )
        lines.append("")

        primary = bug_spec.suspects[0]
        if primary.code_snippet:
            lines.append("### Primary Suspect Code Slice")
            lines.append(f"*File: `{_md_cell(primary.file_path)}` (Lines {primary.line_range[0]} to {primary.line_range[1]})*")
            lines.append(fenced_markdown_block(primary.code_snippet, "python"))
            lines.append("")

    if bug_spec.error_log:
        lines.append("### Error Log / Stack Trace")
        lines.append(fenced_markdown_block(bug_spec.error_log))
        lines.append("")

    if repro_spec:
        lines.append("## 2. Failing Reproduction Test (Red Baseline)")
        lines.append(f"- **Test File**: `{_md_cell(repro_spec.test_file_path)}`")
        if repro_spec.expected_exception:
            lines.append(f"- **Expected Exception / Failure**: `{_md_cell(repro_spec.expected_exception)}`")
        status_label = "VERIFIED (Fails before fix)" if repro_spec.red_baseline_verified else "UNVERIFIED"
        lines.append(f"- **Red Baseline Status**: `{status_label}`")
        lines.append("")
        lines.append(fenced_markdown_block(repro_spec.test_code, "python"))
        lines.append("")

    return "\n".join(lines)


def format_markdown_report(
    tournament: TournamentRecord,
    bug_spec: BugSpec | None = None,
    repro_spec: ReproTestSpec | None = None,
    bug_description: str | None = None,
) -> str:
    """
    Format a complete, publication-ready markdown tournament report with full bug data.
    """
    resolved_bug = bug_spec or tournament.bug_spec
    resolved_repro = repro_spec or tournament.repro_spec
    resolved_desc = bug_description or tournament.bug_description

    lines = []
    lines.append("# BugArena Diagnostic & Repair Report")
    lines.append(f"**Tournament ID**: `{tournament.tournament_id}`  ")
    lines.append(f"**Repository**: `{tournament.repo_path}`  ")
    lines.append("")

    # Section 1 & 2: Bug Diagnostics & Repro Test
    if resolved_bug or resolved_desc:
        if resolved_bug:
            diag_md = format_bug_diagnostic_markdown(
                bug_spec=resolved_bug,
                repro_spec=resolved_repro,
                bug_description=resolved_desc,
            )
            lines.append(diag_md)
        elif resolved_desc:
            lines.append("## 1. Bug Description & Diagnostics")
            lines.append(f"- **Description**: {resolved_desc}")
            lines.append("")
        lines.append("---")
        lines.append("")

    # Section 3: Leaderboard Table
    lines.append("## Tournament Leaderboard")
    lines.append(
        "| Rank | Candidate ID | Persona | Repro Passed | Regressions | Churn (LOC) | Complexity Δ | Score | Status | Notes |"
    )
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    cand_map = {c.candidate_id: c for c in tournament.candidates}
    sorted_evals = sorted(tournament.evaluations, key=lambda e: e.score, reverse=True)

    for idx, ev in enumerate(sorted_evals, 1):
        cand = cand_map.get(ev.candidate_id)
        persona_str = cand.persona.value if cand else "unknown"
        repro_str = "PASS" if ev.repro_passed else "FAIL"
        status_str = (
            "CHAMPION"
            if ev.candidate_id == tournament.champion_candidate_id
            else ("DISQUALIFIED" if ev.disqualified else "EVALUATED")
        )
        notes_str = _md_cell(ev.disqualification_reason) if ev.disqualification_reason else "-"

        lines.append(
            f"| {idx} | `{_md_cell(ev.candidate_id)}` | {_md_cell(persona_str)} | {repro_str} | {ev.regressions_count} | {ev.diff_churn} | {ev.cyclomatic_delta} | **{ev.score:.1f}** | `{status_str}` | {notes_str} |"
        )

    lines.append("")

    # Section 4: Champion Section
    champion = (
        cand_map.get(tournament.champion_candidate_id) if tournament.champion_candidate_id else None
    )
    if champion:
        lines.append("## Winning Champion Patch")
        lines.append(f"- **Candidate ID**: `{_md_cell(champion.candidate_id)}`")
        lines.append(f"- **Agent Persona**: `{champion.persona.value}`")
        lines.append(
            f"- **Lines Added / Deleted**: +{champion.lines_added} / -{champion.lines_deleted}"
        )
        lines.append(f"- **Explanation**: {_md_cell(champion.explanation)}")
        lines.append("")
        lines.append("### Unified Diff")
        lines.append(fenced_markdown_block(champion.diff, "diff"))
        lines.append("")
        lines.append("### How to Apply This Fix")
        lines.append(
            "To apply this patch to your repository, save the diff above to `fix.patch` and run:"
        )
        lines.append("```bash")
        lines.append("git apply fix.patch")
        lines.append("```")
    else:
        lines.append("## No Champion Selected")
        lines.append(
            "None of the competing agent patches satisfied the zero-regression and reproduction pass gates."
        )

    return "\n".join(lines)
