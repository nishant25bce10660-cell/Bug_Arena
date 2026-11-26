"""AgentEvaluator: grades subagents per round on precision, duplicate rate, and evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from bugarena.audit.ledger import EvidenceType, Finding, FindingState

if TYPE_CHECKING:
    from bugarena.agents.base import AgentRunResult


class AgentScorecard(BaseModel):
    """Per-agent quality evaluation metrics for an audit round."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_name: str
    submitted: int = Field(ge=0)
    confirmed: int = Field(ge=0)
    dismissed: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    dynamic_verified: int = Field(ge=0)
    precision_pct: float = Field(ge=0.0, le=100.0)
    duplicate_rate_pct: float = Field(ge=0.0, le=100.0)
    evidence_quality_pct: float = Field(ge=0.0, le=100.0)
    quarantined: bool = False
    recommendation: str = "OK"


class AgentEvaluator:
    """Scores subagent precision, duplicates, evidence backing, and quarantine triggers."""

    def evaluate_round(
        self,
        run_results: list[AgentRunResult],
        ledger_findings: tuple[Finding, ...],
        *,
        invalid_json_counts: dict[str, int] | None = None,
    ) -> list[AgentScorecard]:
        """Compute round scorecard for each agent that ran."""
        bad_json = invalid_json_counts or {}
        by_agent: dict[str, list[Finding]] = {}
        for f in ledger_findings:
            by_agent.setdefault(f.found_by, []).append(f)

        cards: list[AgentScorecard] = []
        for res in run_results:
            name = res.agent_name
            submitted = len(res.findings)
            owned = by_agent.get(name, [])
            confirmed = sum(
                1 for f in owned if f.state in (FindingState.CONFIRMED, FindingState.FIXED)
            )
            dismissed = sum(1 for f in owned if f.state == FindingState.DISMISSED)
            dynamic_count = sum(1 for f in owned if f.evidence_type == EvidenceType.DYNAMIC)

            # Duplicate estimate: submitted drafts that already existed instead of creating new
            denom_eval = confirmed + dismissed
            precision = round((confirmed / denom_eval) * 100.0, 1) if denom_eval > 0 else 100.0
            dupes = max(0, submitted - len(owned)) if submitted > len(owned) else 0
            dupe_rate = round((dupes / submitted) * 100.0, 1) if submitted > 0 else 0.0
            ev_quality = (
                round((dynamic_count / len(owned)) * 100.0, 1) if owned else 100.0
            )
            quarantined = bad_json.get(name, 0) >= 2

            rec = "OK"
            if quarantined:
                rec = "QUARANTINED: repeated invalid JSON output"
            elif precision < 70.0 and denom_eval >= 2:
                rec = "RETUNE_PROMPT: precision below 70%"

            cards.append(
                AgentScorecard(
                    agent_name=name,
                    submitted=submitted,
                    confirmed=confirmed,
                    dismissed=dismissed,
                    duplicates=dupes,
                    dynamic_verified=dynamic_count,
                    precision_pct=precision,
                    duplicate_rate_pct=dupe_rate,
                    evidence_quality_pct=ev_quality,
                    quarantined=quarantined,
                    recommendation=rec,
                )
            )
        return cards
