"""Truth Foundation package: hash-chained vault, claim citations, scoreboard, transcripts."""

from bugarena.truth.claims import (
    CitationChecker,
    Claim,
    ClaimLedger,
    ClaimStatus,
    apply_site_severity_rubric,
)
from bugarena.truth.scoreboard import AgentScore, AgentScoreboard
from bugarena.truth.transcript import TranscriptLogger
from bugarena.truth.vault import EvidenceEntry, EvidenceVault, scrub_evidence_text

__all__ = [
    "AgentScore",
    "AgentScoreboard",
    "CitationChecker",
    "Claim",
    "ClaimLedger",
    "ClaimStatus",
    "EvidenceEntry",
    "EvidenceVault",
    "TranscriptLogger",
    "apply_site_severity_rubric",
    "scrub_evidence_text",
]
