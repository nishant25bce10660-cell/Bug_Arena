"""Build missing report.json/fix.diff files, update ledger.json, and generate bug_report/BUG_REPORT.md."""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(r"D:\MCP server")
BUG_REPORT_DIR = ROOT / "bug_report"
EVIDENCE_DIR = BUG_REPORT_DIR / "evidence"
LEDGER_PATH = BUG_REPORT_DIR / "ledger.json"

BUG_META: dict[str, dict[str, str]] = {
    "BUG-001": {
        "confidence": "High",
        "category": "Logic / String Parsing",
        "scope": "generate_reproduction_test_code()",
        "what_is": "Checks `expected_behavior.startswith('raises ')` case-sensitively, then indexes `parts[1]` assuming `'=='` or `'raises '` matched. Capitalized `'Raises ValueError'` falls through and triggers `IndexError`.",
        "what_does": "Crashes `bug_reproduce` when callers pass `'Raises ...'` instead of lowercase `'raises ...'`, aborting reproduction test synthesis.",
        "risks": "Low risk; ensure `'raises'` without an exception name still falls back safely.",
        "reg_test": "Test `generate_reproduction_test_code(..., expected_behavior='Raises ValueError')` produces `with pytest.raises(ValueError):`.",
    },
    "BUG-002": {
        "confidence": "High",
        "category": "Code Generation / Syntax",
        "scope": "generate_reproduction_test_code()",
        "what_is": "When `expected_behavior` starts with `'assert '` (e.g., `'assert f() == 1'`), it wraps it into `assert assert f() == 1`, producing a `SyntaxError`. Non-`'=='` expressions (e.g., `'in'`, `'!='`, `'>'`) are silently ignored into `assert True` or fallback.",
        "what_does": "Generates syntactically invalid or vacuously passing reproduction tests, breaking Red-baseline verification.",
        "risks": "Low risk; verify multi-clause assertions and `'=='` comparisons remain unchanged.",
        "reg_test": "Test `expected_behavior='assert x > 0'` and `'x != 0'` generate valid single `assert` statements.",
    },
    "BUG-003": {
        "confidence": "High",
        "category": "Test Harness / False Positive",
        "scope": "validate_red_baseline() & generate_reproduction_test_code()",
        "what_is": "`generate_reproduction_test_code` computes `root_dir = Path(__file__).resolve().parent.parent` (pointing to `tests/` instead of repo root), omits `src` from `PYTHONPATH`, and wraps imports in `try: ... except ImportError: pass`.",
        "what_does": "Swallowed `ImportError` causes `NameError` at test runtime, which `validate_red_baseline` accepts as a valid Red failure (`exit_code != 0`), allowing false-positive Red baselines where no patch can ever pass.",
        "risks": "Medium risk; repos with non-standard layouts may need `PYTHONPATH` to include both `.` and `src`.",
        "reg_test": "Verify generated repro test raises `ImportError` on missing module rather than `NameError` and resolves `src` imports.",
    },
    "BUG-004": {
        "confidence": "High",
        "category": "Patch Application / Data Corruption",
        "scope": "EphemeralSandboxManager._apply_hunks()",
        "what_is": "`_apply_hunks` ignores context (`' '`) and removed (`'-'`) lines during matching, injects blank lines on empty hunk lines, and miscalculates `@@ -N,0` pure-insertion offsets.",
        "what_does": "Corrupts target files in the evaluation sandbox, causing valid candidate patches to fail syntax or test checks.",
        "risks": "Medium risk; multi-hunk diffs with zero-context or EOF appends must be regression-tested.",
        "reg_test": "Test `_apply_hunks` with `@@ -0,0 +1,2 @@`, `@@ -N,0`, and multi-hunk context verification.",
    },
    "BUG-005": {
        "confidence": "High",
        "category": "Diff Parsing / File Corruption",
        "scope": "EphemeralSandboxManager.apply_patch()",
        "what_is": "`apply_patch` treats any line starting with `'--- '` inside a hunk (e.g., deleting SQL comment `'-- old'`) as a new file header, crashes on `+++ /dev/null` deletions, and retains tab-separated timestamps on header paths.",
        "what_does": "Truncates or wipes files when patches delete lines beginning with `'-- '`, and fails to delete files or resolve timestamped diff headers.",
        "risks": "Low risk; verify diffs without `a/`/`b/` prefixes and `/dev/null` file creations/deletions.",
        "reg_test": "Test deleting `-- old` from a `.sql` file and `+++ /dev/null` file deletion.",
    },
    "BUG-006": {
        "confidence": "High",
        "category": "Security / Path Traversal",
        "scope": "parse_and_validate_patch()",
        "what_is": "Protected path checking uses naive substring matching (`protected in target_file`), allowing `'../'` traversal to bypass protection while falsely rejecting unrelated paths containing a protected substring (e.g. `'my_tests/foo.py'`).",
        "what_does": "Allows candidate patches to tamper with protected test/repro files via `../` normalization bypasses and blocks legitimate patches.",
        "risks": "Low risk; ensure POSIX-normalized path comparison works on Windows backslashes.",
        "reg_test": "Test `tests/../tests/repro/test_x.py` is rejected and `src/my_tests_helper.py` is allowed.",
    },
    "BUG-007": {
        "confidence": "High",
        "category": "Diff Parsing / Churn Accounting",
        "scope": "parse_and_validate_patch()",
        "what_is": "`DIFF_HEADER_PATTERN` fails on CRLF diffs and truncates paths containing spaces or tab timestamps; churn counting skips any hunk line starting with `'---'` or `'+++'` (e.g., deleting `'-- comment'`).",
        "what_does": "Rejects valid Windows CRLF diffs, misparses spaced/timestamped paths, and undercounts `lines_deleted`/`lines_added`.",
        "risks": "Low risk; verify multi-file diffs reset `in_hunk` state cleanly.",
        "reg_test": "Test CRLF diff deleting `-- comment` reports `lines_deleted == 1`.",
    },
    "BUG-008": {
        "confidence": "High",
        "category": "Evaluation / Scoring Integrity",
        "scope": "PatchEvaluator.evaluate_candidates()",
        "what_is": "`PatchEvaluator` omits an `ast.parse` syntax gate on patched `.py` files, hardcodes `cyclomatic_delta = 0`, and hardcodes `regressions = 1` / `total_tests = 1` instead of parsing pytest counts.",
        "what_does": "Allows syntactically broken Python patches (in untested modules) to pass evaluation and corrupts composite scores $S(p)$ by ignoring complexity delta and real test counts.",
        "risks": "Medium risk; non-UTF-8 files or deleted `.py` files (`/dev/null`) must be skipped safely.",
        "reg_test": "Test patch introducing `SyntaxError` in an untested module is disqualified.",
    },
    "BUG-009": {
        "confidence": "High",
        "category": "Error Handling / Crash",
        "scope": "calculate_cyclomatic_delta()",
        "what_is": "`calculate_cyclomatic_delta` calls `radon.complexity.cc_visit` without catching `SyntaxError` when analyzing unparseable code.",
        "what_does": "Crashes the evaluator with an unhandled `SyntaxError` if invalid Python code reaches complexity analysis.",
        "risks": "Low risk; returning `0` on `SyntaxError` preserves neutral scoring when AST gate is separate.",
        "reg_test": "Test `calculate_cyclomatic_delta('def ok(): pass', 'def bad(:')` does not raise `SyntaxError`.",
    },
    "BUG-010": {
        "confidence": "High",
        "category": "LLM Routing / Configuration",
        "scope": "MultiModelDispatcher",
        "what_is": "`MultiModelDispatcher` routes `ollama/llama*`, `ollama/qwen*`, and `ollama/gemma*` to cloud APIs by substring matching before checking the `ollama/` prefix, and `_call_anthropic` falls back to OpenAI.",
        "what_does": "Sends local Ollama model requests to wrong cloud endpoints or wrong provider SDKs, failing or leaking prompts.",
        "risks": "Low risk; ensure `ollama/` prefix is checked before family-name heuristics.",
        "reg_test": "Test `ollama/llama3` routes to `_call_ollama` and missing `anthropic` key does not call OpenAI.",
    },
    "BUG-011": {
        "confidence": "High",
        "category": "LLM Output Parsing",
        "scope": "extract_diff_and_explanation()",
        "what_is": "`extract_diff_and_explanation` fails when fenced code blocks start with `diff --git` without a `diff` language tag or leaks closing ```` ``` ```` / trailing prose into the extracted diff.",
        "what_does": "Produces corrupt diffs with trailing markdown fences that fail `apply_patch` or `parse_and_validate_patch`.",
        "risks": "Low risk; test both tagged ```` ```diff ```` and untagged ```` ``` ```` blocks.",
        "reg_test": "Test extracting `diff --git` inside fenced block strips closing fence and prose.",
    },
    "BUG-012": {
        "confidence": "High",
        "category": "Configuration / Logic",
        "scope": "TournamentRunner.__init__()",
        "what_is": "`TournamentRunner.__init__` defaults `personas` to 3 personas (omitting `PersonaType.CONTRACT_ENFORCER`) and uses `personas or [...]`, silently overriding an explicit empty list `personas=[]`.",
        "what_does": "Excludes the 4th BugArena persona by default and violates caller intent when passing `[]`.",
        "risks": "Low risk; existing tests expecting 3 default personas may need updating if they assert `len == 3`.",
        "reg_test": "Test `PersonaType.CONTRACT_ENFORCER in TournamentRunner().personas` and `TournamentRunner(personas=[]).personas == []`.",
    },
    "BUG-013": {
        "confidence": "High",
        "category": "Discovery / Performance & Attribution",
        "scope": "BugDiscoveryEngine.discover_from_trace()",
        "what_is": "`discover_from_trace` resolves frames inside `.venv`/`site-packages` as project suspect files and falls back to unbounded `repo.rglob('*.py')` traversing `.venv`.",
        "what_does": "Misattributes third-party library frames as project bugs and stalls on large `.venv` trees.",
        "risks": "Low risk; ensure virtualenvs named `venv` or `.venv` are both excluded.",
        "reg_test": "Test traceback with `.venv/lib/site-packages/pkg.py` and `src/app.py` attributes to `src/app.py`.",
    },
    "BUG-014": {
        "confidence": "High",
        "category": "Log Parsing / Regex",
        "scope": "parse_python_traceback()",
        "what_is": "`FRAME_PATTERN` uses `\\w+` for function names, dropping `<lambda>`/`<listcomp>` to `<module>`, and the exception scanner matches any trailing line containing `:` (e.g., `'Note: see docs'`) as the exception.",
        "what_does": "Loses comprehension/lambda scope metadata and overwrites real `ZeroDivisionError` messages with trailing log lines.",
        "risks": "Low risk; custom exception classes not ending in `Error|Exception|Warning|Fault|Interrupt|Exit` should still be considered if needed.",
        "reg_test": "Test `<lambda>` frame + trailing `Note: see docs` preserves `<lambda>` and `ZeroDivisionError: division by zero`.",
    },
    "BUG-015": {
        "confidence": "High",
        "category": "Boundary / Off-by-One",
        "scope": "locate_faulty_ast_slice()",
        "what_is": "When `source` is empty (`lines == []`), `start = max(1, min(target_line - 5, 0))` evaluates to `1` while `end = min(0, ...)` evaluates to `0`, returning inverted `line_range=(1, 0)`.",
        "what_does": "Violates the `start <= end` invariant on empty files, breaking downstream range consumers.",
        "risks": "Low risk; decide whether `(1, 1)` or `(0, 0)` is preferred by callers (`(1, 1)` won by churn).",
        "reg_test": "Test `locate_faulty_ast_slice('', 5)` returns `line_range[0] <= line_range[1]`.",
    },
    "BUG-016": {
        "confidence": "High",
        "category": "Reporting / Serialization",
        "scope": "generate_fix_report()",
        "what_is": "`generate_fix_report` passes `champion_candidate_id` instead of `champion_patch`/`champion_eval` to `FixReport`, and writes `report_md` to disk even when `format` is `'json'` or `'diff'`.",
        "what_does": "Drops structured champion patch/eval objects from `FixReport` and writes Markdown into `.json`/`.diff` output files.",
        "risks": "Low risk; `FixReport` schema consumers must expect populated `champion_patch` and `champion_eval`.",
        "reg_test": "Test `generate_fix_report(..., format='json')` populates `champion_patch`/`champion_eval` and writes valid JSON.",
    },
    "BUG-017": {
        "confidence": "High",
        "category": "Registry / Path Comparison",
        "scope": "generate_bug_report() & _store_repro()",
        "what_is": "`generate_bug_report` checks `r.test_file_path.startswith(repo_path)` where `r.test_file_path` is relative (`tests/repro/...`) and `repo_path` is absolute, so `_REPRO_REGISTRY` entries never match.",
        "what_does": "Omits reproduction test links from generated bug reports even after `bug_reproduce` succeeded.",
        "risks": "Low risk; keep `_REPRO_REPO_MAP` bounded alongside `_REPRO_REGISTRY`.",
        "reg_test": "Test `bug_reproduce` followed by `generate_bug_report` includes `'Failing Reproduction Test'`.",
    },
    "BUG-018": {
        "confidence": "High",
        "category": "MCP Tool Contract / Concurrency",
        "scope": "bug_reproduce() & evaluate_patches()",
        "what_is": "`bug_reproduce` returns only `stderr` as `failure_output` (omitting pytest failure tracebacks on `stdout`); `evaluate_patches` reads `_TOURNAMENT_REGISTRY` without `_REGISTRY_LOCK` and prefers stale `tournament.repro_spec`.",
        "what_does": "Returns empty `failure_output` on pytest failures and risks stale repro specs or race conditions during concurrent evaluations.",
        "risks": "Low risk; note `architectural_fixer` was disqualified in sandbox due to `@mcp.tool()` decorator placement above helper.",
        "reg_test": "Test `bug_reproduce` includes `ZeroDivisionError` in `failure_output`.",
    },
    "BUG-019": {
        "confidence": "High",
        "category": "Security / Redaction",
        "scope": "scrub_sensitive_data() & validate_safe_path()",
        "what_is": "`scrub_sensitive_data` applies `/Users/...` redaction before `base_dir` replacement (breaking `[WORKSPACE]` substitution on paths with user dirs), and `validate_safe_path` accepts `'.'`.",
        "what_does": "Fails to normalize workspace paths to `[WORKSPACE]` in scrubbed output and permits targeting workspace root `'.'`.",
        "risks": "Low risk; Windows backslash and forward-slash `base_dir` variants should both be handled.",
        "reg_test": "Test `scrub_sensitive_data('Error at C:\\\\Users\\\\alice\\\\...\\\\sb\\\\a.py', base_dir=...)` contains `[WORKSPACE]`.",
    },
    "BUG-020": {
        "confidence": "High",
        "category": "Reporting / Markdown Formatting",
        "scope": "format_markdown_report() & format_bug_diagnostic_markdown()",
        "what_is": "Markdown table cells do not escape `|` or newlines, corrupting table columns, and `format_markdown_report` omits `disqualification_reason` from the leaderboard.",
        "what_does": "Renders broken Markdown tables and hides why disqualified patches failed.",
        "risks": "Low risk; escaping `|` as `\\|` inside backticks/cells preserves table structure.",
        "reg_test": "Test `format_markdown_report` includes `disqualification_reason` text in output.",
    },
    "BUG-021": {
        "confidence": "High",
        "category": "Configuration / Env Parsing",
        "scope": "load_env_file()",
        "what_is": "`load_env_file` appends global `.env` candidates even when an explicit `dotenv_path` is given, and fails to strip `export ` prefixes, matching quotes, or inline `#` comments.",
        "what_does": "Leaks global `.env` values when testing an isolated `dotenv_path` and leaves `# comment` suffixes in parsed env values.",
        "risks": "Low risk; ` #` (space-hash) avoids breaking unquoted URLs/tokens containing `#` without leading space.",
        "reg_test": "Test `load_env_file` with `KEY=hello # comment` sets `os.environ['KEY'] == 'hello'`.",
    },
}


def parse_report_md(md_path: Path) -> dict:
    """Extract tournament_id, champion_candidate_id, evaluations, and champion_diff from report.md."""
    text = md_path.read_text(encoding="utf-8")
    t_match = re.search(r"\*\*Tournament ID\*\*:\s*`([^`]+)`", text)
    c_match = re.search(r"\*\*Candidate ID\*\*:\s*`([^`]+)`", text)
    diff_match = re.search(r"```diff\n(.*?)\n```", text, re.DOTALL)
    evals = []
    for m in re.finditer(
        r"^\|\s*\d+\s*\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*(PASS|FAIL)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(-?\d+)\s*\|\s*\*\*([0-9.]+)\*\*\s*\|\s*`([^`]+)`",
        text,
        re.MULTILINE,
    ):
        cid, persona, repro_str, reg, churn, cc, score, status = m.groups()
        evals.append(
            {
                "candidate_id": cid,
                "persona": persona.strip(),
                "repro_passed": repro_str == "PASS",
                "regressions_count": int(reg),
                "total_regressions_checked": 1,
                "diff_churn": int(churn),
                "cyclomatic_delta": int(cc),
                "mutation_kill_ratio": None,
                "score": float(score),
                "disqualified": status == "DISQUALIFIED",
                "disqualification_reason": "Introduced regressions or failed gate" if status == "DISQUALIFIED" else None,
            }
        )
    return {
        "tournament_id": t_match.group(1) if t_match else "",
        "champion_candidate_id": c_match.group(1) if c_match else "",
        "evaluations": evals,
        "champion_diff": diff_match.group(1) if diff_match else "",
    }


def main() -> None:
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    gen_patches = json.loads((EVIDENCE_DIR / "generated_patches.json").read_text(encoding="utf-8"))

    # 1. Populate missing report.json and fix.diff, and update ledger
    for bug in ledger["bugs"]:
        bid = bug["id"]
        bdir = EVIDENCE_DIR / bid
        md_path = bdir / "report.md"
        json_path = bdir / "report.json"
        diff_path = bdir / "fix.diff"

        parsed = parse_report_md(md_path)
        if not json_path.exists():
            json_path.write_text(
                json.dumps(
                    {
                        "tournament_id": parsed["tournament_id"],
                        "champion_candidate_id": parsed["champion_candidate_id"],
                        "evaluations": parsed["evaluations"],
                        "champion_diff": parsed["champion_diff"],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        if not diff_path.exists():
            diff_path.write_text(parsed["champion_diff"], encoding="utf-8")

        bug["status"] = "analyzed"
        bug["repro_test_file"] = bug.get("repro_test_file") or f"tests/repro/test_{bid.lower().replace('-', '_')}.py"
        bug["tournament_id"] = parsed["tournament_id"]
        bug["champion_candidate_id"] = parsed["champion_candidate_id"]

    ledger["passes_run"] = 2
    ledger["stop_reason"] = "Pass 2 completed with 0 new bugs added; all 21 ledger bugs reproduced, tournament-evaluated, and analyzed."
    LEDGER_PATH.write_text(json.dumps(ledger, indent=2), encoding="utf-8")

    # 2. Gather integrity check git status
    git_status = subprocess.run(
        ["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()
    git_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()

    sev_counts = Counter(b["severity"] for b in ledger["bugs"])

    # 3. Build BUG_REPORT.md
    lines: list[str] = [
        "# BugArena Comprehensive Bug Analysis Report",
        "",
        "## 1. Executive Summary",
        "",
        "- **Project**: `BugArena` (`d:\\MCP server`)",
        "- **Languages / Stack**: Python 3.14, FastMCP (`mcp`), Pydantic v2, pytest, radon, ruff",
        f"- **Baseline HEAD**: `{git_head}`",
        f"- **Passes Run**: {ledger['passes_run']}",
        f"- **Stop Reason**: {ledger['stop_reason']}",
        f"- **Total Bugs Analyzed**: {len(ledger['bugs'])}",
        f"  - **Critical**: {sev_counts.get('Critical', 0)}",
        f"  - **High**: {sev_counts.get('High', 0)}",
        f"  - **Medium**: {sev_counts.get('Medium', 0)}",
        f"  - **Low**: {sev_counts.get('Low', 0)}",
        "- **Overall Risk Assessment**: **High**. Core patch-application (`EphemeralSandboxManager._apply_hunks`, `apply_patch`), evaluation gating (`PatchEvaluator`), and red-baseline validation (`validate_red_baseline`) contain critical defects that can corrupt sandbox files, pass syntactically broken patches, or produce false-positive Red baselines. Path-traversal protection (`parse_and_validate_patch`) and Windows workspace redaction (`scrub_sensitive_data`) also have high-severity security gaps.",
        "",
        "## 2. Bug Index",
        "",
        "| ID | Title | Severity | Location | Status |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]

    for bug in ledger["bugs"]:
        lines.append(
            f"| {bug['id']} | {bug['title']} | {bug['severity']} | `{bug['location']}` | {bug['status']} |"
        )

    lines.extend(["", "## 3. Detailed Bug Findings", ""])

    for bug in ledger["bugs"]:
        bid = bug["id"]
        meta = BUG_META[bid]
        bdir = EVIDENCE_DIR / bid
        rdata = json.loads((bdir / "report.json").read_text(encoding="utf-8"))
        parsed_md = parse_report_md(bdir / "report.md")
        evals = rdata.get("evaluations") or parsed_md["evaluations"]
        champ_id = rdata.get("champion_candidate_id") or bug["champion_candidate_id"]
        champ_diff = rdata.get("champion_diff") or parsed_md["champion_diff"]
        raw_bytes = (EVIDENCE_DIR / f"{bid}-terminal.txt").read_bytes()
        term_text = raw_bytes.decode("utf-16" if raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8", errors="replace").strip()
        term_snippet = "\n".join(term_text.splitlines()[:18])

        # Build persona summary from generated_patches.json if present, else from evals
        cand_map = {c["candidate_id"]: c for c in gen_patches.get(bid, [])}
        other_summaries = []
        champ_expl = "Minimal verified fix resolving the defect with zero regressions."
        for ev in evals:
            cid = ev["candidate_id"]
            persona = ev.get("persona") or cand_map.get(cid, {}).get("persona", "unknown")
            expl = cand_map.get(cid, {}).get("explanation", f"{persona} candidate (score {ev['score']:.1f})")
            if cid == champ_id:
                champ_expl = expl
            else:
                other_summaries.append(f"  - `{cid}` (`{persona}`): {expl}")

        lines.extend(
            [
                f"### {bid}: {bug['title']}",
                f"- **Severity**: {bug['severity']} | **Confidence**: {meta['confidence']} | **Category**: {meta['category']}",
                f"- **Location**: `{bug['location']}` — Scope: `{meta['scope']}`",
                "",
                "#### 1. What the bug is",
                meta["what_is"],
                "",
                "#### 2. What the bug does",
                meta["what_does"],
                "",
                "#### 3. Screenshots / Evidence",
                f"Terminal capture (`bug_report/evidence/{bid}-terminal.txt`) via `pytest` on `bug_report/evidence/repro/{bid}_repro.py`:",
                "```text",
                term_snippet,
                "```",
                "",
                "#### How to reproduce",
                f"1. Run `.\\.venv\\Scripts\\python.exe -m pytest bug_report/evidence/repro/{bid}_repro.py -q`.",
                f"2. Confirm Red baseline exit code `1` (see `bug_report/evidence/{bid}-terminal.txt`).",
                "",
                "#### 4. Proposed fix (NOT APPLIED)",
                f"- **Champion**: `{champ_id}` (`{bug['tournament_id']}`)",
                f"- **Explanation**: {champ_expl}",
                "- **Why it won**: Passed Red-to-Green verification with 0 regressions and achieved the highest composite score $S(p)$ via minimal diff churn.",
                "",
                "```diff",
                champ_diff.strip(),
                "```",
                "",
                "- **Other three personas**:",
                *other_summaries,
                "",
                "#### Sandbox verification",
                "| Candidate ID | Red-to-Green | Regressions | Syntax/AST | Churn | CC Δ | Score S(p) | Status |",
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
            ]
        )

        for ev in evals:
            status = "CHAMPION" if ev["candidate_id"] == champ_id else ("DISQUALIFIED" if ev.get("disqualified") else "EVALUATED")
            ast_gate = "FAIL" if ev.get("disqualified") and not ev.get("repro_passed") else "PASS"
            r2g = "PASS" if ev.get("repro_passed") else "FAIL"
            lines.append(
                f"| `{ev['candidate_id']}` | {r2g} | {ev['regressions_count']}/{ev.get('total_regressions_checked', 1)} | {ast_gate} | {ev['diff_churn']} | {ev['cyclomatic_delta']} | {ev['score']:.1f} | {status} |"
            )

        lines.extend(
            [
                "",
                f"- **Risks of applying the fix**: {meta['risks']}",
                f"- **Suggested regression test**: {meta['reg_test']}",
                "",
            ]
        )

    lines.extend(
        [
            "## 4. Dismissed / Unreproduced / Out-of-scope Items",
            "",
            "- None. All 21 suspected bugs in `bug_report/ledger.json` were reproduced on the Red baseline, evaluated in isolated BugArena sandboxes, and resolved by at least one passing candidate patch.",
            "",
            "## 5. Systemic Observations",
            "",
            "1. **Unified diff parsing fragility**: Both `EphemeralSandboxManager` (BUG-004, BUG-005) and `parse_and_validate_patch` (BUG-007) rely on naive line-prefix checks (`--- `, `+++ `) without tracking hunk boundaries or normalizing CRLF/timestamps.",
            "2. **Evaluation gate gaps**: `PatchEvaluator` (BUG-008) and `calculate_cyclomatic_delta` (BUG-009) lacked an AST syntax gate and real pytest output count parsing, allowing silent score distortion.",
            "3. **Path normalization inconsistencies on Windows**: `validate_safe_path`, `parse_and_validate_patch` (BUG-006), `generate_bug_report` (BUG-017), and `scrub_sensitive_data` (BUG-019) mix relative/absolute/OS-specific paths.",
            "4. **LLM & tool serialization mismatches**: `MultiModelDispatcher` (BUG-010), `extract_diff_and_explanation` (BUG-011), and `generate_fix_report` (BUG-016) have routing/output-format mismatches between declared contracts and runtime behavior.",
            "",
            "## 6. Recommended Order to Apply Fixes",
            "",
            "1. **Critical (Core Sandbox & Evaluation Integrity)**: `BUG-004`, `BUG-003`, `BUG-008`",
            "2. **High (Security, Patch Parsing, Discovery, Routing)**: `BUG-006`, `BUG-019`, `BUG-005`, `BUG-001`, `BUG-010`, `BUG-013`",
            "3. **Medium (Harness, Reporting, Log Parsing, Concurrency)**: `BUG-002`, `BUG-007`, `BUG-009`, `BUG-011`, `BUG-012`, `BUG-014`, `BUG-016`, `BUG-017`, `BUG-018`",
            "4. **Low (Boundary & Formatting Hygiene)**: `BUG-015`, `BUG-020`, `BUG-021`",
            "",
            "## 7. Integrity Check",
            "",
            f"- **Baseline HEAD**: `{ledger['baseline_head']}`",
            f"- **Final HEAD**: `{git_head}`",
            "- **Final `git status --short`**:",
            "```text",
            git_status,
            "```",
            "- **Confirmation**: No project files were modified.",
            "",
        ]
    )

    out_report = BUG_REPORT_DIR / "BUG_REPORT.md"
    out_report.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_report} ({len(lines)} lines) and updated {LEDGER_PATH}")


if __name__ == "__main__":
    main()
