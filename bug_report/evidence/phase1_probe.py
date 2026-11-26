"""Read-only Phase 1 diagnostic probe exercising BugArena flows in temp workspaces."""

import asyncio
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

from bugarena.discovery.ast_analyzer import locate_faulty_ast_slice
from bugarena.discovery.engine import BugDiscoveryEngine
from bugarena.discovery.log_parser import parse_python_traceback
from bugarena.evaluation.ast_metrics import calculate_cyclomatic_delta
from bugarena.evaluation.test_runner import PatchEvaluator
from bugarena.models.agent import CandidatePatch, PersonaType
from bugarena.models.bug import BugSpec, SuspectLocation
from bugarena.models.repro import ReproTestSpec
from bugarena.reporting.markdown_formatter import format_markdown_report
from bugarena.sandbox.manager import EphemeralSandboxManager
from bugarena.sandbox.security import scrub_sensitive_data, validate_safe_path
from bugarena.server import (
    agent_fix_tournament,
    bug_reproduce,
    evaluate_patches,
    generate_bug_report,
    generate_fix_report,
)
from bugarena.synthesizer.red_validator import validate_red_baseline
from bugarena.synthesizer.test_generator import generate_reproduction_test_code
from bugarena.tournament.patch_parser import PatchValidationError, parse_and_validate_patch
from bugarena.tournament.providers.dispatcher import (
    MultiModelDispatcher,
    extract_diff_and_explanation,
)
from bugarena.tournament.runner import TournamentRunner


def run_probe(name: str, fn):
    print(f"\n=== PROBE: {name} ===")
    try:
        res = fn()
        print("RESULT:", res)
    except Exception:
        print("EXCEPTION TRACEBACK:")
        traceback.print_exc()


def probe_1_test_generator_raises_case():
    s = SuspectLocation(
        file_path="src/calc.py",
        function_name="divide",
        line_range=(1, 2),
        confidence=0.9,
        bug_type="ZeroDivisionError",
        reasoning="err",
        code_snippet="return a / b",
    )
    return generate_reproduction_test_code(
        suspect=s,
        bug_description="raises error",
        call_expr="divide(1, 0)",
        expected_behavior="Raises ZeroDivisionError",
    )


def probe_2_test_generator_assert_prefix():
    s = SuspectLocation(
        file_path="src/calc.py",
        function_name="divide",
        line_range=(1, 2),
        confidence=0.9,
        bug_type="ZeroDivisionError",
        reasoning="err",
        code_snippet="return a / b",
    )
    return generate_reproduction_test_code(
        suspect=s,
        bug_description="asserts behavior",
        call_expr="divide(1, 0)",
        expected_behavior="assert divide(1, 0) == 0",
    )


def probe_3_test_generator_src_layout_false_repro():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "src" / "pkg").mkdir(parents=True)
        (repo / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (repo / "src" / "pkg" / "helper.py").write_text("VAL = 42\n", encoding="utf-8")
        (repo / "src" / "pkg" / "mod.py").write_text(
            "from pkg.helper import VAL\ndef get_val():\n    return VAL\n",
            encoding="utf-8",
        )
        # Note: get_val() actually ALREADY returns 42 (no bug!), yet test_generator
        # fails to import src.pkg.mod due to missing src on sys.path, swallows ImportError,
        # gets NameError on get_val(), and validate_red_baseline falsely reports REPRODUCED_RED!
        s = SuspectLocation(
            file_path="src/pkg/mod.py",
            function_name="get_val",
            line_range=(2, 3),
            confidence=0.9,
            bug_type="AssertionError",
            reasoning="test",
            code_snippet="",
        )
        code = generate_reproduction_test_code(
            suspect=s,
            bug_description="get_val returns 42",
            call_expr="get_val()",
            expected_behavior="get_val() == 42",
        )
        spec = validate_red_baseline(repo, "tests/repro/test_issue_abc.py", code)
        return {
            "red_baseline_verified": spec.red_baseline_verified,
            "exit_code": spec.initial_outcome.exit_code,
            "stdout": spec.initial_outcome.stdout,
            "stderr": spec.initial_outcome.stderr,
        }


def probe_4_apply_patch_blank_lines_and_append():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        f = repo / "app.py"
        f.write_text("line1\nline2\n", encoding="utf-8")
        mgr = EphemeralSandboxManager(repo)
        # Standard unified diff inserting at end of file (git diff @@ -2,0 +3,1 @@) + trailing blank line
        diff = "--- a/app.py\n+++ b/app.py\n@@ -2,0 +3,1 @@\n+line3\n\n"
        with mgr.create_sandbox() as sb:
            mgr.apply_patch(sb, diff)
            return repr((sb / "app.py").read_text(encoding="utf-8"))


def probe_5_apply_patch_deleted_sql_comment():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        f = repo / "query.sql"
        f.write_text("-- old comment\nSELECT 1;\n", encoding="utf-8")
        mgr = EphemeralSandboxManager(repo)
        diff = "--- a/query.sql\n+++ b/query.sql\n@@ -1,2 +1,1 @@\n--- old comment\n SELECT 1;\n"
        with mgr.create_sandbox() as sb:
            mgr.apply_patch(sb, diff)
            return repr((sb / "query.sql").read_text(encoding="utf-8"))


def probe_6_apply_patch_wrong_context_corrupts():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        f = repo / "app.py"
        f.write_text("def a():\n    return 1\n\ndef b():\n    return 2\n", encoding="utf-8")
        mgr = EphemeralSandboxManager(repo)
        # Wrong line numbers/context: claims line 1 is def b()
        diff = "--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n def b():\n-    return 2\n+    return 99\n"
        with mgr.create_sandbox() as sb:
            mgr.apply_patch(sb, diff)
            return repr((sb / "app.py").read_text(encoding="utf-8"))


def probe_7_patch_parser_protected_bypass_and_crlf():
    results = {}
    # Bypass via ../ normalization
    bypass_diff = "--- a/tests/repro/../repro/test_issue_1.py\n+++ b/tests/repro/../repro/test_issue_1.py\n@@ -1,1 +1,1 @@\n-assert False\n+assert True\n"
    p = parse_and_validate_patch(
        bypass_diff, PersonaType.SURGICAL_MINIMALIST, "bypass", protected_paths=["tests/repro/test_issue_1.py"]
    )
    results["bypass_accepted"] = True
    results["bypass_diff_mod"] = p.diff.splitlines()[1]

    # False positive on filename substring
    try:
        fp_diff = "--- a/src/calc.py\n+++ b/src/calc.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
        parse_and_validate_patch(
            fp_diff, PersonaType.SURGICAL_MINIMALIST, "fp", protected_paths=["tests/test_src/calc.py"]
        )
        results["false_positive"] = False
    except PatchValidationError as e:
        results["false_positive"] = str(e)

    # CRLF diff
    try:
        crlf_diff = "--- a/src/calc.py\r\n+++ b/src/calc.py\r\n@@ -1,1 +1,1 @@\r\n-a\r\n+b\r\n"
        parse_and_validate_patch(crlf_diff, PersonaType.SURGICAL_MINIMALIST, "crlf")
        results["crlf_accepted"] = True
    except PatchValidationError as e:
        results["crlf_error"] = str(e)

    return results


def probe_8_cyclomatic_delta_syntax_error():
    return calculate_cyclomatic_delta("def f():\n    return 1\n", "def broken(:\n")


def probe_9_evaluator_no_tests_dir_and_syntax_broken_file_and_cc_ignored():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "src").mkdir()
        (repo / "src" / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (repo / "src" / "other.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
        # No tests/ directory!
        cand = CandidatePatch(
            candidate_id="c1",
            persona=PersonaType.SURGICAL_MINIMALIST,
            diff="--- a/src/calc.py\n+++ b/src/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n",
            explanation="fix",
            lines_added=1,
            lines_deleted=1,
        )
        repro = ReproTestSpec(
            test_file_path="tests/repro/test_add.py",
            test_code="from src.calc import add\ndef test_add():\n    assert add(1, 2) == 3\n",
            red_baseline_verified=True,
        )
        ev = PatchEvaluator(repo)
        evals_no_tests, champ_no_tests = ev.evaluate_candidates([cand], repro)

        # Now add tests/ dir and test a patch that adds huge complexity + syntax error in other.py
        (repo / "tests").mkdir()
        (repo / "tests" / "test_ok.py").write_text("def test_pass():\n    assert True\n", encoding="utf-8")
        complex_broken_cand = CandidatePatch(
            candidate_id="c_broken",
            persona=PersonaType.ARCHITECTURAL_FIXER,
            diff=(
                "--- a/src/calc.py\n+++ b/src/calc.py\n@@ -1,2 +1,14 @@\n"
                " def add(a, b):\n"
                "+    if a > 0:\n+        if b > 0:\n+            if a > 1:\n+                if b > 1:\n"
                "+                    if a > 2:\n+                        if b > 2:\n+                            pass\n"
                "+    if a < 0 and b < 0 or a == 0 or b == 0:\n+        pass\n"
                "-    return a - b\n+    return a + b\n"
                "--- a/src/other.py\n+++ b/src/other.py\n@@ -1,2 +1,2 @@\n"
                "-def ok():\n+def broken(:\n     return 1\n"
            ),
            explanation="complex + syntax error",
            lines_added=11,
            lines_deleted=2,
        )
        evals_broken, champ_broken = ev.evaluate_candidates([complex_broken_cand], repro)
        return {
            "no_tests_dir_champ": champ_no_tests,
            "no_tests_dir_eval": evals_no_tests[0].model_dump(),
            "broken_syntax_champ": champ_broken,
            "broken_syntax_eval": evals_broken[0].model_dump(),
        }


def probe_10_discovery_venv_rglob_and_empty_ast():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".venv" / "Lib" / "site-packages" / "pkg").mkdir(parents=True)
        (repo / ".venv" / "Lib" / "site-packages" / "pkg" / "runner.py").write_text(
            "def run():\n    raise RuntimeError('venv')\n", encoding="utf-8"
        )
        (repo / "src").mkdir()
        (repo / "src" / "runner.py").write_text("def run():\n    return 1\n", encoding="utf-8")
        trace = 'Traceback (most recent call last):\n  File "/usr/lib/python3.11/runner.py", line 2, in run\n    raise RuntimeError("boom")\nRuntimeError: boom\n'
        eng = BugDiscoveryEngine(repo)
        spec = eng.discover_from_trace(trace)
        empty_ast = locate_faulty_ast_slice("", 5)
        lambda_traces = parse_python_traceback(
            'Traceback (most recent call last):\n  File "src/runner.py", line 1, in <lambda>\n    fn = lambda x: 1/x\nZeroDivisionError: division by zero\n'
        )
        return {
            "suspects": [s.model_dump() for s in spec.suspects],
            "empty_ast": empty_ast,
            "lambda_func_parsed": lambda_traces[0].function_name if lambda_traces else None,
        }


def probe_11_dispatcher_routing_and_extraction():
    res = {}
    llm_out = (
        "Explanation before.\n\n"
        "```diff\n"
        "diff --git a/src/calc.py b/src/calc.py\n"
        "index 111..222 100644\n"
        "--- a/src/calc.py\n"
        "+++ b/src/calc.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-return a / b\n"
        "+return a / (b or 1)\n"
        "```\n\n"
        "Explanation after the code block.\n"
    )
    diff, expl = extract_diff_and_explanation(llm_out)
    res["extracted_diff"] = diff
    res["extracted_expl"] = expl

    # Check Ollama model routing bug
    async def check_routing():
        d = MultiModelDispatcher(timeout_seconds=0.1)
        # Clear API keys in local test scope temporarily? Never mutate real env permanently, just inspect via monkeypatch-like restore
        old = {k: os.environ.get(k) for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY")}
        try:
            for k in old:
                os.environ.pop(k, None)
            bug = BugSpec(bug_id="b", repo_path=".", error_log="err")
            rep = ReproTestSpec(test_file_path="t.py", test_code="pass", red_baseline_verified=True)
            _, r_ollama_llama = await d.generate_patch(PersonaType.SURGICAL_MINIMALIST, bug, rep, model_override="ollama/llama3.1")
            _, r_ollama_gemma = await d.generate_patch(PersonaType.SURGICAL_MINIMALIST, bug, rep, model_override="ollama/gemma2:9b")
            os.environ["GROQ_API_KEY"] = "dummy"
            _, r_claude_fallback = await d.generate_patch(PersonaType.SURGICAL_MINIMALIST, bug, rep, model_override="claude-3-5-sonnet")
            return {
                "ollama_llama_routed_msg": r_ollama_llama,
                "ollama_gemma_routed_msg": r_ollama_gemma,
                "claude_with_groq_fallback_msg": r_claude_fallback,
            }
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    res["routing"] = asyncio.run(check_routing())
    res["default_runner_personas"] = [p.value for p in TournamentRunner().personas]
    return res


def probe_12_server_report_and_scrubber():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "src").mkdir()
        (repo / "tests").mkdir()
        (repo / "src" / "calc.py").write_text("def div(a, b):\n    return a / b\n", encoding="utf-8")
        (repo / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

        repro = bug_reproduce(
            repo_path=str(repo),
            suspect_file="src/calc.py",
            bug_description="div(1, 0) fails",
            function_name="div",
            call_expr="div(1, 0)",
            expected_behavior="div(1, 0) == 0",
        )
        # Call generate_bug_report after bug_reproduce: check if repro_spec was linked!
        bug_rep = generate_bug_report(
            repo_path=str(repo),
            error_log=f'Traceback (most recent call last):\n  File "{repo / "src" / "calc.py"}", line 2, in div\n    return a / b\nZeroDivisionError: division by zero\n',
            output_file=str(repo / "out_bug.md"),
        )
        tourn = agent_fix_tournament(
            repo_path=str(repo),
            repro_test_file=repro["test_file_path"],
            candidate_patches_raw=[
                {
                    "candidate_id": "c1",
                    "persona": "surgical_minimalist",
                    "explanation": "guard 0",
                    "diff": "--- a/src/calc.py\n+++ b/src/calc.py\n@@ -1,2 +1,4 @@\n def div(a, b):\n+    if b == 0:\n+        return 0\n     return a / b\n",
                }
            ],
        )
        ev = evaluate_patches(
            repo_path=str(repo),
            tournament_id=tourn["tournament_id"],
            repro_test_file=repro["test_file_path"],
            repro_code=repro["test_code"],
        )
        fix_rep = generate_fix_report(
            tournament_id=tourn["tournament_id"],
            format="json",
            output_file=str(repo / "out_fix.json"),
        )
        win_path = r"C:\Users\alice\AppData\Local\Temp\bugarena_sandbox_123"
        scrubbed = scrub_sensitive_data(f"Error in {win_path}\\src\\calc.py", base_dir=win_path)
        return {
            "bug_report_includes_repro_section": "Failing Reproduction Test" in bug_rep["report_markdown"],
            "fix_report_champion_patch_in_model": fix_rep["report"]["champion_patch"],
            "fix_report_champion_eval_in_model": fix_rep["report"]["champion_eval"],
            "fix_report_json_file_starts_with": Path(fix_rep["report_file_path"]).read_text(encoding="utf-8")[:40],
            "scrubbed_win_path": scrubbed,
            "validate_safe_path_dot": str(validate_safe_path(repo, ".")),
        }


if __name__ == "__main__":
    for name, fn in [
        ("1_test_generator_raises_case", probe_1_test_generator_raises_case),
        ("2_test_generator_assert_prefix", probe_2_test_generator_assert_prefix),
        ("3_test_generator_src_layout_false_repro", probe_3_test_generator_src_layout_false_repro),
        ("4_apply_patch_blank_lines_and_append", probe_4_apply_patch_blank_lines_and_append),
        ("5_apply_patch_deleted_sql_comment", probe_5_apply_patch_deleted_sql_comment),
        ("6_apply_patch_wrong_context_corrupts", probe_6_apply_patch_wrong_context_corrupts),
        ("7_patch_parser_protected_bypass_and_crlf", probe_7_patch_parser_protected_bypass_and_crlf),
        ("8_cyclomatic_delta_syntax_error", probe_8_cyclomatic_delta_syntax_error),
        ("9_evaluator_no_tests_dir_and_syntax_broken_file_and_cc_ignored", probe_9_evaluator_no_tests_dir_and_syntax_broken_file_and_cc_ignored),
        ("10_discovery_venv_rglob_and_empty_ast", probe_10_discovery_venv_rglob_and_empty_ast),
        ("11_dispatcher_routing_and_extraction", probe_11_dispatcher_routing_and_extraction),
        ("12_server_report_and_scrubber", probe_12_server_report_and_scrubber),
    ]:
        run_probe(name, fn)
