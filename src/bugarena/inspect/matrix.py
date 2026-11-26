"""DevTools inspect coverage matrix covering all 14 Section 10 areas."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

ALL_PANELS: tuple[str, ...] = (
    "Elements",
    "Console",
    "Issues panel",
    "Sources",
    "Network",
    "Performance",
    "Memory",
    "Application",
    "Security",
    "Lighthouse-style",
    "Rendering and layers",
    "Sensors and emulation",
    "Interaction flows",
    "Cross-browser diff",
)


class PanelCoverage(BaseModel):
    """Coverage telemetry for one DevTools panel/aspect."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    panel: str
    covered: bool = False
    reason: str = "Not run yet"
    evidence_ids: tuple[str, ...] = ()
    findings_count: int = 0


class InspectCoverageMatrix:
    """Tracks coverage across all 14 DevTools inspect panels and renders coverage_matrix.md."""

    def __init__(self, run_dir: Path | str):
        self.run_dir = Path(run_dir).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._panels: dict[str, PanelCoverage] = {
            name: PanelCoverage(panel=name, covered=False, reason="Pending") for name in ALL_PANELS
        }

    def mark_panel(
        self,
        panel: str,
        *,
        covered: bool,
        reason: str = "",
        evidence_ids: tuple[str, ...] = (),
        findings_count: int = 0,
    ) -> PanelCoverage:
        entry = PanelCoverage(
            panel=panel,
            covered=covered,
            reason=reason or ("Collected via CDP" if covered else "Not covered"),
            evidence_ids=tuple(evidence_ids),
            findings_count=findings_count,
        )
        self._panels[panel] = entry
        return entry

    def summary(self) -> dict[str, Any]:
        entries = list(self._panels.values())
        covered_cnt = sum(1 for p in entries if p.covered)
        return {
            "total_panels": len(entries),
            "covered_panels": covered_cnt,
            "coverage_pct": round((covered_cnt / len(entries)) * 100.0, 2) if entries else 0.0,
            "panels": [p.model_dump() for p in entries],
        }

    def write_markdown(self, filename: str = "coverage_matrix.md") -> Path:
        lines = [
            "## DevTools Inspect Coverage Matrix",
            "",
            "| DevTools Area | Status | Reason / Notes | Evidence IDs | Findings |",
            "| :--- | :---: | :--- | :--- | :---: |",
        ]
        for panel_name in ALL_PANELS:
            p = self._panels[panel_name]
            status = "COVERED" if p.covered else "NOT COVERED"
            ev = ", ".join(p.evidence_ids) if p.evidence_ids else "-"
            safe_reason = p.reason.replace("|", r"\|")
            lines.append(
                f"| `{p.panel}` | {status} | {safe_reason} | {ev} | {p.findings_count} |"
            )
        target = self.run_dir / filename
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target
