"""Code-enforced claim validation, citation checking, and deterministic severity rubric."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bugarena.truth.scoreboard import AgentScoreboard
from bugarena.truth.vault import EvidenceVault


class ClaimStatus(StrEnum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    NOT_REPRODUCED = "NOT_REPRODUCED"
    UNVERIFIED = "UNVERIFIED"
    RETRACTED = "RETRACTED"
    REJECTED = "REJECTED"


def apply_site_severity_rubric(
    *,
    proposed: str,
    evidence_type: str,
    security_exploitable: bool = False,
    core_flow_lost: bool = False,
    common_path_broken: bool = False,
    a11y_or_perf_barrier: bool = False,
) -> tuple[str, str]:
    """
    Deterministic Section 12 severity rubric:
      - Critical: exploitable security flaw or complete loss of a core user flow, WITH DYNAMIC proof
      - High: broken major feature or data-loss risk on common paths
      - Medium: broken edge flows, accessibility failures with real barriers, notable perf regressions
      - Low: cosmetic, hygiene, best-practice
    STATIC-only evidence can NEVER be Critical.
    """
    ev_upper = evidence_type.upper()
    if ev_upper == "DYNAMIC" and (security_exploitable or core_flow_lost):
        return (
            "Critical",
            "Verified DYNAMIC proof of exploitable security flaw or complete core user-flow loss.",
        )
    if common_path_broken or (ev_upper != "DYNAMIC" and (security_exploitable or core_flow_lost)):
        reason = (
            "STATIC-only evidence capped from Critical to High per rubric."
            if (ev_upper != "DYNAMIC" and (security_exploitable or core_flow_lost))
            else "Broken major feature or data-loss risk on a common user path."
        )
        return ("High", reason)
    if a11y_or_perf_barrier or proposed in ("High", "Medium"):
        return (
            "Medium",
            "Edge-flow failure, accessibility barrier, or notable performance regression.",
        )
    return ("Low", "Cosmetic, hygiene, or best-practice recommendation.")


class Claim(BaseModel):
    """Schema-validated finding/claim requiring >=1 EvidenceVault reference."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    statement: str
    evidence_refs: tuple[str, ...]
    quoted_spans: tuple[str, ...] = ()
    cited_numbers: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    status: ClaimStatus = ClaimStatus.PROPOSED
    found_by: str
    verified_by: str | None = None
    evidence_type: str = "DYNAMIC"
    proposed_severity: str = "Medium"
    severity: str = ""
    severity_justification: str = ""
    limitations: str = "Direct observation limited to executed probes."
    where_found: dict[str, Any] = Field(default_factory=dict)
    how_it_occurs: str = ""
    repro_steps: tuple[str, ...] = ()
    fix_guidance: str = ""
    browsers_affected: tuple[str, ...] = ()
    origin: str = "bugarena"

    @field_validator("evidence_refs")
    @classmethod
    def _require_evidence_refs(cls, val: tuple[str, ...]) -> tuple[str, ...]:
        if not val:
            raise ValueError("Claim rejected: evidence_refs must contain at least one EvidenceVault ID.")
        return val


class CitationChecker:
    """Verify quoted spans and numbers cited by an agent appear verbatim in cited vault artifacts."""

    @staticmethod
    def verify_claim_citations(claim: Claim, vault: EvidenceVault) -> dict[str, Any]:
        artifact_texts: list[str] = []
        missing_refs: list[str] = []

        for ref in claim.evidence_refs:
            entry = vault.get(ref)
            if entry is None:
                missing_refs.append(ref)
                continue
            if entry.rel_path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".pdf")):
                artifact_texts.append(f"{entry.evidence_id} {entry.sha256} {entry.args_summary}")
            else:
                txt = vault.read_artifact_text(ref)
                if txt is None:
                    missing_refs.append(ref)
                else:
                    artifact_texts.append(txt)

        if missing_refs:
            return {
                "valid": False,
                "reason": f"Missing or unreadable evidence_refs: {missing_refs}",
            }

        combined = "\n".join(artifact_texts)
        missing_quotes = [q for q in claim.quoted_spans if q and q not in combined]
        if missing_quotes:
            return {
                "valid": False,
                "reason": f"Citation mismatch: quoted text not found in cited artifacts: {missing_quotes}",
            }

        missing_nums = [
            n for n in claim.cited_numbers if n and not re.search(rf"(?<!\w){re.escape(n)}(?!\w)", combined)
        ]
        if missing_nums:
            return {
                "valid": False,
                "reason": f"Citation mismatch: cited numbers not found in artifacts: {missing_nums}",
            }

        return {"valid": True, "reason": "All cited evidence references, quotes, and numbers verified."}


class ClaimLedger:
    """Enforces vault integrity, citation matching, rubric severity, and retractions."""

    def __init__(
        self,
        run_dir: Path | str,
        *,
        vault: EvidenceVault,
        scoreboard: AgentScoreboard,
    ):
        self.run_dir = Path(run_dir).resolve()
        self.vault = vault
        self.scoreboard = scoreboard
        self.claims_path = self.run_dir / "verify" / "claims.json"
        self.claims_path.parent.mkdir(parents=True, exist_ok=True)
        self._claims: dict[str, Claim] = {}
        self._load()

    def _load(self) -> None:
        if self.claims_path.is_file():
            raw = json.loads(self.claims_path.read_text(encoding="utf-8"))
            for item in raw.get("claims", []):
                c = Claim.model_validate(item)
                self._claims[c.id] = c

    def _save(self) -> None:
        payload = {"claims": [c.model_dump() for c in self._claims.values()]}
        self.claims_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @property
    def claims(self) -> tuple[Claim, ...]:
        return tuple(self._claims.values())

    def get(self, claim_id: str) -> Claim | None:
        return self._claims.get(claim_id)

    def submit_claim(
        self,
        claim: Claim,
        *,
        security_exploitable: bool = False,
        core_flow_lost: bool = False,
        common_path_broken: bool = False,
        a11y_or_perf_barrier: bool = False,
    ) -> dict[str, Any]:
        """Validate evidence chain + citations before accepting a claim into the ledger."""
        chain_check = self.vault.verify_chain()
        if not chain_check["valid"]:
            return {
                "accepted": False,
                "status": ClaimStatus.REJECTED,
                "reason": f"Evidence vault integrity failure: {chain_check['errors']}",
            }

        cite = CitationChecker.verify_claim_citations(claim, self.vault)
        if not cite["valid"]:
            self.scoreboard.record_fabrication(claim.found_by, claim_id=claim.id, reason=cite["reason"])
            rejected = claim.model_copy(update={"status": ClaimStatus.REJECTED})
            self._claims[claim.id] = rejected
            self._save()
            return {"accepted": False, "status": ClaimStatus.REJECTED, "reason": cite["reason"]}

        sev, just = apply_site_severity_rubric(
            proposed=claim.proposed_severity,
            evidence_type=claim.evidence_type,
            security_exploitable=security_exploitable,
            core_flow_lost=core_flow_lost,
            common_path_broken=common_path_broken,
            a11y_or_perf_barrier=a11y_or_perf_barrier,
        )
        stored = claim.model_copy(update={"severity": sev, "severity_justification": just})
        self._claims[stored.id] = stored
        self.scoreboard.record_submission(stored.found_by)
        self._save()
        return {"accepted": True, "status": stored.status, "claim": stored}

    def retract_claim(self, claim_id: str, *, reason: str, by_agent: str) -> Claim:
        claim = self._claims.get(claim_id)
        if claim is None:
            raise KeyError(f"Claim '{claim_id}' not found.")
        updated = claim.model_copy(update={"status": ClaimStatus.RETRACTED})
        self._claims[claim_id] = updated
        self.scoreboard.record_outcome(
            by_agent,
            claim_id=claim_id,
            confirmed=False,
            confidence=claim.confidence,
            retracted=True,
            detail=reason,
        )
        self._save()
        return updated

    def record_verification(
        self,
        claim_id: str,
        *,
        verifier: str,
        verdict: str,
        detail: str = "",
    ) -> Claim:
        claim = self._claims.get(claim_id)
        if claim is None:
            raise KeyError(f"Claim '{claim_id}' not found.")
        if verifier == claim.found_by:
            raise ValueError(f"Verifier '{verifier}' must differ from finder '{claim.found_by}'.")
        if verdict not in ("CONFIRMED", "NOT_REPRODUCED", "UNVERIFIED"):
            raise ValueError(f"Invalid verdict: {verdict!r}")

        new_status = ClaimStatus(verdict)
        updated = claim.model_copy(update={"status": new_status, "verified_by": verifier})
        self._claims[claim_id] = updated

        if verdict in ("CONFIRMED", "NOT_REPRODUCED"):
            self.scoreboard.record_outcome(
                claim.found_by,
                claim_id=claim_id,
                confirmed=(verdict == "CONFIRMED"),
                confidence=claim.confidence,
                retracted=False,
                detail=detail,
            )
        self._save()
        return updated
