"""Markdown report generator for multi-agent repair tournaments."""

from bugarena.models.tournament import TournamentRecord


def format_markdown_report(tournament: TournamentRecord) -> str:
    """
    Format a complete, publication-ready markdown tournament report.
    """
    lines = []
    lines.append("# BugArena Repair Tournament Report")
    lines.append(f"**Tournament ID**: `{tournament.tournament_id}`  ")
    lines.append(f"**Repository**: `{tournament.repo_path}`  ")
    lines.append("")

    # Leaderboard Table
    lines.append("## Tournament Leaderboard")
    lines.append(
        "| Rank | Candidate ID | Persona | Repro Passed | Regressions | Churn (LOC) | Complexity Δ | Score | Status |"
    )
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

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

        lines.append(
            f"| {idx} | `{ev.candidate_id}` | {persona_str} | {repro_str} | {ev.regressions_count} | {ev.diff_churn} | {ev.cyclomatic_delta} | **{ev.score:.1f}** | `{status_str}` |"
        )

    lines.append("")

    # Champion Section
    champion = (
        cand_map.get(tournament.champion_candidate_id) if tournament.champion_candidate_id else None
    )
    if champion:
        lines.append("## Winning Champion Patch")
        lines.append(f"- **Candidate ID**: `{champion.candidate_id}`")
        lines.append(f"- **Agent Persona**: `{champion.persona.value}`")
        lines.append(
            f"- **Lines Added / Deleted**: +{champion.lines_added} / -{champion.lines_deleted}"
        )
        lines.append(f"- **Explanation**: {champion.explanation}")
        lines.append("")
        lines.append("### Unified Diff")
        lines.append("```diff")
        lines.append(champion.diff)
        lines.append("```")
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
