# BugArena MCP — Project & Audit Report

- **Generated (UTC):** `2026-11-26T11:38:11+00:00`
- **Repository:** `MCP server`
- **Branch / HEAD:** `upgrade/bugarena-agents` @ `a4ef4b1`
- **Tracked Files:** `175` across `21` audited areas
- **Auto-Update Trigger:** `.githooks/pre-commit` + `scripts/update_project_report.py` + `AGENTS.md`

## Audit Verdict
- **Overall Status:** **PASS — Clean Audit & Verification**
- **Audit Engine Summary:** `ROUND 1 | new: 0 | confirmed: 0 | dismissed: 0 | fixed: 0 | open: 0`
- **Module Coverage:** `100.0%` (`100.0%` statically read)
- **Open Confirmed Bugs:** `0` | **Dismissed:** `0` | **Unverified:** `0`
- **Historical Ledger & Fix History:** `75` reconciled fixes (`40` `fix(...)` commits in git history; `2` prior dismissed)

## Verification Status
| Check | Result | Details |
| :--- | :--- | :--- |
| `ruff check src tests scripts` | **PASS (0 issues)** | `All checks passed!` |
| `pytest -q -m "not slow and not browser"` | **PASS (128 passed, 4 deselected in 16.82s)** | `Isolated unit + regression suites` |
| `LoopOperator` Read-Only Audit | **PASS** | `21 areas, 0 open confirmed` |

## MCP Tools
Total registered tools: **13**

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
| `reporting` | 2 | YES | YES | - |
| `sandbox` | 4 | YES | YES | - |
| `scripts` | 3 | YES | YES | - |
| `server` | 1 | YES | YES | - |
| `synthesizer` | 3 | YES | YES | - |
| `tests` | 59 | YES | YES | - |
| `tournament` | 3 | YES | YES | - |
| `truth` | 5 | YES | YES | - |

## Active Audit Findings
No open audit findings detected in the current codebase.

## Recent Changes
- `a4ef4b1 feat(inspect): add 14 DevTools CDP collectors, coverage_matrix.md, and planted-bug fixture site`
- `c3a81bd feat(browser): add Chromium discovery, RFC 6455 CDP client, isolated [mcp_<browser>] cursors, and access gate`
- `977b8f2 feat(truth): add EvidenceVault hash chain, ClaimLedger, CitationChecker, Scoreboard, and TranscriptLogger`
- `3f51417 docs(phase1): add v2 PLAN, ARCHITECTURE, THREAT_MODEL, REQUIREMENTS_TRACE, and DEVIATIONS`
- `7e95e91 fix(phase0): reconcile state, enforce real coverage, add tool descriptions & pytest markers`
- `ab6765d docs: reconcile README, CONTRIBUTING, docs/, and historical report gitignore`
- `29f57e3 feat(reporting): add audited PROJECT_REPORT.md generator and pre-commit hook`
- `e3c026e fix(audit): preserve leading dotfiles in classify_area and guard post-fix detectors`
- `d2ba121 fix(audit): fix log_parser detector match, patch_parser probe, and agents/audit circular import`
- `4cf3bdb fix(ECC-020): escape markdown tables, use adaptive fences, show disqualification, frame prompts`
- `dec8234 fix(ECC-040): sync README and SKILL docs with MCP tools, scoring, and portable config`
- `9c1dfde fix(ECC-039): replace tautological security assertion and test all 5 providers with MockTransport`

## Working Tree Snapshot (`git status --short`)
```text
M  src/bugarena/agents/__init__.py
A  src/bugarena/agents/prompts/console_analyst.md
A  src/bugarena/agents/prompts/cross_browser_diff_analyst.md
A  src/bugarena/agents/prompts/dom_a11y_analyst.md
A  src/bugarena/agents/prompts/honesty_auditor.md
A  src/bugarena/agents/prompts/js_source_analyst.md
A  src/bugarena/agents/prompts/merge_analyst.md
A  src/bugarena/agents/prompts/network_analyst.md
A  src/bugarena/agents/prompts/performance_memory_analyst.md
A  src/bugarena/agents/prompts/report_writer.md
A  src/bugarena/agents/prompts/responsive_analyst.md
A  src/bugarena/agents/prompts/storage_security_analyst.md
A  src/bugarena/agents/prompts/verifier.md
M  src/bugarena/agents/registry.py
M  src/bugarena/inspect/__init__.py
A  src/bugarena/inspect/site_audit.py
A  src/bugarena/linking/__init__.py
A  src/bugarena/linking/sourcemap.py
A  src/bugarena/tournament/providers/cross_vendor.py
M  src/bugarena/tournament/providers/dispatcher.py
A  tests/unit/test_phase5_6_7_site_linking_grok.py
```

## How This Report Stays Updated
Run anytime after editing files (runs automatically on `git commit` when `.githooks` is active):
```bash
python scripts/update_project_report.py
```
