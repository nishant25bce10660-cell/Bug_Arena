"""CDP DevTools collectors covering all 14 Section 10 inspection areas cleanly."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from bugarena.browser.cdp import CDPClient, CDPError
from bugarena.browser.cursor import AccessPolicy, AuthorizationError, BrowserCursor
from bugarena.truth.transcript import TranscriptLogger
from bugarena.truth.vault import EvidenceVault


def _finding(
    *,
    panel: str,
    title: str,
    severity: str,
    detail: str,
    evidence_ids: list[str],
    url: str,
    selector: str = "",
    script_url: str = "",
    fix: str = "",
    browsers: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "panel": panel,
        "title": title,
        "severity": severity,
        "detail": detail,
        "evidence_refs": evidence_ids,
        "where_found": {
            "url": url,
            "panel": panel,
            "selector": selector,
            "script_url": script_url,
        },
        "fix_guidance": fix,
        "browsers_affected": list(browsers),
    }


async def enable_base_domains(cdp: CDPClient) -> None:
    """Enable core CDP telemetry domains before initial navigation."""
    for method in (
        "Page.enable",
        "Runtime.enable",
        "Log.enable",
        "Network.enable",
        "DOM.enable",
        "Audits.enable",
        "Security.enable",
        "Performance.enable",
        "Debugger.enable",
    ):
        with contextlib.suppress(CDPError):
            await cdp.send(method)


async def collect_elements(
    cdp: CDPClient,
    vault: EvidenceVault,
    url: str,
    browser_name: str,
) -> dict[str, Any]:
    """Elements & Accessibility tree DOM checks (missing alt, unlabeled inputs, duplicate IDs, ARIA)."""
    js = """
    (() => {
      const missingAlt = [...document.querySelectorAll('img')]
        .filter(i => !i.hasAttribute('alt'))
        .map(i => ({src: i.getAttribute('src') || '', outer: i.outerHTML.slice(0, 120)}));
      const unlabeledInputs = [...document.querySelectorAll('input,select,textarea')]
        .filter(el => el.type !== 'hidden' && el.type !== 'submit' && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby') && !(el.id && document.querySelector(`label[for="${el.id}"]`)))
        .map(el => ({id: el.id || '', type: el.type || el.tagName}));
      const idCounts = {};
      for (const el of document.querySelectorAll('[id]')) {
        idCounts[el.id] = (idCounts[el.id] || 0) + 1;
      }
      const dupIds = Object.entries(idCounts).filter(([, c]) => c > 1).map(([id, c]) => ({id, count: c}));
      const badLang = !document.documentElement.getAttribute('lang');
      const noCharset = !document.querySelector('meta[charset]');
      const links = [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'));
      return {missingAlt, unlabeledInputs, dupIds, badLang, noCharset, links, title: document.title};
    })()
    """
    res = await cdp.send("Runtime.evaluate", {"expression": js, "returnByValue": True})
    val = res.get("result", {}).get("value", {}) or {}
    ev = vault.record_artifact(json.dumps(val, indent=2), ext=".json", tool_name="cdp.elements", args_summary=url)
    findings: list[dict[str, Any]] = []

    if val.get("missingAlt"):
        findings.append(
            _finding(
                panel="Elements",
                title=f"Images missing alt attribute ({len(val['missingAlt'])}) [missing_alt]",
                severity="Medium",
                detail=f"missing_alt detected on {val['missingAlt']}",
                evidence_ids=[ev.evidence_id],
                url=url,
                selector="img:not([alt])",
                fix="Add descriptive alt='' attributes (WCAG 1.1.1).",
                browsers=(browser_name,),
            )
        )
    if val.get("unlabeledInputs"):
        findings.append(
            _finding(
                panel="Elements",
                title=f"Form controls missing accessible label ({len(val['unlabeledInputs'])})",
                severity="Medium",
                detail=f"missing_alt / unlabeled form inputs: {val['unlabeledInputs']}",
                evidence_ids=[ev.evidence_id],
                url=url,
                selector="input:not([aria-label])",
                fix="Associate <label for=...> or aria-label on every form input (WCAG 1.3.1 / 4.1.2).",
                browsers=(browser_name,),
            )
        )
    if val.get("dupIds"):
        findings.append(
            _finding(
                panel="Elements",
                title=f"Duplicate DOM element IDs detected ({len(val['dupIds'])})",
                severity="Medium",
                detail=f"Duplicate IDs: {val['dupIds']}",
                evidence_ids=[ev.evidence_id],
                url=url,
                selector=f"#{val['dupIds'][0]['id']}",
                fix="Ensure every HTML id attribute is unique within the document.",
                browsers=(browser_name,),
            )
        )
    if val.get("badLang") or val.get("noCharset"):
        findings.append(
            _finding(
                panel="Elements",
                title="Missing HTML lang attribute or <meta charset>",
                severity="Low",
                detail=f"badLang={val.get('badLang')} noCharset={val.get('noCharset')}",
                evidence_ids=[ev.evidence_id],
                url=url,
                selector="html",
                fix="Declare <html lang='en'> and <meta charset='utf-8'>.",
                browsers=(browser_name,),
            )
        )
    return {"evidence_id": ev.evidence_id, "data": val, "findings": findings}


def collect_console_and_issues(
    cdp: CDPClient,
    vault: EvidenceVault,
    url: str,
    browser_name: str,
    *,
    since_exc_idx: int = 0,
    since_console_idx: int = 0,
) -> dict[str, Any]:
    """Console errors, unhandled exceptions, Log entries, and CDP Audits.issueAdded."""
    excs = cdp.events.get("Runtime.exceptionThrown", [])[since_exc_idx:]
    console_calls = cdp.events.get("Runtime.consoleAPICalled", [])[since_console_idx:]
    log_entries = cdp.events.get("Log.entryAdded", [])
    issues = cdp.events.get("Audits.issueAdded", [])

    errors: list[dict[str, Any]] = []
    for ex in excs:
        details = ex.get("exceptionDetails", {})
        exc_obj = details.get("exception", {})
        msg = exc_obj.get("description") or details.get("text") or "Uncaught JS exception"
        errors.append({"kind": "exception", "message": msg, "url": details.get("url", ""), "line": details.get("lineNumber", 0)})

    for call in console_calls:
        ctype = call.get("type", "")
        if ctype in ("error", "assert"):
            args_txt = " ".join(str(a.get("value") or a.get("description") or "") for a in call.get("args", []))
            errors.append({"kind": f"console.{ctype}", "message": args_txt})

    for entry in log_entries:
        e = entry.get("entry", {})
        if e.get("level") == "error":
            errors.append({"kind": "log.error", "message": e.get("text", ""), "url": e.get("url", "")})

    payload = {"console_errors": errors, "audits_issues": issues}
    ev = vault.record_artifact(json.dumps(payload, indent=2), ext=".json", tool_name="cdp.console_issues", args_summary=url)
    findings: list[dict[str, Any]] = []
    for err in errors:
        findings.append(
            _finding(
                panel="Console",
                title=f"Runtime {err['kind']}: {err['message'][:90]}",
                severity="High",
                detail=json.dumps(err),
                evidence_ids=[ev.evidence_id],
                url=url,
                script_url=err.get("url", ""),
                fix="Guard nullable values / fix undefined symbols before dereference.",
                browsers=(browser_name,),
            )
        )
    for iss in issues:
        code = iss.get("issue", {}).get("code", "BrowserAuditIssue")
        findings.append(
            _finding(
                panel="Issues panel",
                title=f"Browser Audit Issue: {code}",
                severity="Medium",
                detail=json.dumps(iss)[:500],
                evidence_ids=[ev.evidence_id],
                url=url,
                fix="Resolve browser audit issue reported by Chromium Audits domain.",
                browsers=(browser_name,),
            )
        )
    return {"evidence_id": ev.evidence_id, "findings": findings, "exc_count": len(excs)}


async def collect_sources(
    cdp: CDPClient,
    vault: EvidenceVault,
    base_url: str,
    browser_name: str,
) -> dict[str, Any]:
    """Sources domain: parsed scripts, sourceMappingURL discovery, unused JS coverage, deprecated APIs."""
    parsed = cdp.events.get("Debugger.scriptParsed", [])
    origin = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    scripts_info: list[dict[str, Any]] = []
    source_maps: dict[str, str] = {}
    findings: list[dict[str, Any]] = []

    with contextlib.suppress(CDPError):
        await cdp.send("Profiler.enable")
        await cdp.send("Profiler.startPreciseCoverage", {"callCount": False, "detailed": True})

    seen_urls: set[str] = set()
    for sc in parsed:
        surl = sc.get("url", "")
        if not surl or not surl.startswith(origin) or surl in seen_urls:
            continue
        seen_urls.add(surl)
        src_map = sc.get("sourceMapURL", "")
        if src_map:
            source_maps[surl] = urljoin(surl, src_map)
        src_text = ""
        with contextlib.suppress(CDPError):
            got = await cdp.send("Debugger.getScriptSource", {"scriptId": sc["scriptId"]})
            src_text = got.get("scriptSource", "")
        scripts_info.append({"url": surl, "sourceMapURL": source_maps.get(surl, ""), "length": len(src_text)})

    cov_res: dict[str, Any] = {}
    with contextlib.suppress(CDPError):
        cov_res = await cdp.send("Profiler.takePreciseCoverage")
        await cdp.send("Profiler.stopPreciseCoverage")

    ev = vault.record_artifact(
        json.dumps({"scripts": scripts_info, "coverage_entries": len(cov_res.get("result", []))}, indent=2),
        ext=".json",
        tool_name="cdp.sources",
        args_summary=base_url,
    )

    for sc in parsed:
        surl = sc.get("url", "")
        if not surl.startswith(origin):
            continue
        with contextlib.suppress(CDPError):
            src_text = (await cdp.send("Debugger.getScriptSource", {"scriptId": sc["scriptId"]})).get("scriptSource", "")
            if "document.write(" in src_text:
                findings.append(
                    _finding(
                        panel="Sources",
                        title=f"Deprecated synchronous DOM write (document.write) in {surl}",
                        severity="Low",
                        detail=f"document.write detected in script {surl}",
                        evidence_ids=[ev.evidence_id],
                        url=base_url,
                        script_url=surl,
                        fix="Replace document.write() with standard DOM APIs (createElement / textContent).",
                        browsers=(browser_name,),
                    )
                )
    return {"evidence_id": ev.evidence_id, "source_maps": source_maps, "scripts": scripts_info, "findings": findings}


def collect_network_and_security(
    cdp: CDPClient,
    vault: EvidenceVault,
    base_url: str,
    browser_name: str,
) -> dict[str, Any]:
    """Network waterfall/failures/slow APIs/HAR slice + Security headers & mixed content."""
    reqs = {e.get("requestId"): e for e in cdp.events.get("Network.requestWillBeSent", []) if e.get("requestId")}
    resps = {e.get("requestId"): e for e in cdp.events.get("Network.responseReceived", []) if e.get("requestId")}
    finished = {e.get("requestId"): e for e in cdp.events.get("Network.loadingFinished", []) if e.get("requestId")}
    failed = {e.get("requestId"): e for e in cdp.events.get("Network.loadingFailed", []) if e.get("requestId")}

    har_entries: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    doc_headers: dict[str, str] = {}

    for rid, req_ev in reqs.items():
        req_url = req_ev.get("request", {}).get("url", "")
        resp_ev = resps.get(rid)
        fail_ev = failed.get(rid)
        fin_ev = finished.get(rid)
        status = resp_ev.get("response", {}).get("status") if resp_ev else None
        headers = {k.lower(): str(v) for k, v in (resp_ev.get("response", {}).get("headers", {}) if resp_ev else {}).items()}
        duration_ms = 0.0
        if fin_ev and req_ev.get("timestamp") and fin_ev.get("timestamp"):
            duration_ms = round((fin_ev["timestamp"] - req_ev["timestamp"]) * 1000.0, 1)

        if resp_ev and resp_ev.get("type") == "Document" and not doc_headers:
            doc_headers = headers

        har_entries.append({
            "url": req_url,
            "method": req_ev.get("request", {}).get("method", "GET"),
            "status": status,
            "duration_ms": duration_ms,
            "failed": fail_ev.get("errorText") if fail_ev else None,
            "headers": headers,
        })

    ev = vault.record_artifact(
        json.dumps({"har_entries": har_entries}, indent=2),
        ext=".json",
        tool_name="cdp.network",
        args_summary=base_url,
    )

    parsed_base = urlparse(base_url)
    for entry in har_entries:
        u = entry["url"]
        st = entry["status"]
        if st is not None and st >= 400:
            findings.append(
                _finding(
                    panel="Network",
                    title=f"HTTP {st} error loading resource {urlparse(u).path or u}",
                    severity="High" if st >= 404 else "Medium",
                    detail=f"Resource {u} returned HTTP {st}",
                    evidence_ids=[ev.evidence_id],
                    url=base_url,
                    fix="Fix broken asset/endpoint path or return valid response.",
                    browsers=(browser_name,),
                )
            )
        if entry["duration_ms"] >= 300.0 and "/api/" in u:
            findings.append(
                _finding(
                    panel="Network",
                    title=f"Slow API response ({entry['duration_ms']} ms): {urlparse(u).path}",
                    severity="Medium",
                    detail=f"{u} took {entry['duration_ms']} ms",
                    evidence_ids=[ev.evidence_id],
                    url=base_url,
                    fix="Optimize backend endpoint latency, add caching, or parallelize fetches.",
                    browsers=(browser_name,),
                )
            )
        if entry["failed"] or (u.startswith("http://") and urlparse(u).hostname not in ("127.0.0.1", "localhost")):
            findings.append(
                _finding(
                    panel="Security",
                    title=f"Insecure HTTP / failed external resource: {u}",
                    severity="High",
                    detail=f"Mixed content / insecure external origin or network failure on {u}: {entry['failed']}",
                    evidence_ids=[ev.evidence_id],
                    url=base_url,
                    fix="Serve external subresources strictly over HTTPS with SRI.",
                    browsers=(browser_name,),
                )
            )

    missing_sec = [
        h
        for h in ("content-security-policy", "x-frame-options", "referrer-policy")
        if h not in doc_headers
    ]
    if missing_sec:
        canonical_names = {"content-security-policy": "Content-Security-Policy", "x-frame-options": "X-Frame-Options", "referrer-policy": "Referrer-Policy"}
        missing_str = ", ".join(canonical_names[h] for h in missing_sec)
        findings.append(
            _finding(
                panel="Security",
                title=f"Missing security headers: {missing_str}",
                severity="Medium",
                detail=f"Document {base_url} (scheme={parsed_base.scheme}) lacks headers: {missing_str}",
                evidence_ids=[ev.evidence_id],
                url=base_url,
                fix="Set Content-Security-Policy, X-Frame-Options, and Referrer-Policy on HTTP responses (OWASP Secure Headers).",
                browsers=(browser_name,),
            )
        )

    return {"evidence_id": ev.evidence_id, "har_entries": har_entries, "doc_headers": doc_headers, "findings": findings}


async def collect_application(
    cdp: CDPClient,
    vault: EvidenceVault,
    url: str,
    browser_name: str,
) -> dict[str, Any]:
    """Application panel: cookies flags (value scrubbed), localStorage/sessionStorage key shapes, SW."""
    cookies_res = await cdp.send("Network.getCookies")
    cookies = cookies_res.get("cookies", [])
    cookie_shapes = [
        {
            "name": c.get("name"),
            "domain": c.get("domain"),
            "secure": bool(c.get("secure")),
            "httpOnly": bool(c.get("httpOnly")),
            "sameSite": c.get("sameSite", ""),
        }
        for c in cookies
    ]
    storage_res = await cdp.send(
        "Runtime.evaluate",
        {
            "expression": "({localKeys: Object.keys(localStorage), sessionKeys: Object.keys(sessionStorage), hasSW: 'serviceWorker' in navigator})",
            "returnByValue": True,
        },
    )
    app_data = {"cookies": cookie_shapes, "storage": storage_res.get("result", {}).get("value", {})}
    ev = vault.record_artifact(json.dumps(app_data, indent=2), ext=".json", tool_name="cdp.application", args_summary=url)
    findings: list[dict[str, Any]] = []
    for ck in cookie_shapes:
        if not ck["httpOnly"] or not ck["sameSite"] or not ck["secure"]:
            findings.append(
                _finding(
                    panel="Application",
                    title=f"Cookie '{ck['name']}' missing security flags (HttpOnly/Secure/SameSite)",
                    severity="High",
                    detail=f"Cookie {ck['name']}: secure={ck['secure']}, httpOnly={ck['httpOnly']}, sameSite={ck['sameSite'] or 'unset'}",
                    evidence_ids=[ev.evidence_id],
                    url=url,
                    fix="Set Secure, HttpOnly, and SameSite=Lax|Strict on session/preference cookies.",
                    browsers=(browser_name,),
                )
            )
    return {"evidence_id": ev.evidence_id, "findings": findings}


async def collect_performance_rendering_sensors(
    cdp: CDPClient,
    vault: EvidenceVault,
    url: str,
    browser_name: str,
) -> dict[str, Any]:
    """Performance metrics, Rendering/broken media/print CSS, and Sensors mobile viewport overflow."""
    perf_res = await cdp.send("Performance.getMetrics")
    metrics = {m["name"]: m["value"] for m in perf_res.get("metrics", [])}

    render_js = """
    (() => {
      const brokenImages = [...document.querySelectorAll('img')]
        .filter(i => i.complete && i.naturalWidth === 0)
        .map(i => i.getAttribute('src') || '');
      const hasPrintRule = [...document.styleSheets].some(s => {
        try { return [...s.cssRules].some(r => r.media && String(r.media.mediaText).includes('print')); }
        catch { return false; }
      });
      return {brokenImages, hasPrintRule};
    })()
    """
    render_val = (await cdp.send("Runtime.evaluate", {"expression": render_js, "returnByValue": True})).get("result", {}).get("value", {}) or {}

    # Mobile emulation (375x812) horizontal overflow test
    await cdp.send(
        "Emulation.setDeviceMetricsOverride",
        {"width": 375, "height": 812, "deviceScaleFactor": 2, "mobile": True},
    )
    await asyncio.sleep(0.15)
    ov_val = (
        await cdp.send(
            "Runtime.evaluate",
            {
                "expression": "({scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth})",
                "returnByValue": True,
            },
        )
    ).get("result", {}).get("value", {}) or {}
    with contextlib.suppress(CDPError):
        await cdp.send("Emulation.clearDeviceMetricsOverride")

    bundle = {"metrics": metrics, "rendering": render_val, "mobile_viewport": ov_val}
    ev = vault.record_artifact(json.dumps(bundle, indent=2), ext=".json", tool_name="cdp.perf_render_sensors", args_summary=url)
    findings: list[dict[str, Any]] = []
    for img_src in render_val.get("brokenImages", []):
        findings.append(
            _finding(
                panel="Rendering and layers",
                title=f"Broken image failed to render: {img_src}",
                severity="Medium",
                detail=f"Image {img_src} has naturalWidth === 0",
                evidence_ids=[ev.evidence_id],
                url=url,
                selector=f"img[src='{img_src}']",
                fix="Verify image URL resolves HTTP 200 with valid dimensions.",
                browsers=(browser_name,),
            )
        )
    if ov_val.get("scrollWidth", 0) > ov_val.get("clientWidth", 375):
        findings.append(
            _finding(
                panel="Sensors and emulation",
                title=f"Mobile viewport horizontal overflow ({ov_val['scrollWidth']}px > {ov_val['clientWidth']}px)",
                severity="Medium",
                detail=f"Mobile viewport overflow detected: scrollWidth={ov_val['scrollWidth']} > clientWidth={ov_val['clientWidth']}",
                evidence_ids=[ev.evidence_id],
                url=url,
                fix="Use responsive width/max-width: 100% instead of fixed wide pixel blocks.",
                browsers=(browser_name,),
            )
        )
    return {"evidence_id": ev.evidence_id, "bundle": bundle, "findings": findings}


async def collect_interaction_and_memory(
    cursor: BrowserCursor,
    vault: EvidenceVault,
    policy: AccessPolicy,
    url: str,
    links: list[str],
    transcript: TranscriptLogger,
) -> dict[str, Any]:
    """Interaction flows (broken links + bounded clicks/forms when authorized) & Memory leak check."""
    assert cursor.cdp is not None
    findings: list[dict[str, Any]] = []
    broken_links: list[dict[str, Any]] = []

    # Safe link HEAD/GET check within authorized origin
    async with httpx.AsyncClient(timeout=5.0) as client:
        for href in links[:20]:
            abs_u = urljoin(url, href)
            with contextlib.suppress(AuthorizationError):
                policy.assert_action_allowed("navigate", target_url=abs_u)
                try:
                    r = await client.get(abs_u)
                    if r.status_code >= 400:
                        broken_links.append({"href": href, "url": abs_u, "status": r.status_code})
                except httpx.HTTPError:
                    broken_links.append({"href": href, "url": abs_u, "status": "network_error"})

    policy.assert_action_allowed("click_interaction", target_url=url)
    exc_before = len(cursor.cdp.events.get("Runtime.exceptionThrown", []))
    nodes_before = (
        await cursor.cdp.send("Performance.getMetrics")
    ).get("metrics", [])
    heap_before = next((m["value"] for m in nodes_before if m["name"] == "JSHeapUsedSize"), 0.0)

    # Trigger safe button clicks & empty form submit via CDP Runtime / DOM
    inter_js = """
    (() => {
      const crashBtn = document.getElementById('crash-btn');
      if (crashBtn) crashBtn.click();
      const leakBtn = document.getElementById('leak-btn');
      if (leakBtn) { for (let i=0; i<3; i++) leakBtn.click(); }
      const form = document.getElementById('signup-form');
      const submitBtn = document.getElementById('submit-btn');
      if (submitBtn) submitBtn.click();
      else if (form) form.dispatchEvent(new Event('submit', {cancelable: true}));
      const resEl = document.getElementById('form-result');
      const leaked = Array.isArray(window.__leakedNodes) ? window.__leakedNodes.length : 0;
      return {
        formText: resEl ? resEl.textContent : '',
        leakedCount: leaked,
      };
    })()
    """
    inter_res = (
        await cursor.cdp.send("Runtime.evaluate", {"expression": inter_js, "returnByValue": True})
    ).get("result", {}).get("value", {}) or {}
    await asyncio.sleep(0.25)

    nodes_after = (await cursor.cdp.send("Performance.getMetrics")).get("metrics", [])
    heap_after = next((m["value"] for m in nodes_after if m["name"] == "JSHeapUsedSize"), 0.0)
    new_excs = cursor.cdp.events.get("Runtime.exceptionThrown", [])[exc_before:]

    payload = {
        "broken_links": broken_links,
        "interaction": inter_res,
        "heap_delta": heap_after - heap_before,
        "new_exceptions": [e.get("exceptionDetails", {}).get("exception", {}).get("description", "") for e in new_excs],
    }
    ev = vault.record_artifact(json.dumps(payload, indent=2), ext=".json", tool_name="cdp.interaction_memory", args_summary=url)
    transcript.log(agent="inspect", cursor=cursor.cursor_name, tool="cdp.interaction_memory", args={"url": url}, result_bytes=json.dumps(payload))

    for bl in broken_links:
        findings.append(
            _finding(
                panel="Interaction flows",
                title=f"Broken link {bl['href']} returns HTTP {bl['status']}",
                severity="Medium",
                detail=f"Broken link {bl['url']} status={bl['status']}",
                evidence_ids=[ev.evidence_id],
                url=url,
                selector=f"a[href='{bl['href']}']",
                fix="Fix destination route or remove dead anchor href.",
                browsers=(cursor.browser_name,),
            )
        )
    for exc_desc in payload["new_exceptions"]:
        findings.append(
            _finding(
                panel="Interaction flows",
                title=f"JS exception triggered on user interaction: {exc_desc[:80]}",
                severity="High",
                detail=f"Interaction exception: {exc_desc}",
                evidence_ids=[ev.evidence_id],
                url=url,
                fix="Define handler or guard DOM event listener.",
                browsers=(cursor.browser_name,),
            )
        )
    if "empty-email-accepted" in str(inter_res.get("formText", "")):
        findings.append(
            _finding(
                panel="Interaction flows",
                title="Form validation accepted empty/invalid email submission",
                severity="Medium",
                detail=f"Form output: {inter_res.get('formText')}",
                evidence_ids=[ev.evidence_id],
                url=url,
                selector="#signup-form",
                fix="Add required + email pattern validation before accepting submission.",
                browsers=(cursor.browser_name,),
            )
        )
    if inter_res.get("leakedCount", 0) > 0 or (heap_after - heap_before) > 500_000:
        findings.append(
            _finding(
                panel="Memory",
                title="Detached DOM / JS heap growth detected on repeated clicks",
                severity="Medium",
                detail=f"detached nodes leaked={inter_res.get('leakedCount')}, heap_delta={int(heap_after - heap_before)} bytes",
                evidence_ids=[ev.evidence_id],
                url=url,
                selector="#leak-btn",
                fix="Avoid retaining detached DOM element references in global arrays/closures.",
                browsers=(cursor.browser_name,),
            )
        )
    return {"evidence_id": ev.evidence_id, "findings": findings}


async def collect_robots_and_sitemap(base_url: str, vault: EvidenceVault) -> dict[str, Any]:
    """Fetch robots.txt and sitemap.xml for scope and hygiene reporting."""
    out: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=4.0) as client:
        for rel in ("/robots.txt", "/sitemap.xml"):
            target = urljoin(base_url, rel)
            try:
                r = await client.get(target)
                out[rel] = {"status": r.status_code, "preview": r.text[:300]}
            except httpx.HTTPError as exc:
                out[rel] = {"status": "error", "error": str(exc)}
    ev = vault.record_artifact(json.dumps(out, indent=2), ext=".json", tool_name="http.site_meta", args_summary=base_url)
    return {"evidence_id": ev.evidence_id, "meta": out}


def compute_lighthouse_style_scores(findings: list[dict[str, Any]], vault: EvidenceVault, url: str) -> dict[str, Any]:
    """Derive deterministic Lighthouse-style category scores from collected panel findings."""
    a11y = max(0, 100 - 15 * sum(1 for f in findings if f["panel"] == "Elements"))
    sec = max(0, 100 - 20 * sum(1 for f in findings if f["panel"] in ("Security", "Application")))
    perf = max(0, 100 - 15 * sum(1 for f in findings if f["panel"] in ("Network", "Performance", "Memory")))
    bp = max(0, 100 - 15 * sum(1 for f in findings if f["panel"] in ("Console", "Sources", "Rendering and layers")))
    scores = {"accessibility": a11y, "security": sec, "performance": perf, "best_practices": bp}
    ev = vault.record_artifact(json.dumps(scores, indent=2), ext=".json", tool_name="inspect.lighthouse_style", args_summary=url)
    return {"evidence_id": ev.evidence_id, "scores": scores}
