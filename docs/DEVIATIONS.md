# Deviations Log (`docs/DEVIATIONS.md`)

1. **Helium Browser Not Auto-Detected on Host (Phase 0 / Section 9):**
   - **Observed:** Chrome (`C:\Program Files\Google\Chrome\Application\chrome.exe`) and Brave (`C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe`) are installed; Helium (`helium.exe`) is not present in standard paths or `PATH`.
   - **Adaptation:** Browser discovery checks Registry App Paths, standard install paths, and `PATH` for Chrome, Brave, and Helium, plus accepts explicit user-supplied executable paths in `session_prepare` / `session_confirm`. Browser integration tests auto-skip unavailable browsers cleanly (`@pytest.mark.browser`).
2. **Stdlib RFC 6455 CDP WebSocket & Native Chromium `Page.printToPDF` / Canvas Annotations (Phase 0 / Sections 9, 12):**
   - **Observed:** `.venv` does not include third-party `websockets`, `playwright`, `pillow`, or `weasyprint`.
   - **Adaptation:** Implemented a focused stdlib RFC 6455 async WebSocket client over `asyncio.open_connection` for CDP, Chromium `Page.printToPDF` for real PDF generation, and Chromium DOM/Canvas overlay capture via `Page.captureScreenshot` for annotated screenshots, avoiding unrequested runtime dependencies (per Ponytail and Section 14 hygiene).
3. **`XAI_API_KEY` Absent in Host `.env` (Phase 0 / Section 1, 7):**
   - **Observed:** Host `.env` contains `GEMINI_API_KEY` and `GROQ_API_KEY`, not `XAI_API_KEY`.
   - **Adaptation:** xAI Grok client (`https://api.x.ai/v1/chat/completions` via `XAI_API_KEY`, with fallback note) is fully implemented and covered via `httpx.MockTransport` tests; live multi-vendor checks degrade gracefully with a clear `KEY_NOT_FOUND` notice when `XAI_API_KEY` is unset.
