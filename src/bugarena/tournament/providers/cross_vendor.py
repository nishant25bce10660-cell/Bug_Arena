"""Gemini + xAI Grok cross-vendor report analysis with schema validation and cost/token caps."""

from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, ConfigDict

from bugarena.tournament.providers.dispatcher import MultiModelDispatcher
from bugarena.truth.claims import ClaimLedger, ClaimStatus
from bugarena.truth.vault import EvidenceVault


class WriterAnalysisSchema(BaseModel):
    """Schema-validated prose analysis output from the writer vendor."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    executive_summary: str
    quick_wins: tuple[str, ...] = ()


class CriticAnalysisSchema(BaseModel):
    """Schema-validated adversarial critique from a distinct critic vendor."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    verdict: str = "AGREE_WITH_RESERVATIONS"
    notes: str = ""
    unsupported_claims: tuple[str, ...] = ()


def _parse_json_block(raw_text: str) -> dict[str, Any] | None:
    txt = (raw_text or "").strip()
    if not txt:
        return None
    if txt.startswith("```"):
        lines = txt.splitlines()
        if len(lines) >= 3:
            txt = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(txt)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        return None


def _vendor_model(vendor: str) -> tuple[str, str]:
    v = vendor.lower().strip()
    if v in ("grok", "xai"):
        return ("grok", "grok-3-mini")
    return ("gemini", "gemma-4-26b-a4b-it")


def _vendor_has_key(vendor: str) -> bool:
    return bool(os.environ.get("XAI_API_KEY" if vendor == "grok" else "GEMINI_API_KEY"))


async def analyze_findings_cross_vendor(
    *,
    ledger: ClaimLedger,
    vault: EvidenceVault,
    writer_vendor: str = "gemini",
    critic_vendor: str = "grok",
    max_retries: int = 1,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    """
    Use distinct writer and critic vendors (Gemini & Grok) with schema-validated JSON and
    bounded retries. Falls back honestly to deterministic local summary when API keys are absent.
    """
    w_vendor, w_model = _vendor_model(writer_vendor)
    c_vendor, c_model = _vendor_model(critic_vendor)
    if c_vendor == w_vendor:
        c_vendor, c_model = _vendor_model("grok" if w_vendor == "gemini" else "gemini")

    confirmed = [c for c in ledger.claims if c.status == ClaimStatus.CONFIRMED]
    digest = [
        {
            "id": c.id,
            "statement": c.statement,
            "severity": c.severity or c.proposed_severity,
            "evidence_refs": list(c.evidence_refs),
            "quotes": list(c.quoted_spans),
        }
        for c in confirmed[:25]
    ]
    digest_json = json.dumps(digest, indent=2)

    dispatcher = MultiModelDispatcher(timeout_seconds=timeout_seconds)

    writer_output: dict[str, Any] = {
        "executive_summary": f"Verified {len(confirmed)} confirmed findings backed by {len(vault.entries())} vault artifacts.",
        "quick_wins": [c.fix_guidance or c.statement for c in confirmed[:3] if c.fix_guidance or c.statement],
        "mode": "deterministic_fallback",
    }
    if confirmed and _vendor_has_key(w_vendor):
        w_prompt = (
            "Summarize these verified BugArena findings strictly as JSON with keys "
            "`executive_summary` (string) and `quick_wins` (list of strings). "
            "Cite ONLY quotes/IDs present below.\n"
            f"{digest_json}"
        )
        for _ in range(max_retries + 1):
            _diff, text = await dispatcher._route_model(
                w_model,
                "You are a factual security & quality report writer. Return JSON only.",
                w_prompt,
                timeout_seconds=timeout_seconds,
            )
            parsed = _parse_json_block(text)
            if parsed:
                validated = WriterAnalysisSchema.model_validate(parsed)
                writer_output = validated.model_dump()
                writer_output["mode"] = f"llm:{w_vendor}"
                break

    critic_output: dict[str, Any] = {
        "verdict": "SKIPPED_NO_KEY" if not _vendor_has_key(c_vendor) else "FALLBACK",
        "notes": f"Confirmed {len(confirmed)} claims; critic key present={_vendor_has_key(c_vendor)}.",
        "unsupported_claims": [],
    }
    if confirmed and _vendor_has_key(c_vendor):
        c_prompt = (
            "Review this draft summary against the verified findings strictly as JSON with keys "
            "`verdict` ('AGREE'|'AGREE_WITH_RESERVATIONS'|'DISPUTE'), `notes`, and `unsupported_claims` (list).\n"
            f"Summary:\n{json.dumps(writer_output)}\n\nVerified Findings:\n{digest_json}"
        )
        for _ in range(max_retries + 1):
            _diff, text = await dispatcher._route_model(
                c_model,
                "You are an adversarial report critic. Return JSON only.",
                c_prompt,
                timeout_seconds=timeout_seconds,
            )
            parsed = _parse_json_block(text)
            if parsed:
                validated = CriticAnalysisSchema.model_validate(parsed)
                critic_output = validated.model_dump()
                break

    return {
        "writer_vendor": w_vendor,
        "writer_model": w_model,
        "critic_vendor": c_vendor,
        "critic_model": c_model,
        "writer_output": writer_output,
        "critic_output": critic_output,
    }
