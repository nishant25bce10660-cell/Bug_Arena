# BugArena MCP v2 Requirements Traceability Matrix

| ID | Requirement | Design Component | Code Location | Tests | Proof Command & Observed Output |
| :--- | :--- | :--- | :--- | :--- | :--- |
| R1 | Access a specific site and find its bugs | Browser CDP + Inspect Collectors + Site Audit Loop | `src/bugarena/browser/`, `src/bugarena/inspect/`, `src/bugarena/server.py` | PENDING | PENDING |
| R2 | Produce proper Markdown and PDF report (`REPORT.md`, `REPORT.pdf`) | Report Builder + Chromium `Page.printToPDF` | `src/bugarena/reporting/` | PENDING | PENDING |
| R3 | Use Chrome, Brave, Helium to access console & requested inspect sections | Browser discovery, `[mcp_<browser>]` CDP cursors, `inspect_panel` | `src/bugarena/browser/`, `src/bugarena/inspect/` | PENDING | PENDING |
| R4 | Also work on the user's own project to find bugs | `project_audit_start` + existing `LoopOperator` + source-map linking | `src/bugarena/audit/`, `src/bugarena/linking/` | PENDING | PENDING |
| R5 | Use Gemini and Grok APIs for report analysis | Multi-vendor Gemini + xAI Grok writer/critic analysis | `src/bugarena/tournament/providers/dispatcher.py` | PENDING | PENDING |
| R6 | `merge_both_skills`: compatibility test -> merge -> combined MCP | Quarantine intake, AST security scan, compat matrix, smoke test, adapter | `src/bugarena/skills_merge/` | PENDING | PENDING |
| R7 | In the merge, BugArena stays the main MCP | BugArena primary registry wins collisions; skill tools namespaced `<skill>__<tool>` | `src/bugarena/skills_merge/` | PENDING | PENDING |
| R8 | Subagentic capabilities like ECC | Extended roster (site analysts, `verifier`, `honesty-auditor`, `report-writer`, `merge-analyst`) | `src/bugarena/agents/` | PENDING | PENDING |
| R9 | Generate verification pack + `VERIFY_PROMPT.md` for any other agent | Offline `verify.py` + `claims.json` + `VERIFY_PROMPT.md` + cold subagent check | `src/bugarena/verify/` | PENDING | PENDING |
| R10 | Truth mechanism + calibration scoreboard improving accuracy over time | `EvidenceVault` hash chain, `CitationChecker`, `CorrectionLog`, `AgentScoreboard`, `LESSONS.md` | `src/bugarena/truth/` | PENDING | PENDING |
| R11 | Run site bug finding in `full_access` mode across multiple browsers | `session_confirm` authorization gate -> parallel multi-browser CDP audit | `src/bugarena/browser/`, `src/bugarena/audit/` | PENDING | PENDING |
| R12 | Access complete inspect menu with explicit coverage matrix | 14 CDP collector modules + `coverage_matrix.md` | `src/bugarena/inspect/` | PENDING | PENDING |
| R13 | Report organized by location, repro, fix, proof (images, code, hashes) | Section 1 folder + per-finding folders (`finding.json`, `repro.md`, `repro_script`, `fix.md`, annotated screenshots) | `src/bugarena/reporting/` | PENDING | PENDING |
| R14 | Multiple cursors `[mcp_<browser>]` isolated from user machine | Isolated temp `--user-data-dir`, loopback port, capability token, CDP-only input | `src/bugarena/browser/` | PENDING | PENDING |
| R15 | MCP uses all its tools by default unless restricted by user | `tools_allowed` / `tools_denied` in `session_confirm` defaulting to all registered tools | `src/bugarena/browser/questionnaire.py`, `src/bugarena/server.py` | PENDING | PENDING |
| R16 | Ask questions before starting including browser access grant | `session_prepare` batch questionnaire + `session_confirm` gate | `src/bugarena/browser/questionnaire.py` | PENDING | PENDING |
| R17 | User types or pastes the site link after calling the MCP | `session_prepare` -> `session_confirm` accepts target URL before launching browsers | `src/bugarena/browser/questionnaire.py` | PENDING | PENDING |
| R18 | Owner-ready findings with responsible disclosure & redacted secrets | Scope statement, concrete fixes/diffs, MDN/OWASP/WCAG refs, `redactions.json` | `src/bugarena/reporting/`, `src/bugarena/truth/` | PENDING | PENDING |
| R19 | Looping prompt executes all phases cleanly to stop conditions | `.bugarena/loop_state.json`, status blocks, anti-stall & 8-round cap | `src/bugarena/audit/loop.py` | PENDING | PENDING |
| R20 | Analyse current project state from `PROJECT_REPORT.md` first (Phase 0) | Phase 0 verification of 8 red flags & tooling inventory | `docs/STATE_VERIFICATION.md`, `docs/TOOLING_AVAILABLE.md` | `tests/unit/test_phase0_fixes.py` | `pytest -q -m "not slow and not browser"` (`114 passed` at `7e95e91`) |
| R21 | Use ECC, superpowers, ponytail, context-mode appropriately | Logged usage of skills/tools per phase | `docs/TOOLING_AVAILABLE.md`, `PROJECT_REPORT.md` | `tests/unit/test_phase0_fixes.py` | `docs/TOOLING_AVAILABLE.md` verified at `7e95e91` |
