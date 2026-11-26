# BugArena MCP — Project & Audit Report

- **Generated (UTC):** `2026-11-26T10:34:40+00:00`
- **Repository:** `MCP server`
- **Branch / HEAD:** `upgrade/bugarena-agents` @ `e3c026e`
- **Tracked Files:** `121` across `17` audited areas
- **Auto-Update Trigger:** `.githooks/pre-commit` + `scripts/update_project_report.py` + `AGENTS.md`

## Audit Verdict
- **Overall Status:** **PASS — Clean Audit & Verification**
- **Audit Engine Summary:** `ROUND 1 | new: 0 | confirmed: 0 | dismissed: 0 | fixed: 0 | open: 0`
- **Module Coverage:** `100.0%` (`100.0%` statically read)
- **Open Confirmed Bugs:** `0` | **Dismissed:** `0` | **Unverified:** `0`

## Verification Status
| Check | Result | Details |
| :--- | :--- | :--- |
| `ruff check src tests scripts` | **PASS (0 issues)** | `All checks passed!` |
| `pytest -q --tb=short` | **PASS (112 passed in 105.82s (0:01:45))** | `Isolated unit + regression suites` |
| `LoopOperator` Read-Only Audit | **PASS** | `9 specialist roles, 17 areas, 0 open confirmed` |

## MCP Tools
Total registered tools: **13**

| Tool | Description |
| :--- | :--- |
| `bug_detect` | - |
| `bug_reproduce` | - |
| `agent_fix_tournament` | - |
| `evaluate_patches` | - |
| `generate_fix_report` | - |
| `generate_bug_report` | - |
| `bugarena_autonomous_repair` | - |
| `audit_start` | Initialize a multi-agent read-only or fix audit run and return its run_id. |
| `audit_round` | Execute one multi-agent sweep, independent verification, dedupe, and coverage round. |
| `audit_status` | Return ledger counts, coverage percentage, and stop-condition state for an audit run. |
| `finding_verify` | Force independent second-agent dynamic re-verification of one ledger finding. |
| `audit_report` | Generate an evidence-graded audit report; output_file is confined by validate_safe_path. |
| `fix_loop_start` | Execute test-first fix evaluation over confirmed ledger findings (LLM generation gated by auto_generate). |

## Coverage Matrix
| Area | Files | Static Read | Dynamic / Tested | Findings |
| :--- | :---: | :---: | :---: | :--- |
| `agents` | 18 | YES | YES | - |
| `audit` | 12 | YES | YES | - |
| `config` | 1 | YES | YES | - |
| `discovery` | 4 | YES | YES | - |
| `docs` | 3 | YES | YES | - |
| `evaluation` | 4 | YES | YES | - |
| `models` | 6 | YES | YES | - |
| `packaging` | 4 | YES | YES | - |
| `personas` | 2 | YES | YES | - |
| `providers` | 2 | YES | YES | - |
| `reporting` | 2 | YES | YES | - |
| `sandbox` | 4 | YES | YES | - |
| `scripts` | 3 | YES | YES | - |
| `server` | 1 | YES | YES | - |
| `synthesizer` | 3 | YES | YES | - |
| `tests` | 49 | YES | YES | - |
| `tournament` | 3 | YES | YES | - |

## Active Audit Findings
No open audit findings detected in the current codebase.

## Recent Changes
- `e3c026e fix(audit): preserve leading dotfiles in classify_area and guard post-fix detectors`
- `d2ba121 fix(audit): fix log_parser detector match, patch_parser probe, and agents/audit circular import`
- `4cf3bdb fix(ECC-020): escape markdown tables, use adaptive fences, show disqualification, frame prompts`
- `dec8234 fix(ECC-040): sync README and SKILL docs with MCP tools, scoring, and portable config`
- `9c1dfde fix(ECC-039): replace tautological security assertion and test all 5 providers with MockTransport`
- `00dec51 fix(ECC-043): ignore .env.*, reports, caches, .bugarena and comment .env.example blanks`
- `9569200 fix(ECC-036): add check_api_keys --dry-run, JSON guard, and portable path hint`
- `30eafc2 fix(ECC-007): add personas __init__ and complete reporting exports`
- `bd347de fix(ECC-006): declare httpx>=0.27.0 in project dependencies`
- `d3f5e6e fix(ECC-017): expand sandbox ignore patterns, symlink safety, and read-only cleanup`
- `393121c fix(ECC-015): use UTF-8 replace decoding, process-group kill, and bounded wait`
- `956312c fix(ECC-037): parallelize PatchEvaluator with deadline and enforce tool bounds`

## Working Tree Snapshot (`git status --short`)
```text
A  .githooks/pre-commit
A  AGENTS.md
A  scripts/update_project_report.py
M  src/bugarena/audit/coverage.py
A  tests/unit/test_project_report.py
?? "bug-report ECC/"
?? bug_report/
```

## How This Report Stays Updated
Run anytime after editing files (runs automatically on `git commit` when `.githooks` is active):
```bash
python scripts/update_project_report.py
```
