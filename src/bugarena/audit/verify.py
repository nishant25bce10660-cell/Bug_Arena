"""Independent second-agent verification and Section 8 severity grading."""

from __future__ import annotations

from pathlib import Path

from bugarena.audit.ledger import (
    EvidenceType,
    Finding,
    FindingLedger,
    FindingState,
    SeverityLevel,
)
from bugarena.audit.probes import run_isolated_probe


def apply_severity_rubric(
    proposed: SeverityLevel,
    *,
    category: str,
    evidence_type: EvidenceType,
    what_it_is: str,
) -> tuple[SeverityLevel, str]:
    """
    Enforce Section 8 severity rubric:
      - Critical: arbitrary code/file access beyond doc, silent corruption, broken core Red->Green gate
      - High: wrong results/crashes on common inputs, security hardening gaps, state corruption
      - Medium: edge-input bugs, misleading output, resource waste
      - Low: cosmetic, hygiene, docs
    Rules: missing dependency / doc drift is never Critical; STATIC findings cannot be Critical.
    """
    text_lower = f"{category} {what_it_is}".lower()
    is_doc_or_dep = category in ("docs", "doc_drift", "hygiene") or (
        "missing" in text_lower and "dependency" in text_lower
    ) or "readme" in text_lower or "skill.md" in text_lower

    sev = proposed
    if is_doc_or_dep and sev == SeverityLevel.CRITICAL:
        sev = SeverityLevel.HIGH if "dependency" in text_lower else SeverityLevel.LOW

    if evidence_type != EvidenceType.DYNAMIC and sev == SeverityLevel.CRITICAL:
        sev = SeverityLevel.HIGH

    justification = {
        SeverityLevel.CRITICAL: "Verified dynamic defect causing RCE/file exposure, data corruption, or Red->Green gate failure.",
        SeverityLevel.HIGH: "Substantial security hardening gap, state hazard, or frequent functional failure.",
        SeverityLevel.MEDIUM: "Edge-case defect, misleading output, or bounded performance/resource inefficiency.",
        SeverityLevel.LOW: "Cosmetic, packaging hygiene, or documentation drift.",
    }[sev]
    return sev, justification


def choose_independent_verifier(found_by: str) -> str:
    """Pick an independent verifier role guaranteed to differ from found_by."""
    if found_by != "code-architect":
        return "code-architect"
    return "architect"


def verify_finding(
    repo_path: Path | str,
    ledger: FindingLedger,
    finding_id: str,
    *,
    verifier_agent: str | None = None,
    timeout_seconds: float = 15.0,
) -> Finding:
    """
    Independently verify a finding by running its reproduction probe in an isolated temp sandbox.
    Updates state in ledger according to Section 5 rules:
      - probe exits != 0 OR stdout contains 'REPRODUCED:' -> CONFIRMED (DYNAMIC)
      - probe exits 0 with 'DISPROVED:' -> DISMISSED (stores verification_output)
      - no probe script available -> UNVERIFIED / STATIC (never CONFIRMED)
    """
    finding = ledger.get(finding_id)
    if finding is None:
        raise KeyError(f"Finding '{finding_id}' not found in ledger.")

    verifier = verifier_agent or choose_independent_verifier(finding.found_by)
    if verifier == finding.found_by:
        verifier = choose_independent_verifier(finding.found_by)

    # Preserve already FIXED / WONTFIX entries unless explicitly re-verified manually
    if finding.state in (FindingState.FIXED, FindingState.WONTFIX, FindingState.WONTFIX_NEEDS_HUMAN):
        return finding

    probe_script = finding.repro.probe_script.strip()
    if not probe_script:
        if finding.category in ("docs", "doc_drift"):
            updated = finding.model_copy(
                update={
                    "state": FindingState.UNVERIFIED,
                    "evidence_type": EvidenceType.DOC_COMPARE,
                    "verified_by": verifier,
                    "verification_output": "No runnable probe script; doc-compare claim.",
                }
            )
        else:
            sev, just = apply_severity_rubric(
                finding.proposed_severity,
                category=finding.category,
                evidence_type=EvidenceType.STATIC,
                what_it_is=finding.what_it_is,
            )
            updated = finding.model_copy(
                update={
                    "state": FindingState.UNVERIFIED,
                    "evidence_type": EvidenceType.STATIC,
                    "proposed_severity": sev,
                    "severity_justification": just,
                    "verified_by": verifier,
                    "verification_output": "Static finding without executable probe_script.",
                }
            )
        ledger.upsert(updated)
        return updated

    # Execute isolated dynamic probe
    outcome = run_isolated_probe(repo_path, probe_script, timeout_seconds=timeout_seconds)
    combined = f"EXIT={outcome.exit_code}\nSTDOUT:\n{outcome.stdout}\nSTDERR:\n{outcome.stderr}".strip()

    if outcome.timed_out:
        sev, just = apply_severity_rubric(
            finding.proposed_severity,
            category=finding.category,
            evidence_type=EvidenceType.STATIC,
            what_it_is=finding.what_it_is,
        )
        updated = finding.model_copy(
            update={
                "state": FindingState.UNVERIFIED,
                "evidence_type": EvidenceType.STATIC,
                "proposed_severity": sev,
                "severity_justification": just,
                "verified_by": verifier,
                "verification_output": f"Probe timed out after {timeout_seconds}s.\n{combined}",
            }
        )
        ledger.upsert(updated)
        return updated

    if "DISPROVED:" in outcome.stdout or (
        outcome.exit_code == 0 and "REPRODUCED:" not in outcome.stdout
    ):
        # Probe succeeded without reproducing failure -> finding no longer reproduces (DISMISSED)
        sev, just = apply_severity_rubric(
            finding.proposed_severity,
            category=finding.category,
            evidence_type=EvidenceType.DYNAMIC,
            what_it_is=finding.what_it_is,
        )
        updated = finding.model_copy(
            update={
                "state": FindingState.DISMISSED,
                "evidence_type": EvidenceType.DYNAMIC,
                "proposed_severity": sev,
                "severity_justification": just,
                "verified_by": verifier,
                "verification_output": combined or "EXIT=0 (repro did not trigger defect)",
            }
        )
        ledger.upsert(updated)
        return updated

    # Defect reproduced! (exit_code != 0 or REPRODUCED: marker printed)
    sev, just = apply_severity_rubric(
        finding.proposed_severity,
        category=finding.category,
        evidence_type=EvidenceType.DYNAMIC,
        what_it_is=finding.what_it_is,
    )
    updated = finding.model_copy(
        update={
            "state": FindingState.CONFIRMED,
            "evidence_type": EvidenceType.DYNAMIC,
            "proposed_severity": sev,
            "severity_justification": just,
            "verified_by": verifier,
            "verification_output": combined,
        }
    )
    ledger.upsert(updated)
    return updated
