"""Multi-browser site audit orchestrator connecting cursors, inspect, truth vault, and verifier."""

from __future__ import annotations

import asyncio
import contextlib
import json
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
    collect_robots_and_sitemap,
    collect_sources,
    enable_base_domains,
)
from bugarena.inspect.matrix import InspectCoverageMatrix
from bugarena.inspect.runner import collect_cross_browser_diff, run_full_site_inspection
from bugarena.truth import AgentScoreboard, Claim, ClaimLedger, EvidenceVault, TranscriptLogger

_EXAGGERATED_ADJECTIVES_RE = re.compile(r"\b(always|all users|every user|catastrophic|100%)\b", re.IGNORECASE)
_INSPECT_PANEL_NAMES = frozenset({
    "elements",
    "console",
    "issues panel",
    "network",
    "security",
    "application",
    "sources",
    "performance",
    "rendering and layers",
    "sensors and emulation",
})


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

        if not sess["browsers"]:
            from bugarena.browser.cursor import AuthorizationError

            raise AuthorizationError(
                "No browser access granted; permit at least one browser via IDE prompt or session_confirm(answers={'browsers': [...]})."
            )
        answers = sess.get("answers", {})
        overrides = {
            k.removesuffix("_path").lower(): str(v)
            for k, v in answers.items()
            if k.endswith("_path") and v and k != "project_path"
        }
        detected = discover_browsers(overrides=overrides)
        by_name = {b.name: b for b in detected}
        granted = [b.lower() for b in sess["browsers"]]
        requested = [b for b in granted if b in by_name and by_name[b].found]
        skipped_browsers = {
            b: by_name[b].notes if b in by_name else "Unknown browser"
            for b in granted
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

            per_browser: dict[str, dict[str, Any]] = {}
            async with asyncio.TaskGroup() as tg:
                tasks = [tg.create_task(_run_browser(b, c)) for b, c in cursors.items()]
            for t in tasks:
                bname, bres = t.result()
                per_browser[bname] = bres

            raw_findings: list[dict[str, Any]] = []
            for res in per_browser.values():
                raw_findings.extend(res["findings"])

            diff_res = collect_cross_browser_diff(per_browser, vault, policy.site_url)
            raw_findings.extend(diff_res.get("findings", []))

            # Merge coverage matrices across ALL browsers & mark Cross-browser diff when >= 2 ran
            matrix = InspectCoverageMatrix(run_dir)
            merged_cov: dict[str, dict[str, Any]] = {}
            for res in per_browser.values():
                for p_item in res["coverage"]["panels"]:
                    pname = p_item["panel"]
                    if pname == "Cross-browser diff":
                        continue
                    cur = merged_cov.setdefault(
                        pname,
                        {"covered": False, "reasons": [], "evidence_ids": [], "findings_count": 0},
                    )
                    if p_item["covered"]:
                        cur["covered"] = True
                    if p_item["reason"]:
                        cur["reasons"].append(p_item["reason"])
                    for eid in p_item["evidence_ids"]:
                        if eid not in cur["evidence_ids"]:
                            cur["evidence_ids"].append(eid)
                    cur["findings_count"] += int(p_item["findings_count"])

            for pname, cur in merged_cov.items():
                matrix.mark_panel(
                    pname,
                    covered=cur["covered"],
                    reason=" | ".join(dict.fromkeys(cur["reasons"])),
                    evidence_ids=tuple(cur["evidence_ids"]),
                    findings_count=cur["findings_count"],
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

            round_num = int(sess.get("round_count", 0)) + 1
            sess["round_count"] = round_num

            # Submit findings into ClaimLedger via CitationChecker + honesty check + verifier pass
            for idx, item in enumerate(raw_findings, 1):
                cid = f"F-{idx:04d}" if round_num == 1 else f"F-R{round_num:02d}-{idx:04d}"
                analyst = _panel_to_analyst(item["panel"])
                ev_txt = vault.read_artifact_text(item["evidence_refs"][0]) or ""
                hint = str(item.get("quote_hint") or "")
                detail_snip = item["detail"][:60] if item.get("detail") else ""
                spans: list[str] = []
                if hint and hint in ev_txt:
                    spans.append(hint)
                elif detail_snip and detail_snip in ev_txt:
                    spans.append(detail_snip)
                c_nums = tuple(n for n in item.get("cited_numbers", ()) if n and n in ev_txt)

                claim = Claim(
                    id=cid,
                    statement=item["title"],
                    evidence_refs=tuple(item["evidence_refs"]),
                    quoted_spans=tuple(spans),
                    cited_numbers=c_nums,
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
                    security_exploitable=bool(item.get("exploitable", False)),
                    common_path_broken=(item.get("severity") == "High"),
                    a11y_or_perf_barrier=(item.get("severity") == "Medium"),
                )
                transcript.log(
                    agent=analyst,
                    cursor=f"[mcp_{item['browsers_affected'][0]}]" if item.get("browsers_affected") else "[mcp_site]",
                    tool="claim.submit",
                    args={"claim_id": cid, "refs": list(claim.evidence_refs)},
                    result_bytes=json.dumps({"accepted": sub["accepted"], "status": str(sub["status"])}),
                )
                if sub["accepted"]:
                    flagged_now = any(
                        h["claim_id"] == cid for h in self.run_honesty_audit(ledger, vault)
                    )
                    verdict = "UNVERIFIED" if flagged_now else "CONFIRMED"
                    v_detail = (
                        "Flagged by honesty audit prior to confirmation."
                        if flagged_now
                        else f"Verified dynamically across {list(per_browser)}"
                    )
                    ledger.record_verification(
                        cid,
                        verifier="verifier",
                        verdict=verdict,
                        detail=v_detail,
                    )
                    transcript.log(
                        agent="verifier",
                        cursor="[mcp_verifier]",
                        tool="claim.verify",
                        args={"claim_id": cid},
                        result_bytes=json.dumps({"verdict": verdict, "detail": v_detail}),
                    )

            honesty_flags = self.run_honesty_audit(ledger, vault)
            merged_smaps: dict[str, dict[str, Any]] = {}
            for res in per_browser.values():
                merged_smaps.update(res.get("source_map_contents", {}))
            if merged_smaps:
                (run_dir / "source_maps.json").write_text(json.dumps(merged_smaps, indent=2), encoding="utf-8")
            state_rec = {
                "run_id": run_id,
                "run_dir": str(run_dir),
                "round": round_num,
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
                with contextlib.suppress(Exception):
                    await cur.close()

    async def inspect_panel(self, run_id: str, browser: str, panel: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Targeted on-demand DevTools panel inspection on the granted browser."""
        sess = self.sessions.get_session(run_id)
        p_low = panel.strip().lower()
        if p_low not in _INSPECT_PANEL_NAMES and not any(
            k in p_low for k in ("element", "console", "issue", "network", "security", "application", "source", "performance", "render", "sensor")
        ):
            raise ValueError(
                f"Unknown panel {panel!r} (unsupported in single-browser inspect_panel); supported: {sorted(_INSPECT_PANEL_NAMES)}"
            )
        policy: AccessPolicy = sess["policy"]
        b_low = browser.strip().lower()
        granted = [b.lower() for b in sess.get("browsers", [])]
        if b_low not in granted:
            from bugarena.browser.cursor import AuthorizationError

            raise AuthorizationError(
                f"Browser '{browser}' is not permitted for this session; granted browsers: {granted}."
            )
        run_dir = Path(sess["run_dir"])
        vault = EvidenceVault(run_dir)
        transcript = TranscriptLogger(run_dir)
        answers = sess.get("answers", {})
        overrides = {
            k.removesuffix("_path").lower(): str(v)
            for k, v in answers.items()
            if k.endswith("_path") and v and k != "project_path"
        }
        by_name = {b.name: b for b in discover_browsers(overrides=overrides)}
        if b_low not in by_name or not by_name[b_low].found:
            raise FileNotFoundError(f"Browser '{browser}' not found on host.")

        target_url = str((args or {}).get("url") or policy.site_url)
        meta_res = await collect_robots_and_sitemap(target_url, vault)
        robots_disallow: tuple[str, ...] = tuple(meta_res.get("robots_disallow", ()))
        policy.assert_action_allowed("navigate", target_url=target_url, robots_disallow=robots_disallow)
        cursor = await BrowserCursor.launch(browser_name=b_low, executable=by_name[b_low].executable, headless=True)
        try:
            assert cursor.cdp is not None
            await enable_base_domains(cursor.cdp)
            await cursor.navigate(target_url, policy=policy, robots_disallow=robots_disallow)
            if "element" in p_low:
                res = await collect_elements(cursor.cdp, vault, target_url, browser)
            elif "console" in p_low or "issue" in p_low:
                res = collect_console_and_issues(cursor.cdp, vault, target_url, browser)
            elif "source" in p_low:
                res = await collect_sources(cursor.cdp, vault, target_url, browser)
            elif "network" in p_low or "security" in p_low:
                res = collect_network_and_security(cursor.cdp, vault, target_url, browser)
            elif "application" in p_low:
                res = await collect_application(cursor.cdp, vault, target_url, browser)
            else:
                res = await collect_performance_rendering_sensors(cursor.cdp, vault, target_url, browser)
            transcript.log(
                agent="inspect_panel",
                cursor=cursor.cursor_name,
                tool=f"panel.{panel}",
                args={"url": target_url},
                result_bytes=json.dumps({"evidence_id": res.get("evidence_id"), "findings": len(res.get("findings", []))}),
            )
            return res
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
