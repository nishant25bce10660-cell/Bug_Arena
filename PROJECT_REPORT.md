# BugArena MCP — Project & Audit Report

- **Generated (UTC):** `2026-11-26T14:12:57+00:00`
- **Repository:** `MCP server`
- **Branch / HEAD:** `upgrade/bugarena-agents` @ `9ee6cc8`
- **Tracked Files:** `186` across `23` audited areas
- **Auto-Update Trigger:** `.githooks/pre-commit` + `scripts/update_project_report.py` + `AGENTS.md`

## Audit Verdict
- **Overall Status:** **PASS — Clean Audit & Verification**
- **Audit Engine Summary:** `ROUND 1 | new: 0 | confirmed: 0 | dismissed: 0 | fixed: 0 | open: 0`
- **Module Coverage:** `100.0%` (`100.0%` statically read)
- **Open Confirmed Bugs:** `0` | **Dismissed:** `0` | **Unverified:** `0`
- **Historical Ledger & Fix History:** `75` reconciled fixes (`43` `fix(...)` commits in git history; `2` prior dismissed)

## Verification Status
| Check | Result | Details |
| :--- | :--- | :--- |
| `ruff check src tests scripts` | **PASS (0 issues)** | `All checks passed!` |
| `pytest -q -m "not slow and not browser"` | **PASS (157 passed, 6 deselected in 43.90s)** | `Isolated unit + regression suites` |
| `LoopOperator` Read-Only Audit | **PASS** | `23 areas, 0 open confirmed` |

## MCP Tools
Total registered tools: **26**

| Tool | Description |
| :--- | :--- |
| `bug_detect` | Analyze an error log or traceback, map AST scopes, and locate suspect bug positions. |
| `bug_reproduce` | Synthesize a minimal pytest reproduction test and verify Red-baseline failure in an isolated sandbox. |
| `agent_fix_tournament` | Register, validate, or generate competing candidate patches across bug-fixing personas. |
| `evaluate_patches` | Evaluate tournament candidate patches in isolated sandboxes for Red-to-Green, regressions, AST syntax, and CC delta. |
| `generate_fix_report` | Generate a tournament diagnostic report in markdown, json, or diff format and optionally save it inside repo_path. |
| `generate_bug_report` | Generate and save a standalone Markdown diagnostic report covering suspects, traces, and reproduction status. |
| `bugarena_autonomous_repair` | Run the end-to-end autonomous repair lifecycle: detect, reproduce, tournament, evaluate, and report. |
| `audit_start` | Initialize a multi-agent read-only or fix audit run and return its run_id. |
| `audit_round` | Execute one multi-agent sweep, independent verification, dedupe, and coverage round. |
| `audit_status` | Return ledger counts, coverage percentage, and stop-condition state for an audit run. |
| `finding_verify` | Force independent second-agent dynamic re-verification of one ledger finding. |
| `audit_report` | Generate an evidence-graded audit report; output_file is confined by validate_safe_path. |
| `fix_loop_start` | Execute test-first fix evaluation over confirmed ledger findings (LLM generation gated by auto_generate). |
| `session_prepare` | Detect installed Chrome/Brave/Helium browsers, check API key presence, and return the 13-question pre-start gate without launching any browser. |
| `session_confirm` | Validate questionnaire answers, enforce passive mode when unauthorized, write scope_and_authorization.md, and issue a session token. |
| `site_audit_start` | Start a multi-browser site audit run for a confirmed session_token and run the initial DevTools sweep. |
| `site_audit_round` | Execute another multi-browser DevTools inspection, verification, and honesty-audit round for an active site_audit run_id. |
| `site_audit_status` | Return confirmed/retracted/rejected claim counts, vault integrity, and details for a site_audit run_id. |
| `browser_cursor_list` | List live or registered [mcp_<browser>] cursor workers, PIDs, ports, and states for a run_id. |
| `inspect_panel` | Run targeted DevTools panel inspection (Elements, Console, Network, Application, Performance/Sensors) on one granted browser. |
| `project_audit_start` | Run a read-only project audit and optionally link site stack frames to local source files via source maps. |
| `report_build` | Build Section 1 & 12 REPORT.md, Chromium REPORT.pdf, report.json, per-finding folders, and unverified_leads.md from CONFIRMED claims only. |
| `verify_pack_build` | Build standalone verification pack (verify/verify.py stdlib-only, VERIFY_PROMPT.md, claims.json, README.txt) for an audit run folder. |
| `claim_retract` | Retract a claim from an audit run; entries are preserved permanently in agents/corrections_log.md and raise self-correction honesty score. |
| `agent_scoreboard` | Return agent honesty, precision, Brier calibration, self-correction rate, and quarantine status for a run or cumulative scoreboard. |
| `merge_both_skills` | Quarantine, security-scan, compatibility-test, and merge an external bug-detecting skill while keeping BugArena as immutable primary MCP. |

## Coverage Matrix
| Area | Files | Static Read | Dynamic / Tested | Findings |
| :--- | :---: | :---: | :---: | :--- |
| `agents` | 30 | YES | YES | - |
| `audit` | 12 | YES | YES | - |
| `browser` | 5 | YES | YES | - |
| `config` | 1 | YES | YES | - |
| `discovery` | 4 | YES | YES | - |
| `docs` | 17 | YES | YES | - |
| `evaluation` | 4 | YES | YES | - |
| `inspect` | 5 | YES | YES | - |
| `linking` | 2 | YES | YES | - |
| `models` | 6 | YES | YES | - |
| `packaging` | 4 | YES | YES | - |
| `personas` | 2 | YES | YES | - |
| `providers` | 3 | YES | YES | - |
| `reporting` | 3 | YES | YES | - |
| `sandbox` | 4 | YES | YES | - |
| `scripts` | 3 | YES | YES | - |
| `server` | 1 | YES | YES | - |
| `skills_merge` | 2 | YES | YES | - |
| `synthesizer` | 3 | YES | YES | - |
| `tests` | 65 | YES | YES | - |
| `tournament` | 3 | YES | YES | - |
| `truth` | 5 | YES | YES | - |
| `verify` | 2 | YES | YES | - |

## Active Audit Findings
No open audit findings detected in the current codebase.

## Recent Changes
- `9ee6cc8 fix(hardening): close fail-open ACLs, SSRF origin check, robots pre-nav, and error surfacing`
- `e8391a0 fix(hardening): tighten truth scoreboard, inspect lifecycle, sourcemap linking, verifier, and skill merge`
- `809c356 fix(hardening): enforce v2 session ACLs, AccessPolicy bounds, and CDP/cursor cleanup`
- `f858b11 chore(phase11): update coverage mapping, gitignore, and v2 tool docs`
- `f1eabe9 feat(v2): add quarantined merge_both_skills pipeline and wire all 26 MCP tools`
- `4066f1c feat(reporting,verify): add v2 REPORT.md/Chromium PDF bundle, finding folders, and stdlib offline verify pack`
- `897c0be feat(v2): add site analyst roster, SiteAuditCoordinator, VLQ sourcemap linker, and Grok/Gemini cross-vendor analysis`
- `a4ef4b1 feat(inspect): add 14 DevTools CDP collectors, coverage_matrix.md, and planted-bug fixture site`
- `c3a81bd feat(browser): add Chromium discovery, RFC 6455 CDP client, isolated [mcp_<browser>] cursors, and access gate`
- `977b8f2 feat(truth): add EvidenceVault hash chain, ClaimLedger, CitationChecker, Scoreboard, and TranscriptLogger`
- `3f51417 docs(phase1): add v2 PLAN, ARCHITECTURE, THREAT_MODEL, REQUIREMENTS_TRACE, and DEVIATIONS`
- `7e95e91 fix(phase0): reconcile state, enforce real coverage, add tool descriptions & pytest markers`

## Working Tree Snapshot (`git status --short`)
```text
M  docs/REQUIREMENTS_TRACE.md
```

## How This Report Stays Updated
Run anytime after editing files (runs automatically on `git commit` when `.githooks` is active):
```bash
python scripts/update_project_report.py
```
