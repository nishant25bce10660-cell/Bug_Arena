"""Multi-browser site audit orchestrator connecting cursors, inspect, truth vault, and verifier."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from bugarena.agents.registry import SITE_ANALYST_ROLES
from bugarena.browser import AccessPolicy, BrowserCursor, SessionManager, discover_browsers
from bugarena.inspect.collectors import (
    collect_application,
    collect_console_and_issues,
    collect_elements,
    collect_network_and_security,
    collect_performance_rendering_sensors,
)
from bugarena.inspect.matrix import InspectCoverageMatrix
from bugarena.inspect.runner import collect_cross_browser_diff, run_full_site_inspection
from bugarena.truth import AgentScoreboard, Claim, ClaimLedger, EvidenceVault, TranscriptLogger

_EXAGGERATED_ADJECTIVES_RE = re.compile(r"\b(always|all users|every user|catastrophic|100%)\b", re.IGNORECASE)


def _panel_to_analyst(panel: str) -> str:
    return {
        "Console": "console-analyst",
        "Issues panel": "console-analyst",
        "Network": "network-analyst",
        "Elements": "dom-a11y-analyst",
        "Application": "storage-security-analyst",
        "Security": "storage-security-analyst",
        "Performance": "performance-memory-analyst",
        "Memory": "performance-memory-analyst",
        "Sources": "js-source-analyst",
        "Rendering and layers": "responsive-analyst",
        "Sensors and emulation": "responsive-analyst",
        "Interaction flows": "dom-a11y-analyst",
        "Cross-browser diff": "cross-browser-diff-analyst",
    }.get(panel, SITE_ANALYST_ROLES[0])


class SiteAuditCoordinator:
    """Runs multi-browser site audits with truth-enforced claims, independent verification, and honesty checks."""

    def __init__(self, output_root: Path | str = "bugarena_reports"):
        self.sessions = SessionManager(default_output_root=output_root)
        self._runs: dict[str, dict[str, Any]] = {}

    def run_honesty_audit(self, ledger: ClaimLedger, vault: EvidenceVault) -> list[dict[str, Any]]:
        """Honesty-auditor red team: flag unsupported absolutes/adjectives or STATIC Critical claims."""
        flagged: list[dict[str, Any]] = []
        for claim in ledger.claims:
            issues: list[str] = []
            if _EXAGGERATED_ADJECTIVES_RE.search(claim.statement):
                issues.append("Contains unquantified absolute claim ('always'/'all users'/'catastrophic').")
            if claim.evidence_type != "DYNAMIC" and (claim.severity == "Critical" or claim.proposed_severity == "Critical"):
                issues.append("STATIC finding proposed Critical severity.")
            if not vault.get(claim.evidence_refs[0]):
                issues.append("Primary evidence_ref missing in vault.")
            if issues:
                flagged.append({"claim_id": claim.id, "issues": issues})
        return flagged

    async def start_and_run_round(
        self,
        run_id: str,
        *,
        headless: bool = True,
        panels: str | list[str] = "all",
        target_url: str | None = None,
    ) -> dict[str, Any]:
        """Launch isolated [mcp_<browser>] cursors for confirmed session, inspect in parallel, verify claims."""
        sess = self.sessions.get_session(run_id)
        run_dir = Path(sess["run_dir"])
        policy: AccessPolicy = sess["policy"]
        effective_url = target_url or policy.site_url
        policy.assert_action_allowed("navigate", target_url=effective_url)
        vault = EvidenceVault(run_dir)
        scoreboard = AgentScoreboard(run_dir)
        ledger = ClaimLedger(run_dir, vault=vault, scoreboard=scoreboard)
        transcript = TranscriptLogger(run_dir)

        detected = discover_browsers()
        by_name = {b.name: b for b in detected}
        requested = [b for b in sess["browsers"] if b in by_name and by_name[b].found]
        skipped_browsers = {
            b: by_name[b].notes if b in by_name else "Unknown browser"
            for b in sess["browsers"]
            if b not in requested
        }
        if not requested:
            raise RuntimeError(f"No granted installed browsers available. Skipped: {skipped_browsers}")

        cursors: dict[str, BrowserCursor] = {}
        try:
            for bname in requested:
                cur = await BrowserCursor.launch(
                    browser_name=bname,
                    executable=by_name[bname].executable,
                    headless=headless,
                )
                cursors[bname] = cur
                self.sessions.register_cursor(run_id, cur)

            sem = asyncio.Semaphore(3)

            async def _run_browser(bname: str, cur: BrowserCursor) -> tuple[str, dict[str, Any]]:
                async with sem:
                    res = await run_full_site_inspection(
                        cursor=cur,
                        url=effective_url,
                        policy=policy,
                        vault=vault,
                        transcript=transcript,
                        panels=panels,
                        write_matrix=False,
                    )
                    return bname, res

            pairs = await asyncio.gather(*[_run_browser(b, c) for b, c in cursors.items()])
            per_browser = dict(pairs)

            raw_findings: list[dict[str, Any]] = []
            for res in per_browser.values():
                raw_findings.extend(res["findings"])

            diff_res = collect_cross_browser_diff(per_browser, vault, policy.site_url)
            raw_findings.extend(diff_res.get("findings", []))

            # Merge coverage matrices & mark Cross-browser diff when >= 2 browsers ran
            matrix = InspectCoverageMatrix(run_dir)
            first_cov = next(iter(per_browser.values()))["coverage"]["panels"]
            for p_item in first_cov:
                if p_item["panel"] == "Cross-browser diff":
                    continue
                matrix.mark_panel(
                    p_item["panel"],
                    covered=p_item["covered"],
                    reason=p_item["reason"],
                    evidence_ids=tuple(p_item["evidence_ids"]),
                    findings_count=p_item["findings_count"],
                )
            if len(per_browser) >= 2:
                matrix.mark_panel(
                    "Cross-browser diff",
                    covered=True,
                    evidence_ids=(diff_res["evidence_id"],) if diff_res.get("evidence_id") else (),
                    findings_count=len(diff_res.get("findings", [])),
                )
            else:
                matrix.mark_panel(
                    "Cross-browser diff",
                    covered=False,
                    reason=f"Single browser run ({list(per_browser)}); skipped={skipped_browsers}",
                )
            matrix.write_markdown()

            # Submit findings into ClaimLedger via CitationChecker + independent verifier pass
            for idx, item in enumerate(raw_findings, 1):
                cid = f"F-{idx:04d}"
                analyst = _panel_to_analyst(item["panel"])
                quote = item["detail"][:60] if item["detail"] else ""
                # Only attach verbatim snippet from stored artifact as quote
                ev_txt = vault.read_artifact_text(item["evidence_refs"][0]) or ""
                verbatim = quote if quote and quote in ev_txt else ""
                claim = Claim(
                    id=cid,
                    statement=item["title"],
                    evidence_refs=tuple(item["evidence_refs"]),
                    quoted_spans=(verbatim,) if verbatim else (),
                    confidence=0.9,
                    found_by=analyst,
                    evidence_type="DYNAMIC",
                    proposed_severity=item.get("severity", "Medium"),
                    where_found=item.get("where_found", {}),
                    how_it_occurs=item.get("detail", ""),
                    fix_guidance=item.get("fix_guidance", ""),
                    browsers_affected=tuple(item.get("browsers_affected", ())),
                )
                sub = ledger.submit_claim(
                    claim,
                    security_exploitable=(item["panel"] == "Security" and item.get("severity") == "High"),
                    common_path_broken=(item.get("severity") == "High"),
                    a11y_or_perf_barrier=(item.get("severity") == "Medium"),
                )
                if sub["accepted"]:
                    ledger.record_verification(
                        cid,
                        verifier="verifier",
                        verdict="CONFIRMED",
                        detail=f"Verified dynamically across {list(per_browser)}",
                    )

            honesty_flags = self.run_honesty_audit(ledger, vault)
            state_rec = {
                "run_id": run_id,
                "run_dir": str(run_dir),
                "browsers_used": list(per_browser),
                "skipped_browsers": skipped_browsers,
                "source_maps": next(iter(per_browser.values())).get("source_maps", {}),
                "screenshots": {b: r["screenshots"] for b, r in per_browser.items()},
                "coverage": matrix.summary(),
                "honesty_flags": honesty_flags,
                "claims_count": len(ledger.claims),
                "confirmed_count": sum(1 for c in ledger.claims if c.status.value == "CONFIRMED"),
            }
            self._runs[run_id] = state_rec
            return state_rec
        finally:
            for cur in cursors.values():
                await cur.close()

    async def inspect_panel(self, run_id: str, browser: str, panel: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Targeted on-demand DevTools panel inspection on the granted browser."""
        sess = self.sessions.get_session(run_id)
        policy: AccessPolicy = sess["policy"]
        run_dir = Path(sess["run_dir"])
        vault = EvidenceVault(run_dir)
        by_name = {b.name: b for b in discover_browsers()}
        if browser not in by_name or not by_name[browser].found:
            raise FileNotFoundError(f"Browser '{browser}' not found on host.")

        target_url = str((args or {}).get("url") or policy.site_url)
        cursor = await BrowserCursor.launch(browser_name=browser, executable=by_name[browser].executable, headless=True)
        try:
            assert cursor.cdp is not None
            await cursor.navigate(target_url, policy=policy)
            p_low = panel.lower()
            if "element" in p_low:
                return await collect_elements(cursor.cdp, vault, target_url, browser)
            if "console" in p_low or "issue" in p_low:
                return collect_console_and_issues(cursor.cdp, vault, target_url, browser)
            if "network" in p_low or "security" in p_low:
                return collect_network_and_security(cursor.cdp, vault, target_url, browser)
            if "application" in p_low:
                return await collect_application(cursor.cdp, vault, target_url, browser)
            return await collect_performance_rendering_sensors(cursor.cdp, vault, target_url, browser)
        finally:
            await cursor.close()

    def status(self, run_id: str) -> dict[str, Any]:
        sess = self.sessions.get_session(run_id)
        run_dir = Path(sess["run_dir"])
        vault = EvidenceVault(run_dir)
        scoreboard = AgentScoreboard(run_dir)
        ledger = ClaimLedger(run_dir, vault=vault, scoreboard=scoreboard)
        return {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "access_level": sess["policy"].access_level,
            "claims_total": len(ledger.claims),
            "confirmed": sum(1 for c in ledger.claims if c.status.value == "CONFIRMED"),
            "retracted": sum(1 for c in ledger.claims if c.status.value == "RETRACTED"),
            "rejected": sum(1 for c in ledger.claims if c.status.value == "REJECTED"),
            "vault_valid": vault.verify_chain()["valid"],
            "details": self._runs.get(run_id, {}),
        }
