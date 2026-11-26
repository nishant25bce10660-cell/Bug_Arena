# BugArena MCP v2 Implementation Plan

> **For agentic workers:** Follow `superpowers:test-driven-development`, `superpowers:verification-before-completion`, and `ponytail` discipline (minimal complete implementations, zero duplicated logic, test-first, commit per phase/logical unit).

**Goal:** Extend BugArena MCP v1 into a multi-browser site + project auditing platform with truth-enforced subagents, CDP DevTools collection, Markdown + Chromium PDF reports, offline verification packs, Gemini/Grok cross-vendor analysis, and quarantined `merge_both_skills`.

**Architecture:** Build clean modular Python packages under `src/bugarena/` reusing existing `FindingLedger`, `CoverageMatrix`, `LoopOperator`, `MultiModelDispatcher`, and `sandbox.security` primitives. Browser control uses isolated Chromium processes on loopback ports with a stdlib RFC 6455 async WebSocket CDP client (zero OS input automation). Truth enforcement uses an append-only SHA-256 hash-chained `EvidenceVault` plus code-enforced citation checks, independent verification, and `agent_scores.json`.

**Tech Stack:** Python 3.11+ (`3.14` active), `mcp>=2.0.0`, `pydantic>=2.0.0`, `httpx>=0.27.0`, stdlib `asyncio`/`hashlib`/`struct`/`json`/`zipfile`/`venv`, local Chromium (`chrome.exe`/`brave.exe`) CDP + `Page.printToPDF`, `pytest` + `ruff`.

## Global Constraints
- Safety > Truth Protocol > Requirements > everything else.
- Default output root: `bugarena_reports/<run_id>/` matching Section 1 directory layout exactly.
- Authorization gate: `session_prepare` -> questionnaire -> `session_confirm` required before launching any browser; `neither` forces strict passive mode (`<= 2 req/s`, no form submissions, no fuzzing, robots.txt honored).
- No OS input calls anywhere (`pyautogui`, `pynput`, `ctypes` mouse/keyboard, `SendInput` banned by lint/test).
- Existing 114 unit/regression tests and `ruff check src tests scripts` must stay green after every logical commit.

## Review Focus
1. Cross-cursor isolation: `[mcp_chrome]` capability token cannot connect to `[mcp_brave]` port; user PIDs untouched before/after; temp profiles cleaned up even on crash.
2. Evidence vault tamper detection: agents cannot fabricate quotes, numbers, or evidence hashes; edited artifact breaks SHA-256 chain cleanly caught by `verify.py`.
3. Citation & lying-agent defense: fabricated screenshots, unprinted quotes, and STATIC-Critical severity inflation are rejected by code and penalized on `scoreboard.json`.
4. Untrusted third-party skill quarantine: `merge_both_skills` defaults `dry_run=True`, flags `eval`/`exec`/`subprocess`/outbound network before any execution, namespaces colliding tools while keeping BugArena primary, and rejects incompatible dependencies cleanly.
5. Passive authorization enforcement: active DOM interaction/fuzzing/form abuse raises `AuthorizationError` in passive mode (`authorization="neither"` or `access_level="passive"`).

---

## Phased Build Breakdown

- **Phase 2 (`src/bugarena/truth/`):** `EvidenceVault` (`manifest.jsonl` SHA-256 chain + `redactions.json` PII/token scrubbing), `ClaimLedger` (`evidence_refs` >= 1 required), `CitationChecker`, `CorrectionLog`, `AgentScoreboard` (`.bugarena/agent_scores.json` + Brier calibration), plus seeded lying-agent tests.
- **Phase 3 (`src/bugarena/browser/`):** Browser discovery (`chrome`, `brave`, `helium` via paths/registry/PATH), isolated temp-profile Chromium launcher (`127.0.0.1` ephemeral port), RFC 6455 async CDP client, `BrowserCursor` (`[mcp_<browser>]` capability token + PID snapshot + process-group cleanup), visual cursor overlay (headed mode only), `session_prepare` & `session_confirm` authorization gate, `browser_cursor_list`.
- **Phase 4 (`src/bugarena/inspect/`):** 14 CDP DevTools collectors (`elements`, `console`, `issues`, `sources`, `network`, `performance`, `memory`, `application`, `security`, `lighthouse_style`, `rendering`, `sensors`, `interaction`, `cross_browser`) + `robots.txt`/`sitemap.xml`/links/i18n/print helpers + `coverage_matrix.md` generator + `inspect_panel` MCP tool + fixture site `tests/fixtures/site_bugs/` with `fixture_truth.json`.
- **Phase 5 (`src/bugarena/agents/` & `src/bugarena/audit/`):** Add site analysts (`console-analyst`, `network-analyst`, `dom-a11y-analyst`, `storage-security-analyst`, `performance-memory-analyst`, `js-source-analyst`, `responsive-analyst`, `cross-browser-diff-analyst`), `report-writer`, `verifier`, `honesty-auditor`, `merge-analyst`, prompt files + schema validation, wire `site_audit_start`/`site_audit_round`/`site_audit_status` and `claim_retract`/`agent_scoreboard`.
- **Phase 6 (`src/bugarena/linking/`):** Source-map parser (VLQ/mappings resolver), production JS stack frame -> local project `file:line` linker, `site_only` / `project_only` / `linked` tagging, `project_audit_start` MCP tool.
- **Phase 7 (`src/bugarena/tournament/providers/`):** Add xAI Grok route (`XAI_API_KEY`, `https://api.x.ai/v1/chat/completions`) alongside Gemini (`GEMINI_API_KEY`), schema-validated JSON output, bounded retry/cost/token caps, cross-vendor writer/critic split (`analyze_with_writer_critic`).
- **Phase 8 (`src/bugarena/reporting/`):** v2 run folder builder (`report_build`), `REPORT.md`, Chromium `Page.printToPDF` `REPORT.pdf` (with embedded raw + annotated screenshots), `report.json`, per-finding `findings/F-XXXX/` folders (`finding.json`, `repro.md`, `repro_script.py`, `fix.md`, `evidence/`), `unverified_leads.md`, `coverage_matrix.md`, rubric-locked severity.
- **Phase 9 (`src/bugarena/verify/`):** `verify_pack_build` generating `verify/verify.py` (stdlib-only SHA-256 + hash-chain + schema + quote/count checker), `verify/claims.json`, `verify/README.txt`, `verify/VERIFY_PROMPT.md`; cold subagent execution test.
- **Phase 10 (`src/bugarena/skills_merge/`):** `merge_both_skills(skill_source, name=None, dry_run=True)` — quarantine fetch, ECC `security-reviewer` AST/pattern scan, permission manifest, dependency conflict dry-run, isolated smoke test, adapter registry preserving BugArena as primary (`origin: bugarena | <skill>`, namespaced collisions), `MERGE_REPORT.md`, rollback instructions, and 4 sample skill test scenarios.
- **Phase 11 (Hardening & Full Loop Convergence):** Security & silent-failure audit across all new v2 modules, OS-input ban check, fixture site multi-browser recall (`>=90%`, `0` decoys), cold `VERIFY_PROMPT.md` verification pass, full `pytest` + `ruff`, `REQUIREMENTS_TRACE.md` proof, and `PROJECT_REPORT.md` regeneration.
