"""Site inspection orchestrator, annotated screenshot capture, and cross-browser diff."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from typing import Any

from bugarena.browser.cdp import CDPError
from bugarena.browser.cursor import AccessPolicy, AuthorizationError, BrowserCursor
from bugarena.inspect.collectors import (
    collect_application,
    collect_console_and_issues,
    collect_elements,
    collect_interaction_and_memory,
    collect_network_and_security,
    collect_performance_rendering_sensors,
    collect_robots_and_sitemap,
    collect_sources,
    compute_lighthouse_style_scores,
    enable_base_domains,
)
from bugarena.inspect.matrix import ALL_PANELS, InspectCoverageMatrix
from bugarena.truth.transcript import TranscriptLogger
from bugarena.truth.vault import EvidenceVault


def collect_cross_browser_diff(
    per_browser_results: dict[str, dict[str, Any]],
    vault: EvidenceVault,
    url: str,
) -> dict[str, Any]:
    """Compare findings across granted browsers and flag browser-specific discrepancies."""
    if len(per_browser_results) < 2:
        return {"compared": list(per_browser_results.keys()), "diffs": [], "evidence_id": ""}

    title_sets = {
        b: {f["title"] for f in res.get("findings", [])} for b, res in per_browser_results.items()
    }
    union = set().union(*title_sets.values()) if title_sets else set()
    diffs: list[dict[str, Any]] = []
    for title in sorted(union):
        present_in = [b for b, s in title_sets.items() if title in s]
        absent_in = [b for b, s in title_sets.items() if title not in s]
        if absent_in:
            diffs.append({"finding_title": title, "present_in": present_in, "absent_in": absent_in})

    ev = vault.record_artifact(
        json.dumps({"browsers": list(per_browser_results), "diffs": diffs}, indent=2),
        ext=".json",
        tool_name="inspect.cross_browser_diff",
        args_summary=url,
    )
    findings = [
        {
            "panel": "Cross-browser diff",
            "title": f"Browser discrepancy ({','.join(d['present_in'])} vs {','.join(d['absent_in'])}): {d['finding_title'][:70]}",
            "severity": "Medium",
            "detail": json.dumps(d),
            "evidence_refs": [ev.evidence_id],
            "where_found": {"url": url, "panel": "Cross-browser diff", "selector": "", "script_url": ""},
            "quote_hint": d["finding_title"][:55],
            "fix_guidance": "Normalize browser-specific APIs and CSS layout across Chromium derivatives.",
            "browsers_affected": d["present_in"],
        }
        for d in diffs
    ]
    return {"compared": list(per_browser_results), "diffs": diffs, "findings": findings, "evidence_id": ev.evidence_id}


async def capture_screenshots(
    cursor: BrowserCursor,
    vault: EvidenceVault,
    url: str,
    *,
    annotate_selector: str = "img:not([alt]), #dup-widget, .wide-mobile-break",
    label: str = "BUGARENA",
) -> dict[str, str]:
    """Capture raw PNG screenshot and annotated PNG overlay natively via Chromium CDP."""
    assert cursor.cdp is not None
    raw_res = await cursor.cdp.send("Page.captureScreenshot", {"format": "png"})
    raw_bytes = base64.b64decode(raw_res["data"])
    raw_ev = vault.record_artifact(
        raw_bytes,
        ext=".png",
        tool_name="cdp.captureScreenshot_raw",
        args_summary=url,
        mime_type="image/png",
        is_binary=True,
    )

    # Render non-destructive highlight box in Chromium and capture annotated PNG (always cleanup in finally)
    highlight_js = (
        "(() => { const el = document.querySelector(" + json.dumps(annotate_selector) + "); "
        "const box = document.createElement('div'); box.id='__ba_ann_box'; "
        "const r = el ? el.getBoundingClientRect() : {left:12,top:12,width:240,height:36}; "
        "box.style.cssText = `position:fixed;left:${Math.max(4,r.left)}px;top:${Math.max(4,r.top)}px;"
        "width:${Math.max(60,r.width)}px;height:${Math.max(24,r.height)}px;border:3px solid #dc2626;"
        "background:rgba(220,38,38,0.12);z-index:2147483646;pointer-events:none;font:bold 12px monospace;color:#dc2626;`;"
        f"box.textContent = {json.dumps(label)}; document.documentElement.appendChild(box); return true; }})()"
    )
    try:
        with contextlib.suppress(CDPError):
            await cursor.cdp.send("Runtime.evaluate", {"expression": highlight_js})
        ann_res = await cursor.cdp.send("Page.captureScreenshot", {"format": "png"})
    finally:
        with contextlib.suppress(CDPError):
            await cursor.cdp.send("Runtime.evaluate", {"expression": "document.getElementById('__ba_ann_box')?.remove();"})
    ann_bytes = base64.b64decode(ann_res["data"])
    ann_ev = vault.record_artifact(
        ann_bytes,
        ext=".png",
        tool_name="cdp.captureScreenshot_annotated",
        args_summary=f"{url} ({label})",
        mime_type="image/png",
        is_binary=True,
    )
    return {"raw_id": raw_ev.evidence_id, "annotated_id": ann_ev.evidence_id}


async def run_full_site_inspection(
    *,
    cursor: BrowserCursor,
    url: str,
    policy: AccessPolicy,
    vault: EvidenceVault,
    transcript: TranscriptLogger,
    panels: str | list[str] = "all",
    write_matrix: bool = True,
) -> dict[str, Any]:
    """Run all requested DevTools panels across the target URL, storing evidence only via EvidenceVault."""
    assert cursor.cdp is not None
    if panels == "all":
        selected = set(ALL_PANELS)
    else:
        selected = set(panels)
        unknown = selected - set(ALL_PANELS)
        if unknown:
            raise ValueError(f"Unknown panel(s): {sorted(unknown)}")
    matrix = InspectCoverageMatrix(vault.run_dir)
    all_findings: list[dict[str, Any]] = []

    meta_res = await collect_robots_and_sitemap(url, vault)
    robots_disallow: tuple[str, ...] = tuple(meta_res.get("robots_disallow", ()))
    domain_failures = await enable_base_domains(cursor.cdp)
    await cursor.navigate(url, policy=policy, robots_disallow=robots_disallow)
    await asyncio.sleep(0.25)

    screenshots = await capture_screenshots(cursor, vault, url, label=cursor.cursor_name)
    transcript.log(
        agent="inspect",
        cursor=cursor.cursor_name,
        tool="cdp.navigate_and_snapshot",
        args={"url": url},
        result_bytes=json.dumps({"meta": meta_res["evidence_id"], "domain_failures": domain_failures, **screenshots}),
    )

    elem_res = await collect_elements(cursor.cdp, vault, url, cursor.browser_name)
    if "Elements" in selected:
        all_findings.extend(elem_res["findings"])
        matrix.mark_panel("Elements", covered=True, evidence_ids=(elem_res["evidence_id"],), findings_count=len(elem_res["findings"]))
    else:
        matrix.mark_panel("Elements", covered=False, reason="Excluded by user panel selection")

    con_res = collect_console_and_issues(cursor.cdp, vault, url, cursor.browser_name)
    con_findings = [f for f in con_res["findings"] if f["panel"] == "Console"]
    iss_findings = [f for f in con_res["findings"] if f["panel"] == "Issues panel"]
    if "Console" in selected:
        all_findings.extend(con_findings)
        matrix.mark_panel("Console", covered=True, evidence_ids=(con_res["evidence_id"],), findings_count=len(con_findings))
    else:
        matrix.mark_panel("Console", covered=False, reason="Excluded by user panel selection")
    if "Issues panel" in selected:
        all_findings.extend(iss_findings)
        matrix.mark_panel("Issues panel", covered=True, evidence_ids=(con_res["evidence_id"],), findings_count=len(iss_findings))
    else:
        matrix.mark_panel("Issues panel", covered=False, reason="Excluded by user panel selection")

    src_res = await collect_sources(cursor.cdp, vault, url, cursor.browser_name)
    if "Sources" in selected:
        all_findings.extend(src_res["findings"])
        matrix.mark_panel("Sources", covered=True, evidence_ids=(src_res["evidence_id"],), findings_count=len(src_res["findings"]))
    else:
        matrix.mark_panel("Sources", covered=False, reason="Excluded by user panel selection")

    net_res = collect_network_and_security(cursor.cdp, vault, url, cursor.browser_name)
    net_findings = [f for f in net_res["findings"] if f["panel"] == "Network"]
    sec_findings = [f for f in net_res["findings"] if f["panel"] == "Security"]
    if "Network" in selected:
        all_findings.extend(net_findings)
        matrix.mark_panel("Network", covered=True, evidence_ids=(net_res["evidence_id"],), findings_count=len(net_findings))
    else:
        matrix.mark_panel("Network", covered=False, reason="Excluded by user panel selection")
    if "Security" in selected:
        all_findings.extend(sec_findings)
        matrix.mark_panel("Security", covered=True, evidence_ids=(net_res["evidence_id"],), findings_count=len(sec_findings))
    else:
        matrix.mark_panel("Security", covered=False, reason="Excluded by user panel selection")

    app_res = await collect_application(cursor.cdp, vault, url, cursor.browser_name)
    if "Application" in selected:
        all_findings.extend(app_res["findings"])
        matrix.mark_panel("Application", covered=True, evidence_ids=(app_res["evidence_id"],), findings_count=len(app_res["findings"]))
    else:
        matrix.mark_panel("Application", covered=False, reason="Excluded by user panel selection")

    prs_res = await collect_performance_rendering_sensors(cursor.cdp, vault, url, cursor.browser_name)
    rend_findings = [f for f in prs_res["findings"] if f["panel"] == "Rendering and layers"]
    sens_findings = [f for f in prs_res["findings"] if f["panel"] == "Sensors and emulation"]
    if "Performance" in selected:
        matrix.mark_panel("Performance", covered=True, evidence_ids=(prs_res["evidence_id"],))
    else:
        matrix.mark_panel("Performance", covered=False, reason="Excluded by user panel selection")
    if "Rendering and layers" in selected:
        all_findings.extend(rend_findings)
        matrix.mark_panel("Rendering and layers", covered=True, evidence_ids=(prs_res["evidence_id"],), findings_count=len(rend_findings))
    else:
        matrix.mark_panel("Rendering and layers", covered=False, reason="Excluded by user panel selection")
    if "Sensors and emulation" in selected:
        all_findings.extend(sens_findings)
        matrix.mark_panel("Sensors and emulation", covered=True, evidence_ids=(prs_res["evidence_id"],), findings_count=len(sens_findings))
    else:
        matrix.mark_panel("Sensors and emulation", covered=False, reason="Excluded by user panel selection")

    if "Interaction flows" in selected or "Memory" in selected:
        try:
            inter_res = await collect_interaction_and_memory(
                cursor,
                vault,
                policy,
                url,
                elem_res["data"].get("links", []),
                transcript,
                robots_disallow=robots_disallow,
            )
            int_findings = [f for f in inter_res["findings"] if f["panel"] == "Interaction flows"]
            mem_findings = [f for f in inter_res["findings"] if f["panel"] == "Memory"]
            if "Interaction flows" in selected:
                all_findings.extend(int_findings)
                matrix.mark_panel("Interaction flows", covered=True, evidence_ids=(inter_res["evidence_id"],), findings_count=len(int_findings))
            else:
                matrix.mark_panel("Interaction flows", covered=False, reason="Excluded by user panel selection")
            if "Memory" in selected:
                all_findings.extend(mem_findings)
                matrix.mark_panel("Memory", covered=True, evidence_ids=(inter_res["evidence_id"],), findings_count=len(mem_findings))
            else:
                matrix.mark_panel("Memory", covered=False, reason="Excluded by user panel selection")
        except AuthorizationError as err:
            matrix.mark_panel("Interaction flows", covered=False, reason=str(err))
            matrix.mark_panel("Memory", covered=False, reason="Interaction allocation blocked in passive mode")
    else:
        matrix.mark_panel("Interaction flows", covered=False, reason="Excluded by user panel selection")
        matrix.mark_panel("Memory", covered=False, reason="Excluded by user panel selection")

    if "Lighthouse-style" in selected:
        lh_res = compute_lighthouse_style_scores(all_findings, vault, url)
        lh_scores = lh_res["scores"]
        matrix.mark_panel("Lighthouse-style", covered=True, evidence_ids=(lh_res["evidence_id"],))
    else:
        lh_scores = {}
        matrix.mark_panel("Lighthouse-style", covered=False, reason="Excluded by user panel selection")
    matrix.mark_panel("Cross-browser diff", covered=False, reason="Single browser run; compare in multi-browser orchestrator")

    if write_matrix:
        matrix.write_markdown()

    return {
        "browser": cursor.browser_name,
        "cursor": cursor.cursor_name,
        "url": url,
        "findings": all_findings,
        "source_maps": src_res["source_maps"],
        "source_map_contents": src_res.get("source_map_contents", {}),
        "screenshots": screenshots,
        "lighthouse_scores": lh_scores,
        "coverage": matrix.summary(),
    }
