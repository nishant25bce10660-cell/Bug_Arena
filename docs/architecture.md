# Architecture

[Documentation index](README.md) · [Project overview](../README.md)

## Repair pipeline

The [MCP server](../src/bugarena/server.py) orchestrates these components. Supplying candidate diffs exercises the repair flow without model generation.

| Package | Responsibility |
| --- | --- |
| `models` | Pydantic contracts for bugs, reproductions, candidates and results |
| `discovery` | Traceback parsing, file resolution and AST scope lookup |
| `synthesizer` | Reproduction construction and failing-baseline validation |
| `tournament` | Persona prompts, provider dispatch, candidate parsing |
| `sandbox` | Temporary copies, path validation and command execution |
| `evaluation` | Patch application, tests, AST metrics and scoring |
| `reporting` | Markdown formatting and report persistence |
| `agents` | Specialist role registry, prompts and execution |
| `audit` | Rounds, ledger, deduplication, probes and fix evaluation |

## State and outputs

Repair registries in `server.py` are bounded, process-local structures. Restarting the server loses those in-memory IDs. Audit runs are persisted by [LoopOperator](../src/bugarena/audit/loop.py); inspect `audit_status` rather than assuming every finding is confirmed.

The [fix loop](../src/bugarena/audit/fix_loop.py) evaluates candidate patches in temporary workspaces. Its result is an evaluation and champion identifier, not automatic application to the user's checkout. Review an exported diff before applying it.

## Scoring

The [scorer](../src/bugarena/evaluation/scorer.py) uses:

```text
score = 40 × reproduction_passed
      + 30 × regression_quality
      + 15 × churn_quality
      + 10 × complexity_quality
      +  5 × mutation_kill_ratio

regression_quality = 1 - failures / total_tests (0 when no tests were checked)
churn_quality      = max(0, 1 - lines_changed / 50)
complexity_quality = max(0, 1 - max(0, cyclomatic_delta) / 10)
mutation component = 0 when unmeasured
```

Reproduction failure or failing regression checks causes disqualification and a zero score. Syntax validation happens before scoring. The regression metric counts failures in the patched suite; it is not a general comparison against every pre-existing baseline failure.

The evaluator currently supplies no measured mutation score. Formula tests do not establish that higher scores predict success on unseen repositories.

## Audit evidence

The [ledger](../src/bugarena/audit/ledger.py) distinguishes states and evidence levels. [Verification](../src/bugarena/audit/verify.py) and [deduplication](../src/bugarena/audit/dedupe.py) support review. With `auto_generate=false`, roles use offline detectors. With generation enabled, role output is schema-validated.

Area coverage means the engine tracked examination of repository areas. It is **not** statement/branch test coverage, a completeness guarantee, or proof that no bugs remain. Offline detectors include project-specific checks; broad performance on other projects remains unbenchmarked.

## BugArena MCP v2 Subsystems

| Package | Responsibility |
| --- | --- |
| `truth` | Append-only SHA-256 hash-chained `EvidenceVault` (`manifest.jsonl`, `redactions.json`), `ClaimLedger`, `CitationChecker`, `CorrectionLog`, `AgentScoreboard` (`.bugarena/agent_scores.json`) |
| `browser` | Chromium discovery (`chrome`, `brave`, `helium`), isolated `--user-data-dir` launcher, stdlib RFC 6455 CDP client, capability-scoped `[mcp_<browser>]` cursors, authorization gate & questionnaire |
| `inspect` | 14 DevTools collectors (`DOM`, `Runtime`/`Log`, `Audits`, `Debugger`/`Profiler`, `Network`, `Performance`, `HeapProfiler`, `Storage`, `Security`, `Overlay`/`LayerTree`, `Emulation`, `Input`, cross-browser diff) + `coverage_matrix.md` |
| `linking` | VLQ source-map parser linking production JS stack frames to local source `file:line` (`site_only` / `project_only` / `linked`) |
| `verify` | Self-contained `verify/` pack (`verify.py` stdlib-only SHA-256, chain, schema, quote & count checker, `claims.json`, `VERIFY_PROMPT.md`) |
| `skills_merge` | Quarantined `merge_both_skills` pipeline: AST security scan, permission manifest, dependency compat dry-run, isolated smoke test, adapter registry preserving BugArena as primary |

### Data Flow & Trust Boundaries
1. **Pre-Start Gate:** `session_prepare` -> questionnaire -> `session_confirm` issues a scoped token and forces passive mode whenever authorization is `neither`.
2. **Isolated Cursors:** Each browser runs in a dedicated temp profile on loopback `127.0.0.1` via CDP only (zero OS mouse/keyboard input).
3. **Truth Gate:** Raw outputs enter `EvidenceVault` -> citations verified against stored artifacts -> independent `verifier` replay + `honesty-auditor` pass -> only `CONFIRMED` findings with intact hashes reach `REPORT.md` / `REPORT.pdf`.
