"""Per-module and per-area audit coverage tracking."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class ModuleCoverage(BaseModel):
    """Coverage telemetry for a single repository file or logical area."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    area: str
    files: tuple[str, ...] = ()
    static_read: bool = False
    dynamic_probe: bool = False
    test_exists: bool = False
    findings_ids: tuple[str, ...] = ()
    agents_assigned: tuple[str, ...] = ()


class CoverageMatrix(BaseModel):
    """Immutable coverage snapshot across all discovered repository areas."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo_path: str
    areas: tuple[ModuleCoverage, ...] = ()

    @property
    def coverage_pct(self) -> float:
        """Compute percentage of areas inspected statically and dynamically (or tested)."""
        if not self.areas:
            return 0.0
        covered = sum(
            1
            for a in self.areas
            if a.static_read and (a.dynamic_probe or a.test_exists or a.area in ("docs", "packaging"))
        )
        return round((covered / len(self.areas)) * 100.0, 2)

    @property
    def fully_examined_pct(self) -> float:
        """Percentage of areas with static_read == True."""
        if not self.areas:
            return 0.0
        return round((sum(1 for a in self.areas if a.static_read) / len(self.areas)) * 100.0, 2)


AREA_PREFIX_RULES: tuple[tuple[str, str], ...] = (
    ("src/bugarena/models/", "models"),
    ("src/bugarena/discovery/", "discovery"),
    ("src/bugarena/synthesizer/", "synthesizer"),
    ("src/bugarena/sandbox/", "sandbox"),
    ("src/bugarena/tournament/providers/", "providers"),
    ("src/bugarena/tournament/personas/", "personas"),
    ("src/bugarena/tournament/", "tournament"),
    ("src/bugarena/evaluation/", "evaluation"),
    ("src/bugarena/reporting/", "reporting"),
    ("src/bugarena/agents/", "agents"),
    ("src/bugarena/audit/", "audit"),
    ("src/bugarena/server.py", "server"),
    ("src/bugarena/config.py", "config"),
    ("src/bugarena/__init__.py", "packaging"),
    ("scripts/", "scripts"),
    ("tests/", "tests"),
    ("pyproject.toml", "packaging"),
    (".gitignore", "packaging"),
    (".env.example", "packaging"),
    ("README.md", "docs"),
    (".agents/", "docs"),
)


def classify_area(rel_path: str) -> str:
    """Map a relative repository file path to a logical audit area."""
    norm = rel_path.replace("\\", "/").lstrip("./")
    for prefix, area in AREA_PREFIX_RULES:
        if prefix.endswith("/") and norm.startswith(prefix):
            return area
        if norm == prefix:
            return area
    if norm.startswith("src/"):
        parts = norm.split("/")
        return parts[1] if len(parts) > 2 else "src_root"
    return "other"


def build_coverage_matrix(
    repo_path: Path | str,
    tracked_files: list[str] | tuple[str, ...],
    findings: tuple = (),
) -> CoverageMatrix:
    """Build initial coverage matrix from repository file list and existing findings."""
    repo = Path(repo_path).resolve()
    area_files: dict[str, list[str]] = {}
    test_files_lower: list[str] = []

    for f in tracked_files:
        norm = f.replace("\\", "/")
        if (
            norm.startswith((".bugarena/", "bug-report", "bug_report", ".venv/", ".git/"))
            or "/__pycache__/" in norm
        ):
            continue
        if norm.startswith("tests/") and norm.endswith(".py"):
            test_files_lower.append(norm.lower())
        area = classify_area(norm)
        area_files.setdefault(area, []).append(norm)

    area_findings: dict[str, list[str]] = {}
    area_dynamic: set[str] = set()
    for finding in findings:
        f_area = classify_area(finding.location.file)
        area_findings.setdefault(f_area, []).append(finding.id)
        if getattr(finding, "evidence_type", "") == "DYNAMIC":
            area_dynamic.add(f_area)

    areas: list[ModuleCoverage] = []
    for area_name in sorted(area_files):
        files_sorted = tuple(sorted(area_files[area_name]))
        has_test = any(
            area_name in tf or any(Path(src_f).stem in tf for src_f in files_sorted)
            for tf in test_files_lower
        ) or area_name == "tests"
        areas.append(
            ModuleCoverage(
                area=area_name,
                files=files_sorted,
                static_read=False,
                dynamic_probe=area_name in area_dynamic,
                test_exists=has_test,
                findings_ids=tuple(sorted(set(area_findings.get(area_name, ())))),
            )
        )

    return CoverageMatrix(repo_path=str(repo), areas=tuple(areas))


def mark_area_coverage(
    matrix: CoverageMatrix,
    area: str,
    *,
    static_read: bool | None = None,
    dynamic_probe: bool | None = None,
    agent_name: str | None = None,
    finding_id: str | None = None,
) -> CoverageMatrix:
    """Return updated CoverageMatrix with new area telemetry."""
    updated: list[ModuleCoverage] = []
    found = False
    for entry in matrix.areas:
        if entry.area == area:
            found = True
            agents = (
                tuple(sorted(set(entry.agents_assigned) | {agent_name}))
                if agent_name
                else entry.agents_assigned
            )
            fids = (
                tuple(sorted(set(entry.findings_ids) | {finding_id}))
                if finding_id
                else entry.findings_ids
            )
            entry = ModuleCoverage(
                area=entry.area,
                files=entry.files,
                static_read=entry.static_read if static_read is None else static_read,
                dynamic_probe=entry.dynamic_probe if dynamic_probe is None else dynamic_probe,
                test_exists=entry.test_exists,
                findings_ids=fids,
                agents_assigned=agents,
            )
        updated.append(entry)

    if not found:
        updated.append(
            ModuleCoverage(
                area=area,
                files=(),
                static_read=bool(static_read),
                dynamic_probe=bool(dynamic_probe),
                test_exists=False,
                findings_ids=(finding_id,) if finding_id else (),
                agents_assigned=(agent_name,) if agent_name else (),
            )
        )
    return CoverageMatrix(repo_path=matrix.repo_path, areas=tuple(updated))


def save_coverage_matrix(matrix: CoverageMatrix, path: Path | str = ".bugarena/coverage.json") -> Path:
    """Atomically write coverage matrix JSON."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".cov_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(matrix.model_dump(), indent=2))
        os.replace(tmp_name, target)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    return target
