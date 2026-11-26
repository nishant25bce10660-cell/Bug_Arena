"""BugArena MCP v2 Section 1 & 12 Report Bundle Builder (REPORT.md, Chromium REPORT.pdf, per-finding folders)."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import html
import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bugarena.browser import BrowserCursor, discover_browsers
from bugarena.sandbox.security import validate_safe_path
from bugarena.truth import AgentScoreboard, Claim, ClaimLedger, ClaimStatus, EvidenceVault
from bugarena.truth.vault import scrub_evidence_text


def _minimal_pdf_bytes(title: str, lines: list[str]) -> bytes:
    """Minimal valid %PDF-1.4 fallback when Chromium binary is unavailable in CI."""
    escaped = [
        f"BT /F1 11 Tf 40 {760 - idx * 14} Td ({line[:90].replace('(', '[').replace(')', ']')}) Tj ET"
        for idx, line in enumerate([title, *lines[:45]])
    ]
    stream = "\n".join(escaped).encode("latin1", errors="replace")
    objs = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n",
        f"4 0 obj << /Length {len(stream)} >> stream\n".encode("ascii") + stream + b"\nendstream\nendobj\n",
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = [0]
    for obj in objs:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


async def _chromium_render_pdf(html_path: Path, pdf_path: Path, executable: str, browser_name: str) -> None:
    cursor = await BrowserCursor.launch(browser_name=browser_name, executable=executable, headless=True)
    try:
        assert cursor.cdp is not None
        file_url = html_path.resolve().as_uri()
        load_before = len(cursor.cdp.events.get("Page.loadEventFired", []))
        res = await cursor.cdp.send("Page.navigate", {"url": file_url})
        if isinstance(res, dict) and res.get("errorText"):
            raise RuntimeError(f"Page.navigate failed rendering PDF: {res['errorText']}")
        loaded = False
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if len(cursor.cdp.events.get("Page.loadEventFired", [])) > load_before:
                loaded = True
                break
            with contextlib.suppress(Exception):
                st = await cursor.cdp.send("Runtime.evaluate", {"expression": "document.readyState", "returnByValue": True})
                if st.get("result", {}).get("value") == "complete":
                    loaded = True
                    break
            await asyncio.sleep(0.1)
        if not loaded:
            raise TimeoutError(f"Timed out waiting for PDF HTML render readiness on {html_path}")
        await asyncio.sleep(0.2)
        pdf_res = await cursor.cdp.send(
            "Page.printToPDF",
            {
                "printBackground": True,
                "displayHeaderFooter": True,
                "headerTemplate": "<div style='font-size:8px;color:#666;width:100%;text-align:center;'>BugArena MCP v2 Audit Report</div>",
                "footerTemplate": "<div style='font-size:8px;color:#666;width:100%;text-align:center;'>Page <span class='pageNumber'></span> of <span class='totalPages'></span></div>",
                "marginTop": 0.6,
                "marginBottom": 0.6,
            },
            timeout=25.0,
        )
        pdf_path.write_bytes(base64.b64decode(pdf_res["data"]))
    finally:
        await cursor.close()


def _render_html_from_report(run_dir: Path, md_text: str, confirmed: list[Claim], vault: EvidenceVault) -> str:
    img_tags: list[str] = []
    seen_ev: set[str] = set()
    ref_to_claims: dict[str, list[str]] = {}
    for c in confirmed:
        for ref in c.evidence_refs:
            ref_to_claims.setdefault(ref, []).append(c.id)

    for ent in vault.entries():
        if ent.evidence_id in seen_ev:
            continue
        if ent.rel_path.lower().endswith((".png", ".jpg", ".jpeg")):
            seen_ev.add(ent.evidence_id)
            img_path = validate_safe_path(run_dir, ent.rel_path)
            if img_path.is_file():
                b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
                mime = "image/jpeg" if ent.rel_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
                cids = ", ".join(ref_to_claims.get(ent.evidence_id, [])) or ent.tool_name
                img_tags.append(
                    f"<figure><figcaption>{html.escape(cids)} — {html.escape(ent.evidence_id)} "
                    f"(sha256:{ent.sha256[:12]})</figcaption>"
                    f"<img src='data:{mime};base64,{b64}' style='max-width:100%;border:1px solid #ccc;'/></figure>"
                )
    body_pre = html.escape(md_text)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>BugArena Report</title>"
        "<style>@page{size:A4;margin:16mm;}body{font-family:system-ui,sans-serif;font-size:11px;line-height:1.45;color:#111;}"
        "pre{white-space:pre-wrap;word-break:break-word;background:#f8fafc;padding:12px;border:1px solid #e2e8f0;}"
        "figure{margin:14px 0;page-break-inside:avoid;}figcaption{font-weight:600;margin-bottom:4px;}</style>"
        f"</head><body><h1>BugArena MCP v2 Report</h1><pre>{body_pre}</pre>"
        f"<h2>Embedded Visual Evidence</h2>{''.join(img_tags) or '<p>No PNG screenshots recorded.</p>'}"
        "</body></html>"
    )


def _write_finding_folder(run_dir: Path, claim: Claim, vault: EvidenceVault) -> None:
    fdir = validate_safe_path(run_dir, f"findings/{claim.id}")
    ev_sub = fdir / "evidence"
    ev_sub.mkdir(parents=True, exist_ok=True)
    (fdir / "finding.json").write_text(claim.model_dump_json(indent=2), encoding="utf-8")

    steps_md = "\n".join(f"{i}. {st}" for i, st in enumerate(claim.repro_steps, 1)) or "1. Open target URL\n2. Inspect panel evidence"
    (fdir / "repro.md").write_text(
        f"# Reproduction: {claim.id} — {claim.statement}\n\n"
        f"- **Where Found:** `{json.dumps(claim.where_found)}`\n"
        f"- **Severity:** `{claim.severity}` ({claim.severity_justification})\n\n"
        f"## Steps\n{steps_md}\n",
        encoding="utf-8",
    )

    target_url = str(claim.where_found.get("url") or "http://127.0.0.1")
    selector = str(claim.where_found.get("selector") or "body")
    repro_py = (
        '"""Replayable CDP verification script for ' + claim.id + '."""\n\n'
        "import asyncio\nimport json\nfrom bugarena.browser import AccessPolicy, BrowserCursor, discover_browsers\n\n"
        f"TARGET_URL = {target_url!r}\n"
        f"SELECTOR = {selector!r}\n\n"
        "async def replay() -> dict:\n"
        "    browsers = [b for b in discover_browsers() if b.found]\n"
        "    if not browsers:\n"
        "        return {'status': 'CANNOT_RUN', 'reason': 'No browser installed'}\n"
        "    policy = AccessPolicy.from_answers({'site_url': TARGET_URL, 'authorization': 'neither'})\n"
        "    cur = await BrowserCursor.launch(browser_name=browsers[0].name, executable=browsers[0].executable, headless=True)\n"
        "    try:\n"
        "        try:\n"
        "            await cur.navigate(TARGET_URL, policy=policy)\n"
        "        except Exception as exc:\n"
        "            return {'status': 'CANNOT_RUN', 'reason': str(exc)}\n"
        "        expr = f'Boolean(document.querySelector({json.dumps(SELECTOR)}))'\n"
        "        res = await cur.cdp.send('Runtime.evaluate', {'expression': expr, 'returnByValue': True})\n"
        "        present = bool(res.get('result', {}).get('value'))\n"
        "        return {'status': 'MATCH' if present else 'MISMATCH', 'selector_present': present}\n"
        "    finally:\n"
        "        await cur.close()\n\n"
        "if __name__ == '__main__':\n"
        "    print(asyncio.run(replay()))\n"
    )
    (fdir / "repro_script.py").write_text(repro_py, encoding="utf-8")

    (fdir / "fix.md").write_text(
        f"# Remediation Guidance: {claim.id}\n\n"
        f"## Recommended Fix\n{claim.fix_guidance or 'Apply input/null guards, secure headers, and accessibility fixes.'}\n\n"
        "## References\n- OWASP Web Security Testing Guide\n- WCAG 2.2 AA\n- MDN Web Docs\n",
        encoding="utf-8",
    )

    for ref in claim.evidence_refs:
        ent = vault.get(ref)
        if ent:
            src = validate_safe_path(run_dir, ent.rel_path)
            if src.is_file():
                shutil.copy2(src, ev_sub / src.name)


def build_v2_report_bundle(
    run_dir: Path | str,
    *,
    formats: tuple[str, ...] = ("md", "pdf"),
    analysis_summary: dict[str, Any] | None = None,
    allow_fallback_pdf: bool = True,
) -> dict[str, Any]:
    """Build REPORT.md, REPORT.pdf, report.json, findings/F-XXXX/, and unverified_leads.md."""
    rdir = Path(run_dir).resolve()
    vault = EvidenceVault(rdir)
    chain = vault.verify_chain()
    sb = AgentScoreboard(rdir)
    ledger = ClaimLedger(rdir, vault=vault, scoreboard=sb)

    confirmed = [c for c in ledger.claims if c.status == ClaimStatus.CONFIRMED and chain["valid"]]
    unverified = [c for c in ledger.claims if c not in confirmed]

    for c in confirmed:
        _write_finding_folder(rdir, c, vault)

    unv_lines = ["# Unverified, Retracted, & Rejected Leads", ""]
    if not unverified:
        unv_lines.append("None.")
    else:
        for u in unverified:
            unv_lines.append(f"- `{u.id}` [**{u.status.value}** / `{u.found_by}`] {u.statement} (refs={list(u.evidence_refs)})")
    (rdir / "unverified_leads.md").write_text("\n".join(unv_lines) + "\n", encoding="utf-8")

    sev_counts: dict[str, int] = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    for c in confirmed:
        sev = c.severity or c.proposed_severity or "Medium"
        sev_counts[sev] = sev_counts.get(sev, 0) + 1

    scope_txt = (rdir / "scope_and_authorization.md").read_text(encoding="utf-8") if (rdir / "scope_and_authorization.md").is_file() else "Scope not recorded."
    cov_txt = (rdir / "coverage_matrix.md").read_text(encoding="utf-8") if (rdir / "coverage_matrix.md").is_file() else "Coverage matrix not generated."
    corr_txt = sb.corrections_path.read_text(encoding="utf-8") if sb.corrections_path.is_file() else "None."

    lines = [
        "# BugArena MCP v2 — Site & Project Audit Report",
        "",
        f"- **Generated (UTC):** `{datetime.now(UTC).isoformat(timespec='seconds')}`",
        f"- **Run Directory:** `{rdir.name}`",
        f"- **Confirmed Findings:** `{len(confirmed)}` | **Unverified Leads:** `{len(unverified)}` | **Vault Integrity:** `{'VALID' if chain['valid'] else 'BROKEN'}`",
        "",
        "## Table of Contents",
        "1. Executive Summary",
        "2. Scope, Authorization & Responsible Disclosure",
        "3. Method & Tooling",
        "4. DevTools Coverage Matrix & Limitations",
        "5. Confirmed Findings",
        "6. Cross-Browser Differences & Systemic Clusters",
        "7. Appendices (A: Unverified Leads, B: Corrections Log, C: Agent Scoreboard, D: Evidence Index)",
        "",
        "## 1. Executive Summary",
        f"- **Severity Breakdown:** Critical={sev_counts['Critical']}, High={sev_counts['High']}, Medium={sev_counts['Medium']}, Low={sev_counts['Low']}",
    ]
    if not chain["valid"]:
        lines.append(f"- **Vault Verification Errors:** `{'; '.join(chain['errors'])}`")
    if analysis_summary and analysis_summary.get("writer_output"):
        w_out = analysis_summary["writer_output"]
        lines.append(f"- **Analysis Summary ({w_out.get('mode', 'unknown')}):** {w_out.get('executive_summary', '')}")
        if w_out.get("fallback_reason"):
            lines.append(f"- **Analysis Fallback Reason:** `{w_out['fallback_reason']}`")
    if analysis_summary and analysis_summary.get("critic_output"):
        c_out = analysis_summary["critic_output"]
        lines.append(f"- **Critic Verdict:** `{c_out.get('verdict', '')}` — {c_out.get('notes', '')}")
    lines.extend([
        "",
        "## 2. Scope, Authorization & Responsible Disclosure",
        scope_txt.strip(),
        "",
        (
            "> **Responsible Disclosure Notice:** This report is intended exclusively for the authorized site/project owner. "
            "All credentials, cookies, tokens, and PII were scrubbed prior to storage; no exploit chains are included."
        ),
        "",
        "## 3. Method & Tooling",
        "- **Verification Gate:** Only `CONFIRMED` findings backed by intact `EvidenceVault` SHA-256 chains appear in Section 5.",
        "- **Ecosystems Used:** ECC agents, Superpowers TDD/verification, Ponytail minimal-diff rules, Context-Mode context hygiene.",
        "",
        "## 4. DevTools Coverage Matrix & Limitations",
        cov_txt.strip(),
        "",
        "## 5. Confirmed Findings",
    ])
    if not confirmed:
        lines.append("No confirmed findings recorded.")
    else:
        for c in confirmed:
            lines.extend([
                f"### {c.id} — {c.statement}",
                f"- **Severity:** `{c.severity}` ({c.severity_justification}) | **Confidence:** `{c.confidence:.2f}` | **Origin:** `{c.origin}`",
                f"- **Browsers Affected:** `{', '.join(c.browsers_affected) or 'n/a'}`",
                f"- **Where Found:** `{json.dumps(c.where_found)}`",
                f"- **How It Occurs:** {c.how_it_occurs or c.statement}",
                f"- **How to Reproduce:** See `findings/{c.id}/repro.md` and `findings/{c.id}/repro_script.py`",
                f"- **Proof & Vault Hashes:** Refs `{list(c.evidence_refs)}`",
                f"- **How to Fix:** {c.fix_guidance or f'See findings/{c.id}/fix.md'}",
                f"- **Verified By:** `{c.verified_by}` | **Direct Observation Limits:** {c.limitations}",
                "",
            ])

    lines.extend([
        "## 6. Cross-Browser Differences & Systemic Clusters",
        f"Cross-browser findings confirmed: `{sum(1 for c in confirmed if c.where_found.get('panel') == 'Cross-browser diff')}`",
        "",
        "## 7. Appendices",
        "### Appendix A — Unverified Leads",
        "\n".join(unv_lines),
        "",
        "### Appendix B — Corrections Log",
        corr_txt.strip(),
        "",
        "### Appendix C — Agent Scoreboard",
    ])
    for name, sc in sorted(sb.all_scores().items()):
        lines.append(
            f"- `{name}`: honesty={sc.honesty:.2f}, precision={sc.precision:.2f}, brier={sc.calibration_brier:.3f}, quarantined={sc.quarantined}"
        )
    if not sb.all_scores():
        lines.append("- No agent scores recorded.")

    lines.extend(["", "### Appendix D — Evidence Index (SHA-256)"])
    for ent in vault.entries():
        lines.append(f"- `{ent.evidence_id}` | `{ent.tool_name}` | `{ent.rel_path}` | `sha256:{ent.sha256}`")

    md_text, _ = scrub_evidence_text("\n".join(lines) + "\n")
    if "md" in formats:
        (rdir / "REPORT.md").write_text(md_text, encoding="utf-8")

    report_json = {
        "run_id": rdir.name,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "vault_valid": chain["valid"],
        "vault_errors": list(chain["errors"]),
        "confirmed_count": len(confirmed),
        "unverified_count": len(unverified),
        "severity_counts": sev_counts,
        "analysis": analysis_summary,
        "findings": [c.model_dump() for c in confirmed],
    }
    (rdir / "report.json").write_text(json.dumps(report_json, indent=2), encoding="utf-8")

    pdf_engine = "none"
    pdf_error = ""
    if "pdf" in formats:
        pdf_path = rdir / "REPORT.pdf"
        installed = [b for b in discover_browsers() if b.found]
        if installed:
            html_tmp = rdir / "_render_report.html"
            html_tmp.write_text(_render_html_from_report(rdir, md_text, confirmed, vault), encoding="utf-8")
            try:
                def _run_pdf() -> None:
                    asyncio.run(_chromium_render_pdf(html_tmp, pdf_path, installed[0].executable, installed[0].name))

                try:
                    asyncio.get_running_loop()
                    in_loop = True
                except RuntimeError:
                    in_loop = False

                if in_loop:
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        pool.submit(_run_pdf).result()
                else:
                    _run_pdf()
                pdf_engine = "chromium"
            except Exception as exc:
                if not allow_fallback_pdf:
                    raise
                pdf_error = str(exc)
                pdf_path.write_bytes(_minimal_pdf_bytes("BugArena MCP v2 Report", md_text.splitlines()))
                pdf_engine = "stdlib_fallback"
            finally:
                if html_tmp.exists():
                    html_tmp.unlink()
        elif allow_fallback_pdf:
            pdf_path.write_bytes(_minimal_pdf_bytes("BugArena MCP v2 Report", md_text.splitlines()))
            pdf_engine = "stdlib_fallback"
        else:
            raise RuntimeError("No Chromium browser available for Page.printToPDF.")

    return {
        "run_dir": str(rdir),
        "report_md": str(rdir / "REPORT.md") if "md" in formats else "",
        "report_pdf": str(rdir / "REPORT.pdf") if "pdf" in formats else "",
        "report_json": str(rdir / "report.json"),
        "confirmed_count": len(confirmed),
        "unverified_count": len(unverified),
        "vault_errors": list(chain["errors"]),
        "analysis": analysis_summary,
        "pdf_engine": pdf_engine,
        "pdf_error": pdf_error,
    }
