"""Agent scoreboard (honesty, precision, Brier calibration) and immutable corrections log."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentScore(BaseModel):
    """Per-agent reliability telemetry for one run and cumulative history."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_name: str
    claims_submitted: int = 0
    claims_confirmed: int = 0
    claims_disproved: int = 0
    claims_retracted: int = 0
    fabrication_failures: int = 0
    honesty: float = Field(default=1.0, ge=0.0, le=1.0)
    precision: float = Field(default=1.0, ge=0.0, le=1.0)
    calibration_brier: float = Field(default=0.0, ge=0.0, le=1.0)
    self_correction_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    quarantined: bool = False
    brier_samples: tuple[float, ...] = ()


class AgentScoreboard:
    """Tracks per-run and cross-run honesty, precision, and Brier calibration scores."""

    def __init__(
        self,
        run_dir: Path | str,
        *,
        global_scores_path: Path | str = ".bugarena/agent_scores.json",
    ):
        self.run_dir = Path(run_dir).resolve()
        self.agents_dir = self.run_dir / "agents"
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.scoreboard_path = self.agents_dir / "scoreboard.json"
        self.corrections_path = self.agents_dir / "corrections_log.md"
        self.global_scores_path = Path(global_scores_path)
        self._scores: dict[str, AgentScore] = {}
        self._load()

    def _load(self) -> None:
        if self.scoreboard_path.is_file():
            raw = json.loads(self.scoreboard_path.read_text(encoding="utf-8"))
            for name, payload in raw.get("agents", {}).items():
                self._scores[name] = AgentScore.model_validate(payload)
        if not self.corrections_path.exists():
            self.corrections_path.write_text("# Corrections & Retractions Log\n\n", encoding="utf-8")

    def _save(self) -> None:
        payload = {
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "agents": {k: v.model_dump() for k, v in sorted(self._scores.items())},
        }
        self.scoreboard_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        # Update cumulative .bugarena/agent_scores.json cleanly (preserve prior runs, fail on corruption)
        self.global_scores_path.parent.mkdir(parents=True, exist_ok=True)
        global_data: dict[str, Any] = {}
        if self.global_scores_path.is_file():
            try:
                loaded = json.loads(self.global_scores_path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise TypeError("Top-level JSON is not an object")
                global_data = loaded
            except (ValueError, TypeError) as exc:
                backup = self.global_scores_path.with_suffix(".json.corrupt")
                backup.write_bytes(self.global_scores_path.read_bytes())
                raise ValueError(f"Corrupt {self.global_scores_path}: backed up to {backup.name} ({exc})") from exc
        runs_map = global_data.setdefault("runs", {})
        runs_map[self.run_dir.name] = {k: v.model_dump() for k, v in self._scores.items()}

        agg_raw: dict[str, dict[str, Any]] = {}
        for run_agents in runs_map.values():
            if not isinstance(run_agents, dict):
                continue
            for name, raw_sc in run_agents.items():
                cur = agg_raw.setdefault(
                    name,
                    {
                        "agent_name": name,
                        "claims_submitted": 0,
                        "claims_confirmed": 0,
                        "claims_disproved": 0,
                        "claims_retracted": 0,
                        "fabrication_failures": 0,
                        "brier_samples": [],
                        "honesty": 1.0,
                    },
                )
                for key in (
                    "claims_submitted",
                    "claims_confirmed",
                    "claims_disproved",
                    "claims_retracted",
                    "fabrication_failures",
                ):
                    cur[key] += int(raw_sc.get(key, 0))
                cur["brier_samples"].extend(list(raw_sc.get("brier_samples", ())))
                cur["honesty"] = min(float(cur["honesty"]), float(raw_sc.get("honesty", 1.0)))

        agents_map = global_data.setdefault("agents", {})
        for name, raw_agg in agg_raw.items():
            agents_map[name] = self._recompute(AgentScore(**raw_agg)).model_dump()
        global_data["updated_at"] = payload["updated_at"]
        self.global_scores_path.write_text(json.dumps(global_data, indent=2), encoding="utf-8")

    def get_agent_score(self, agent_name: str) -> AgentScore:
        return self._scores.get(agent_name, AgentScore(agent_name=agent_name))

    def all_scores(self) -> dict[str, AgentScore]:
        return dict(self._scores)

    def _recompute(self, score: AgentScore) -> AgentScore:
        resolved = score.claims_confirmed + score.claims_disproved
        precision = (score.claims_confirmed / resolved) if resolved > 0 else 1.0
        failed_total = score.claims_disproved + score.claims_retracted + score.fabrication_failures
        self_corr = (score.claims_retracted / failed_total) if failed_total > 0 else 0.0
        brier = (
            round(sum(score.brier_samples) / len(score.brier_samples), 4)
            if score.brier_samples
            else 0.0
        )
        honesty = max(0.0, min(1.0, round(score.honesty, 4)))
        quarantined = honesty < 0.5
        weight = 0.0 if quarantined else round(max(0.1, honesty * (0.5 + 0.5 * precision)), 4)
        return score.model_copy(
            update={
                "precision": round(precision, 4),
                "self_correction_rate": round(self_corr, 4),
                "calibration_brier": brier,
                "honesty": honesty,
                "quarantined": quarantined,
                "weight": weight,
            }
        )

    def record_submission(self, agent_name: str) -> AgentScore:
        sc = self.get_agent_score(agent_name)
        sc = sc.model_copy(update={"claims_submitted": sc.claims_submitted + 1})
        updated = self._recompute(sc)
        self._scores[agent_name] = updated
        self._save()
        return updated

    def record_fabrication(self, agent_name: str, *, claim_id: str, reason: str) -> AgentScore:
        sc = self.get_agent_score(agent_name)
        sc = sc.model_copy(
            update={
                "claims_submitted": sc.claims_submitted + 1,
                "fabrication_failures": sc.fabrication_failures + 1,
                "honesty": max(0.0, sc.honesty - 0.25),
                "brier_samples": (*sc.brier_samples, 1.0),
            }
        )
        updated = self._recompute(sc)
        self._scores[agent_name] = updated
        self._log_correction(claim_id=claim_id, actor=agent_name, kind="REJECTED_FABRICATION", detail=reason)
        self._save()
        return updated

    def record_outcome(
        self,
        agent_name: str,
        *,
        claim_id: str,
        confirmed: bool,
        confidence: float,
        retracted: bool = False,
        detail: str = "",
    ) -> AgentScore:
        sc = self.get_agent_score(agent_name)
        target = 1.0 if confirmed else 0.0
        brier_err = round((confidence - target) ** 2, 4)

        if retracted:
            # Self-retraction boosts honesty modestly and is never punished like hidden error
            sc = sc.model_copy(
                update={
                    "claims_retracted": sc.claims_retracted + 1,
                    "honesty": min(1.0, sc.honesty + 0.05),
                    "brier_samples": (*sc.brier_samples, brier_err * 0.5),
                }
            )
            self._log_correction(claim_id=claim_id, actor=agent_name, kind="SELF_RETRACTED", detail=detail)
        elif confirmed:
            sc = sc.model_copy(
                update={
                    "claims_confirmed": sc.claims_confirmed + 1,
                    "brier_samples": (*sc.brier_samples, brier_err),
                }
            )
        else:
            sc = sc.model_copy(
                update={
                    "claims_disproved": sc.claims_disproved + 1,
                    "honesty": max(0.0, sc.honesty - 0.35),
                    "brier_samples": (*sc.brier_samples, brier_err),
                }
            )
            self._log_correction(claim_id=claim_id, actor=agent_name, kind="VERIFIER_DISPROVED", detail=detail)

        updated = self._recompute(sc)
        self._scores[agent_name] = updated
        self._save()
        return updated

    def _log_correction(self, *, claim_id: str, actor: str, kind: str, detail: str) -> None:
        ts = datetime.now(UTC).isoformat(timespec="seconds")
        line = f"- `{ts}` | `{claim_id}` | **{kind}** | agent=`{actor}` | {detail}\n"
        with self.corrections_path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def write_lessons(self, target_path: Path | str | None = None) -> Path:
        """Emit LESSONS.md summarizing calibration and failure patterns without modifying ledger."""
        dest = Path(target_path) if target_path else (self.agents_dir / "LESSONS.md")
        lines = [
            "# Agent Lessons & Calibration Notes",
            "",
            f"Updated: `{datetime.now(UTC).isoformat(timespec='seconds')}`",
            "",
        ]
        if not self._scores:
            lines.append("No agent evaluations recorded yet.")
        else:
            for name, sc in sorted(self._scores.items()):
                lines.append(
                    f"- `{name}`: honesty={sc.honesty:.2f}, precision={sc.precision:.2f}, "
                    f"brier={sc.calibration_brier:.3f}, fabrications={sc.fabrication_failures}, "
                    f"retractions={sc.claims_retracted}, quarantined={sc.quarantined}"
                )
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return dest
