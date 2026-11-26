---
name: bugarena-repair
description: >-
  Autonomous multi-agent bug reproduction and fix tournament workflow using the BugArena MCP server.
  Use when the user has a software bug, runtime exception, stack trace, or failing test in a codebase
  and wants to automatically reproduce it, launch competing repair agents (Surgical Minimalist,
  Defensive Guardian, Deep Architectural Fixer, Contract Enforcer), verify candidate patches against
  regressions in an isolated ephemeral sandbox, and crown the most accurate fix with a unified git diff.
---

# BugArena Multi-Agent Bug Repair & Tournament Skill

This skill guides the agent through an autonomous, verified bug lifecycle. Rather than accepting a single LLM fix proposal that might introduce subtle regressions or excessive code churn, this workflow runs a competitive tournament where multiple candidate patches are objectively tested and scored.

---

## When to Activate

- The user reports a bug, error log, runtime exception, or unexpected behavior in a codebase.
- The user requests to "find and fix bugs with multiple agents", "recreate the bug and test fixes", or "compare bug fixes across agents".
- The user needs an objective guarantee that a proposed patch does not break existing test suites.

---

## Prerequisites & Tools

Ensure the `bugarena` MCP server is active in `mcp_config.json`. The server exposes:
- `bug_detect`: Scans repository and stack traces to isolate suspect AST scopes.
- `bug_reproduce`: Synthesizes a minimal pytest case and asserts the **Red baseline** (must fail on unpatched code).
- `agent_fix_tournament`: Registers candidate patches from distinct agent personas.
- `evaluate_patches`: Applies each patch in an ephemeral sandbox, executes reproduction + regression tests, and scores accuracy.
- `generate_fix_report`: Produces a comparative leaderboard and git-apply patch, saving a complete `.md` report to disk.
- `generate_bug_report`: Generates and saves a standalone `.md` diagnostic report containing the bug description, suspects, and reproduction test.
- `bugarena_autonomous_repair`: Executes the entire 5-stage tournament end-to-end and saves the `.md` report.
- `audit_start`: Initializes a read-only multi-agent audit run and module coverage tracker.
- `audit_round`: Runs one specialist detection, deduplication, and probe round.
- `audit_status`: Queries current round ledger counts and coverage percentage.
- `finding_verify`: Independently verifies or dismisses a candidate finding in the ledger.
- `audit_report`: Writes an evidence-graded audit report under `.bugarena/`.
- `fix_loop_start`: Orchestrates test-first remediation over confirmed audit findings.

---

## The 5-Stage Repair Workflow

### Stage 1: Bug Localization & AST Slicing
1. Call `bug_detect(repo_path, error_log, hint)` with the stack trace or error log.
2. Review the returned `suspects`:
   - Inspect `file_path`, `function_name`, `line_range`, and `code_snippet`.
   - Identify the primary suspect (highest confidence frame).

### Stage 2: Deterministic Red-First Reproduction
1. Call `bug_reproduce(repo_path, suspect_file, bug_description, function_name, call_expr, expected_behavior)`.
2. Verify the response status:
   - **`REPRODUCED_RED`**: Confirmed! The synthesized test fails on the original codebase with the expected error signature.
   - **`FALSE_POSITIVE_REPRO`**: The test passed on the unpatched codebase. Adjust `call_expr` or `expected_behavior` to accurately capture the defect.
3. Save `test_file_path` and `test_code` for verification.

### Stage 3: Multi-Agent Candidate Generation
Formulate candidate patches using 4 distinct engineering perspectives:
1. **Surgical Minimalist**:
   - Objective: Minimum lines changed, zero reformatting, exact control flow preserved.
   - Ideal for: Hotfixes and critical paths.
2. **Defensive Guardian**:
   - Objective: Robust guard clauses, precondition checks, null-safety, and exception handling.
   - Ideal for: Boundary errors and uncaught exceptions.
3. **Deep Architectural Fixer**:
   - Objective: Identifies root design flaws and refactors clean abstractions.
   - Ideal for: State synchronization, race conditions, or bad contracts.
4. **Contract & Type Enforcer**:
   - Objective: Enforces strict type signatures, Pydantic/dataclass validation, and invariants.

Submit candidate diffs using `agent_fix_tournament(repo_path, repro_test_file, candidate_patches_raw)`.

### Stage 4: Sandboxed Verification & Scoring
1. Call `evaluate_patches(repo_path, tournament_id, repro_test_file, repro_code)`.
2. Each patch is tested inside an ephemeral temp-directory copy of the repository (or optional `docker`/`podman --network=none --read-only --cap-drop=ALL` container when `BUGARENA_SANDBOX_MODE=container`):
   - **Red-to-Green Gate**: The reproduction test must PASS.
   - **Zero Regression Gate**: Regressions in existing tests must equal 0.
   - **AST & Churn Analysis**: Penalizes unnecessary churn ($Q_{\text{churn}}$) and cyclomatic complexity increases ($Q_{\text{complexity}}$).
3. The server computes the composite score $S(p) \in [0, 100]$:
   $$S(p) = 40 \cdot R(p) + 30 \cdot Q_{\text{reg}}(p) + 15 \cdot Q_{\text{churn}} + 10 \cdot Q_{\text{complexity}} + 5 \cdot Q_{\text{mutation}}$$
   (`Q_reg = 0` when `total_regressions_checked == 0`, and `Q_mutation = 0` when unmeasured.)

### Stage 5: Fix Presentation & Application
1. Call `generate_fix_report(tournament_id, format="markdown")`.
2. Present the winning **Champion Patch** to the user with:
   - Comparative leaderboard showing all competing personas.
   - Why the champion won (e.g., zero regressions + minimal churn).
   - Unified git diff.
   - Command to apply: `git apply fix.patch`.

---

## Fast-Path: End-to-End Autonomous Repair

For single-call execution, invoke `bugarena_autonomous_repair`:
```python
result = call_mcp_tool(
    "bugarena",
    "bugarena_autonomous_repair",
    {
        "repo_path": "/path/to/repo",
        "error_log": "<stack trace>",
        "bug_description": "divide(10, 0) raises ZeroDivisionError instead of returning 0.0",
        "call_expr": "Calculator().divide(10, 0)",
        "expected_behavior": "Calculator().divide(10, 0) == 0.0",
        "candidate_patches_raw": [
            {
                "candidate_id": "cand_surgical_01",
                "persona": "surgical_minimalist",
                "explanation": "Added zero check guard clause",
                "diff": "--- a/src/calc.py\n+++ b/src/calc.py\n@@ -3,2 +3,4 @@\n def divide(self, a: float, b: float) -> float:\n+    if b == 0:\n+        return 0.0\n     return a / b\n",
            }
        ],
    },
)
```
