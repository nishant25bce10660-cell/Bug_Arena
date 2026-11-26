# State Verification & Red-Flag Audit (Phase 0.2 / 0.4 / 0.5)

Verification executed from `d:\MCP server` on branch `upgrade/bugarena-agents` before starting v2 feature implementation.

## 1. Verification of Section 2 Red Flags

| # | Red Flag Hypothesis | Verdict | Measured Proof & Remediation |
| :---: | :--- | :--- | :--- |
| 1 | `"PASS — Clean Audit"` with `0/0/0/0` could mean a dead detector | **Disproved as dead engine; baseline verified** | Running `LoopOperator` on a detached `git worktree` of `46acbdee6cba97f74341636adc72794fc437bd87` returned `ROUND 1 | new: 36 | confirmed: 34 | dismissed: 0 | fixed: 0 | open: 34`, **21/21 (100%)** BugArena recall and **42/43 (97.7%)** ECC file-level recall (`BUG-023` grouped inside `F-029` domain models). |
| 2 | `fixed: 0` in `PROJECT_REPORT.md` despite 36 `fix(ECC-*)` commits | **Confirmed** | `scripts/update_project_report.py` started an empty fresh `project_audit` run without reading `.bugarena/runs/main_upgrade_audit/ledger.json` (`75 FIXED`) or git `fix(...)` history. **Fix:** `update_project_report.py` now reports reconciled historical ledger fix counts + git fix commits alongside live open findings. |
| 3 | Only 9 specialist roles vs planned 14+ roster | **Confirmed gap for v2** | `src/bugarena/agents/registry.py` registers `17` roles total (`9` `SWEEP_ROLES`, `loop-operator`, `code-architect`, `agent-evaluator`, `4` `fix-author-*`, `fix-reviewer`), lacking the v2 site analysts, `report-writer`, `verifier`, `honesty-auditor`, and `merge-analyst`. Planned for Phases 2–10. |
| 4 | Coverage `"Dynamic/Tested = YES"` heuristic for `docs` and `packaging` | **Confirmed** | `src/bugarena/audit/coverage.py:43` previously allowed `a.area in ("docs", "packaging")` to pass coverage without `dynamic_probe` or `test_exists`. **Fix:** removed heuristic bypass in `CoverageMatrix.coverage_pct` and required real `dynamic_probe or test_exists`, proven by `test_phase0_fixes.py` (`93.33%` on `46acbde` vs `100.0%` on `upgrade/bugarena-agents` where doc/packaging tests actually exist). |
| 5 | `PROJECT_REPORT.md` only listed 12 recent commits | **Confirmed** | `git log --oneline --grep="fix(ECC-"` confirmed **43/43** `ECC-001`..`ECC-043` IDs mapped to fix commits (`MISSING_IN_COMMIT_MSG: []`), covering Phases A–F completely. `update_project_report.py` now counts/lists full `fix(...)` coverage. |
| 6 | 7 original tools showed `-` descriptions in `PROJECT_REPORT.md` | **Confirmed** | `server.py` relied on multiline docstrings starting with `\n`, causing `.splitlines()[0]` to extract empty text. **Fix:** added explicit `description=...` on all 7 original `@mcp.tool(...)` decorators and normalized multiline tool descriptions in `update_project_report.py`. |
| 7 | Dirty working tree & non-idempotent `pre-commit` hook | **Confirmed** | Prior doc review left modified `.env.example`, `.gitignore`, `PROJECT_REPORT.md`, `README.md`, and untracked `CONTRIBUTING.md`, `docs/`. Committed doc cleanup (`ab6765d`), updated `update_project_report.py` with idempotent volatile-line filtering (`unchanged` detection), and switched `.githooks/pre-commit` to `--fast --stage`. |
| 8 | 93–97s test suite slows iteration loop | **Confirmed** | `pytest -q --durations=15` measured `112 passed in 92.94s`, with `test_generate_project_report_runs_audit_and_writes_markdown` (`46.92s`) and `test_ecc_014_033` (`22.34s`) accounting for 69.26s. **Fix:** declared `slow` and `browser` markers in `pyproject.toml` and marked those tests `@pytest.mark.slow`; fast tier runs in `47.03s` (`114 passed, 2 deselected`). |

## 2. Prior Findings Reconciliation (Phase 0.4)
- `git log --oneline --grep="fix(ECC-"`: `43/43` ECC IDs matched directly to commits (`ECC-001`..`ECC-043`, zero missing).
- `.bugarena/runs/main_upgrade_audit/ledger.json`: `77` tracked entries (`75 FIXED`, `2 DISMISSED`, `0 CONFIRMED`, `0 UNVERIFIED`).
