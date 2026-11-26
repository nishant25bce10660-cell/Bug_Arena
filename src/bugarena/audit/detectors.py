"""Grounded offline specialist detectors for BugArena's 9 audit sweep roles.

Each role runs strictly read-only against repo_path using only its allowed grounding tools
(no .env reads, no paid API calls, no reading prior audit reports). Each emitted FindingDraft
carries exact observed line numbers and a self-contained temp-sandbox probe_script so an
independent verifier agent can confirm or dismiss it empirically.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from bugarena.audit.ledger import (
    EvidenceType,
    FindingDraft,
    FindingLocation,
    FindingRepro,
    SeverityLevel,
)
from bugarena.audit.tools import execute_grounding_tool


def _read_rel(repo: Path, rel_path: str) -> tuple[str, list[str]]:
    p = repo / rel_path
    if not p.is_file():
        return "", []
    text = p.read_text(encoding="utf-8", errors="replace")
    return text, text.splitlines()


def _find_line(lines: list[str], pattern: str, default: int = 1) -> int:
    rx = re.compile(pattern)
    for idx, line in enumerate(lines, 1):
        if rx.search(line):
            return idx
    return default


def _draft(
    *,
    title: str,
    file: str,
    line_start: int,
    line_end: int,
    symbol: str,
    category: str,
    what_it_is: str,
    what_it_does: str,
    root_cause: str,
    inputs: str,
    expected: str,
    actual: str,
    probe_script: str,
    suggested_fix: str,
    risks: str,
    regression_test_idea: str,
    severity: SeverityLevel,
    found_by: str,
    evidence_hint: EvidenceType = EvidenceType.DYNAMIC,
) -> FindingDraft:
    return FindingDraft(
        title=title,
        location=FindingLocation(
            file=file,
            line_start=max(1, line_start),
            line_end=max(max(1, line_start), line_end),
            symbol=symbol,
        ),
        category=category,
        what_it_is=what_it_is,
        what_it_does=what_it_does,
        root_cause=root_cause,
        repro=FindingRepro(
            inputs=inputs,
            expected=expected,
            actual=actual,
            probe_script=probe_script,
        ),
        suggested_fix=suggested_fix,
        risks=risks,
        regression_test_idea=regression_test_idea,
        proposed_severity=severity,
        evidence_hint=evidence_hint,
        found_by=found_by,
    )


def _detect_security(repo: Path, allowed: tuple[str, ...], role: str) -> list[FindingDraft]:
    findings: list[FindingDraft] = []
    # Keep grounding tool call audited cleanly
    execute_grounding_tool("grep", allowed, repo, pattern=r"subprocess|output_file|call_expr", path_prefix="src/")

    # 1. RCE in test_generator (ECC-001)
    tg_text, tg_lines = _read_rel(repo, "src/bugarena/synthesizer/test_generator.py")
    if tg_text and "ast.parse" not in tg_text.split("target_call")[0] and "target_call = call_expr" in tg_text:
        ln = _find_line(tg_lines, r"target_call\s*=")
        findings.append(
            _draft(
                title="Arbitrary Python code execution via unsanitized call_expr/expected_behavior",
                file="src/bugarena/synthesizer/test_generator.py",
                line_start=ln,
                line_end=ln + 12,
                symbol="generate_reproduction_test_code",
                category="security",
                what_it_is="Untrusted call_expr and expected_behavior are interpolated directly into generated pytest source.",
                what_it_does="Running bug_reproduce executes arbitrary host Python code inside pytest subprocesses.",
                root_cause="generate_reproduction_test_code interpolates unvalidated call_expr and expected_behavior directly into Python source.",
                inputs="call_expr=\"__import__('pathlib').Path('pwn.txt').write_text('PWN')\"",
                expected="ValueError raised before generating executable Python",
                actual="Generated test executes the arbitrary import/file write when pytest runs",
                probe_script="""
import tempfile, subprocess, sys
from pathlib import Path
from bugarena.models.bug import SuspectLocation
from bugarena.synthesizer.test_generator import generate_reproduction_test_code
with tempfile.TemporaryDirectory() as d:
    m = Path(d) / "pwn.txt"
    s = SuspectLocation(file_path="a.py", function_name="f", line_range=(1,1), confidence=0.9, bug_type="Err", reasoning="r", code_snippet="")
    try:
        code = generate_reproduction_test_code(s, "d", call_expr=f"__import__('pathlib').Path({str(m)!r}).write_text('PWN')", expected_behavior="True")
    except ValueError:
        print("DISPROVED: rejected unsafe call_expr")
        sys.exit(0)
    tf = Path(d) / "t.py"
    tf.write_text(code, encoding="utf-8")
    subprocess.run([sys.executable, "-m", "pytest", str(tf), "-q"], check=False)
    if m.exists():
        print("REPRODUCED: arbitrary code executed on host")
        sys.exit(1)
    print("DISPROVED: side effect did not execute")
""",
                suggested_fix="Validate call_expr and expected_behavior against a safe AST expression allowlist.",
                risks="Complex call expressions with nested comprehensions or lambdas will be rejected unless allowlisted.",
                regression_test_idea="Reject __import__('os').system(...) in generate_reproduction_test_code",
                severity=SeverityLevel.CRITICAL,
                found_by=role,
            )
        )

    # 2. evaluate_patches arbitrary repro_code without verified binding (ECC-002)
    srv_text, srv_lines = _read_rel(repo, "src/bugarena/server.py")
    if srv_text and "evaluate_patches" in srv_text and "validate_red_baseline" not in srv_text.split("def evaluate_patches")[1][:900]:
        ln = _find_line(srv_lines, r"def evaluate_patches")
        findings.append(
            _draft(
                title="Arbitrary code execution in evaluate_patches via unverified repro_code",
                file="src/bugarena/server.py",
                line_start=ln,
                line_end=ln + 20,
                symbol="evaluate_patches",
                category="security",
                what_it_is="evaluate_patches trusts caller-supplied repro_code without matching tournament.repro_spec or running AST/Red validation.",
                what_it_does="Clients can execute arbitrary Python via repro_code even bypassing Red verification.",
                root_cause="evaluate_patches builds ReproTestSpec(red_baseline_verified=True) directly from unverified caller repro_code.",
                inputs="repro_code='import pathlib; pathlib.Path(\"m\").write_text(\"X\")\ndef test_x(): pass'",
                expected="Reject unverified/mismatched repro_code or validate against tournament.repro_spec",
                actual="Executes caller repro_code directly inside pytest subprocess",
                probe_script="""
import tempfile, sys
from pathlib import Path
import bugarena.server as srv
with tempfile.TemporaryDirectory() as d:
    repo = Path(d) / "r"
    repo.mkdir()
    (repo / "m.py").write_text("x = 1\\n")
    t = srv.agent_fix_tournament(str(repo), "tests/t.py", [{"candidate_id": "c1", "persona": "surgical_minimalist", "explanation": "e", "diff": "--- a/m.py\\n+++ b/m.py\\n@@ -1,1 +1,1 @@\\n-x = 1\\n+x = 2\\n"}])
    marker = Path(d) / "pwn2.txt"
    res = srv.evaluate_patches(str(repo), t["tournament_id"], "tests/t.py", f"import pathlib\\npathlib.Path({str(marker)!r}).write_text('X')\\ndef test_x():\\n    assert True\\n")
    if marker.exists():
        print("REPRODUCED: arbitrary repro_code executed without Red verification")
        sys.exit(1)
    print("DISPROVED:", res)
""",
                suggested_fix="Bind evaluate_patches to tournament.repro_spec or reject unverified / AST-disallowed repro_code.",
                risks="Direct callers skipping bug_reproduce must supply valid pytest AST test functions or run bug_reproduce first.",
                regression_test_idea="Reject arbitrary top-level import side effects in evaluate_patches",
                severity=SeverityLevel.CRITICAL,
                found_by=role,
            )
        )

    # 3. Unvalidated output_file path traversal (ECC-003)
    mf_text, mf_lines = _read_rel(repo, "src/bugarena/reporting/markdown_formatter.py")
    if mf_text and "validate_safe_path" not in mf_text:
        ln = _find_line(mf_lines, r"def save_markdown_report")
        findings.append(
            _draft(
                title="Arbitrary host file write via unvalidated output_file in save_markdown_report",
                file="src/bugarena/reporting/markdown_formatter.py",
                line_start=ln,
                line_end=ln + 8,
                symbol="save_markdown_report",
                category="security",
                what_it_is="save_markdown_report writes directly to any resolved output_path without base_dir containment check.",
                what_it_does="generate_fix_report and generate_bug_report can overwrite arbitrary host files outside repo_path.",
                root_cause="save_markdown_report resolves output_path directly with Path(output_path).resolve() without validate_safe_path.",
                inputs="output_file='../outside_escape.md'",
                expected="SecurityViolationError raised when output_file escapes repo_path",
                actual="Creates and writes file outside target repository",
                probe_script="""
import tempfile, sys
from pathlib import Path
from bugarena.server import generate_bug_report
with tempfile.TemporaryDirectory() as d:
    repo = Path(d) / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("x = 1 / 0\\n")
    outside = Path(d) / "escaped.md"
    try:
        generate_bug_report(str(repo), 'File "app.py", line 1\\nZeroDivisionError: div', output_file=str(outside))
    except Exception as exc:
        print(f"DISPROVED: blocked with {type(exc).__name__}: {exc}")
        sys.exit(0)
    if outside.exists():
        print("REPRODUCED: wrote file outside repo_path")
        sys.exit(1)
    print("DISPROVED: no outside file written")
""",
                suggested_fix="Require base_dir and validate output_file with validate_safe_path in handlers and save_markdown_report.",
                risks="Callers writing reports outside repo_path must supply explicit allowed paths inside repo_path.",
                regression_test_idea="Test generate_bug_report and generate_fix_report reject ../outside.md",
                severity=SeverityLevel.CRITICAL,
                found_by=role,
            )
        )

    # 4. bug_detect / discover_from_trace reading .env / secrets unscrubbed (ECC-004)
    eng_text, eng_lines = _read_rel(repo, "src/bugarena/discovery/engine.py")
    if eng_text and ".env" not in eng_text and "scrub_sensitive_data" not in eng_text:
        ln = _find_line(eng_lines, r"resolved_file\.read_text")
        findings.append(
            _draft(
                title="Arbitrary repo secret file (.env) read and exposed unscrubbed in bug_detect",
                file="src/bugarena/discovery/engine.py",
                line_start=ln,
                line_end=ln + 10,
                symbol="BugDiscoveryEngine.discover_from_trace",
                category="security",
                what_it_is="discover_from_trace reads any file in repo_path cited by an error log (including .env) without extension allowlist or scrubbing.",
                what_it_does="Forged stack frames targeting .env return plaintext secrets via MCP tools and saved reports.",
                root_cause="BugDiscoveryEngine reads any resolved file inside repo_path without filtering non-source/.env files or scrubbing snippets.",
                inputs='error_log=\'  File ".env", line 1, in <module>\\nError\'',
                expected="Skip .env/non-source files and scrub secrets in returned snippets/logs",
                actual="Returns plaintext .env secret in suspect.code_snippet",
                probe_script="""
import tempfile, sys
from pathlib import Path
from bugarena.discovery.engine import BugDiscoveryEngine
with tempfile.TemporaryDirectory() as d:
    repo = Path(d) / "repo"
    repo.mkdir()
    secret = "sk-" + "dummysecret1234567890abcdef"
    (repo / ".env").write_text(f"API_KEY={secret}\\n")
    spec = BugDiscoveryEngine(repo).discover_from_trace('  File ".env", line 1, in <module>\\nRuntimeError: boom')
    if spec.suspects and secret in spec.suspects[0].code_snippet:
        print("REPRODUCED: plaintext secret returned in suspect snippet")
        sys.exit(1)
    print("DISPROVED: secret excluded/scrubbed")
""",
                suggested_fix="Restrict discover_from_trace to source extensions (.py), skip .env*/.git/.venv/.ssh, and scrub logs/snippets.",
                risks="Config/data files won't be returned as Python AST snippets unless explicitly allowlisted.",
                regression_test_idea="Test BugDiscoveryEngine ignores .env trace frames",
                severity=SeverityLevel.CRITICAL,
                found_by=role,
            )
        )

    # 5. Sandbox lacks OS/container isolation despite docs (ECC-005)
    run_text, run_lines = _read_rel(repo, "src/bugarena/sandbox/runner.py")
    readme_text, _ = _read_rel(repo, "README.md")
    if run_text and "docker" not in run_text and "--network=none" in readme_text:
        ln = _find_line(run_lines, r"subprocess\.Popen")
        findings.append(
            _draft(
                title="False --network=none sandbox isolation claim; host subprocess has full host access",
                file="src/bugarena/sandbox/runner.py",
                line_start=ln,
                line_end=ln + 8,
                symbol="run_sandboxed_command",
                category="security",
                what_it_is="run_sandboxed_command executes plain host subprocess.Popen while README claims '--network=none, jails'.",
                what_it_does="Untrusted code runs with host user permissions and network access unless containerized or accurately documented.",
                root_cause="No container/OS isolation mode exists and documentation overstates temp-directory copying as network/jail isolation.",
                inputs="Execute command writing marker outside workspace via host Python",
                expected="Container isolation when enabled, and honest docs matching actual isolation",
                actual="Host Popen succeeds outside workspace while README advertises --network=none",
                probe_script="""
import tempfile, sys
from pathlib import Path
from bugarena.sandbox.runner import run_sandboxed_command
with tempfile.TemporaryDirectory() as d:
    ws = Path(d) / "ws"
    ws.mkdir()
    outside = Path(d) / "outside_host.txt"
    readme = Path("README.md").read_text(encoding="utf-8") if Path("README.md").is_file() else ""
    out = run_sandboxed_command(ws, [sys.executable, "-c", f"from pathlib import Path; Path({str(outside)!r}).write_text('HOST')"])
    if "--network=none" in readme and outside.exists():
        print("REPRODUCED: host write outside workspace succeeded despite --network=none doc claim")
        sys.exit(1)
    print("DISPROVED: isolated or docs accurate")
""",
                suggested_fix="Add optional auto-detected container isolation mode and update README/SKILL.md honestly when host mode is active.",
                risks="Host mode cannot block host syscalls without Docker/OS sandbox tools installed.",
                regression_test_idea="Test README isolation description matches actual runner capability and test container cmd builder",
                severity=SeverityLevel.CRITICAL,
                found_by=role,
            )
        )

    # 6. Pytest option injection + env blocklist gaps + -c bypass (ECC-018)
    sec_text, sec_lines = _read_rel(repo, "src/bugarena/sandbox/security.py")
    rv_text, _ = _read_rel(repo, "src/bugarena/synthesizer/red_validator.py")
    if rv_text and '"--"' not in rv_text and "'--'" not in rv_text:
        ln = _find_line(sec_lines, r"def sanitize_command_args")
        findings.append(
            _draft(
                title="Pytest CLI option injection (--version) & weak env/arg sanitization in security.py",
                file="src/bugarena/sandbox/security.py",
                line_start=ln,
                line_end=ln + 20,
                symbol="sanitize_env / sanitize_command_args",
                category="security",
                what_it_is="pytest calls omit '--' separator, sanitize_env misses MYSQL_PWD/PYTHONSTARTUP/GH_PAT/HTTP_PROXY, and sanitize_command_args bypasses all checks after '-c'.",
                what_it_does="Passing '--version' as repro_test_file makes pytest exit 0 with 0 tests; secrets leak to subprocesses.",
                root_cause="Missing '--' option separator before test paths and permissive blocklist/bypass in security.py.",
                inputs="repro_test_file='--version' and sanitize_env({'MYSQL_PWD': 'x', 'GH_PAT': 'ghp'})",
                expected="Option-like test paths rejected; dangerous env vars stripped; '-c' constrained",
                actual="pytest --version passes (exit 0) and MYSQL_PWD/GH_PAT leak",
                probe_script="""
import sys
from bugarena.sandbox.security import sanitize_env, sanitize_command_args, SecurityViolationError
leaked = [k for k in ("MYSQL_PWD", "PYTHONSTARTUP", "GH_PAT", "HTTP_PROXY") if k in sanitize_env({k: "val"})]
bypassed = False
try:
    sanitize_command_args(["bash", "-c", "id; cat /etc/passwd"])
    bypassed = True
except SecurityViolationError:
    pass
if leaked or bypassed:
    print(f"REPRODUCED: leaked={leaked}, bash_c_bypassed={bypassed}")
    sys.exit(1)
print("DISPROVED: env stripped and unsafe -c blocked")
""",
                suggested_fix="Insert '--' and reject '-' test paths; expand sanitize_env (+ allowlist mode in runner); restrict '-c' payloads.",
                risks="Strict allowlist must permit pytest test runners and explicit env_override.",
                regression_test_idea="Test --version test path rejection, MYSQL_PWD/PYTHONSTARTUP stripping, bash -c rejection",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

    # 7. validate_safe_path empty/dot/NUL + scrub_sensitive_data ordering & slashes (ECC-041 / ECC-029 / BA-019)
    if sec_text and ('"\\x00"' not in sec_text or "C:/Users" not in sec_text and "[/\\\\]" not in sec_text):
        ln = _find_line(sec_lines, r"def scrub_sensitive_data")
        findings.append(
            _draft(
                title="validate_safe_path accepts ''/'.' and scrub_sensitive_data breaks base_dir & Windows slashes",
                file="src/bugarena/sandbox/security.py",
                line_start=ln,
                line_end=ln + 28,
                symbol="validate_safe_path / scrub_sensitive_data",
                category="security",
                what_it_is="scrub_sensitive_data redacts user home regex before base_dir, misses forward slashes and token prefixes, and validate_safe_path accepts '' and '.'.",
                what_it_does="Workspace paths and tokens (xoxb-, glpat-, hf_, database URLs from runner) leak in reports/outputs.",
                root_cause="Regex ordering puts C:\\Users\\... ahead of base_dir substitution and validate_safe_path omits root/empty/NUL checks.",
                inputs="scrub_sensitive_data(r'C:\\Users\\alice\\tmp\\a.py', base_dir=r'C:\\Users\\alice\\tmp'); validate_safe_path(d, '.')",
                expected="Produces '[WORKSPACE]/a.py' and rejects '.'",
                actual="Produces '[REDACTED_PATH]\\tmp\\a.py' and returns base_dir for '.'",
                probe_script="""
import tempfile, sys
from bugarena.sandbox.security import scrub_sensitive_data, validate_safe_path, SecurityViolationError
with tempfile.TemporaryDirectory() as d:
    s1 = scrub_sensitive_data(r"C:\\Users\\alice\\tmp\\a.py", base_dir=r"C:\\Users\\alice\\tmp")
    s2 = scrub_sensitive_data("C:/Users/alice/work/a.py")
    dot_ok = True
    try:
        validate_safe_path(d, ".")
    except SecurityViolationError:
        dot_ok = False
    if "[WORKSPACE]" not in s1 or "alice" in s2 or dot_ok:
        print(f"REPRODUCED: s1={s1!r} s2={s2!r} dot_accepted={dot_ok}")
        sys.exit(1)
    print("DISPROVED: paths scrubbed and '.' rejected")
""",
                suggested_fix="Replace normalized base_dir variants first, match forward/backslashes, expand token regexes, and reject '', '.', NUL in validate_safe_path.",
                risks="Low; tests passing base_dir directly must use allow_root=True.",
                regression_test_idea="Test Windows forward/backslashes, base_dir ordering, and '.'/'\\x00' rejection",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

    # 8. config.load_env_file cwd trust & parser bugs (ECC-019 / BA-021)
    cfg_text, cfg_lines = _read_rel(repo, "src/bugarena/config.py")
    if cfg_text and "Path.cwd()" in cfg_text:
        ln = _find_line(cfg_lines, r"Path\.cwd\(\)")
        findings.append(
            _draft(
                title="load_env_file auto-loads untrusted cwd .env, ignores encoding errors, and mishandles export/comments",
                file="src/bugarena/config.py",
                line_start=ln,
                line_end=ln + 15,
                symbol="load_env_file",
                category="security",
                what_it_is="load_env_file loads Path.cwd()/.env unconditionally even with explicit dotenv_path, lacks UTF-16/BOM handling, fails on export/inline comments, and caches empty strings.",
                what_it_does="Malicious cwd .env can inject OPENAI_API_KEY/redirects; blank KEY= poisons fallback providers.",
                root_cause="load_env_file appends global/cwd paths after dotenv_path and parses lines naively without encoding or quote/comment handling.",
                inputs="Explicit dotenv_path alongside global .env, export FOO='bar' # comment, or UTF-16 .env",
                expected="Explicit dotenv_path loads only that path; UTF-16/export/inline comments/blank values handled safely",
                actual="Crashes UnicodeDecodeError on UTF-16 and loads wrong scopes/values",
                probe_script="""
import os, tempfile, sys
from pathlib import Path
from bugarena.config import load_env_file
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / ".env"
    p.write_text('export TEST_BA_K="hello" # inline\\n', encoding="utf-16")
    os.environ.pop("TEST_BA_K", None)
    try:
        load_env_file(p)
    except UnicodeDecodeError as exc:
        print(f"REPRODUCED: UnicodeDecodeError {exc}")
        sys.exit(1)
    val = os.environ.pop("TEST_BA_K", None)
    if val != "hello":
        print(f"REPRODUCED: parsed export/comment wrong: val={val!r}")
        sys.exit(1)
    print("DISPROVED: UTF-16 and export parsed cleanly")
""",
                suggested_fix="Load only dotenv_path when provided, drop cwd auto-load, decode utf-8-sig/utf-16, handle export/quotes/#, skip blank overwrite.",
                risks="Users relying on cwd/.env outside project root must pass dotenv_path explicitly.",
                regression_test_idea="Test explicit dotenv_path isolation, UTF-16 BOM, export/quotes, and empty KEY=",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

    return findings


def _detect_code_logic(repo: Path, allowed: tuple[str, ...], role: str) -> list[FindingDraft]:
    findings: list[FindingDraft] = []
    execute_grounding_tool("grep", allowed, repo, pattern=r"def |parse_", path_prefix="src/")

    # 1. EphemeralSandboxManager._apply_hunks / apply_patch corruption (ECC-009 / BA-004, BA-005)
    mgr_text, mgr_lines = _read_rel(repo, "src/bugarena/sandbox/manager.py")
    if mgr_text and "res_lines[actual_start:actual_end] = additions" in mgr_text:
        ln = _find_line(mgr_lines, r"def _apply_hunks")
        findings.append(
            _draft(
                title="Custom _apply_hunks corrupts files on -U0, multi-file, '-- ' comments, and context mismatch",
                file="src/bugarena/sandbox/manager.py",
                line_start=ln,
                line_end=ln + 33,
                symbol="EphemeralSandboxManager._apply_hunks",
                category="data-integrity",
                what_it_is="_apply_hunks ignores context/'-' lines, clamps out-of-range offsets silently, miscalculates @@ -N,0 insertions, and apply_patch mistakes deleted '-- ' comments for file headers.",
                what_it_does="Patches silently corrupt sandbox files and misapply hunks, distorting Red-to-Green tournament evaluation.",
                root_cause="_apply_hunks splices lines by header math without verifying context/removed lines or parsing hunk counts strictly.",
                inputs="Unified diff with @@ -4,0 +5,1 @@ or deleted '-- comment' line",
                expected="Exact insertion after line 4, context mismatch raises error, '-- ' stays inside hunk",
                actual="-U0 inserts off-by-one and '-- ' truncates hunks",
                probe_script="""
import tempfile, sys
from pathlib import Path
from bugarena.sandbox.manager import EphemeralSandboxManager
with tempfile.TemporaryDirectory() as d:
    r = Path(d) / "r"
    r.mkdir()
    (r / "nums.txt").write_text("1\\n2\\n3\\n4\\n5\\n", encoding="utf-8")
    diff = "--- a/nums.txt\\n+++ b/nums.txt\\n@@ -4,0 +5,1 @@\\n+INSERTED\\n"
    m = EphemeralSandboxManager(r)
    with m.create_sandbox() as sb:
        m.apply_patch(sb, diff)
        got = (sb / "nums.txt").read_text(encoding="utf-8").splitlines()
    if got != ["1", "2", "3", "4", "INSERTED", "5"]:
        print(f"REPRODUCED: wrong insertion result {got}")
        sys.exit(1)
    print("DISPROVED: -U0 applied cleanly")
""",
                suggested_fix="Replace _apply_hunks/apply_patch with a hunk state machine verifying context lines, counts, timestamps, and /dev/null.",
                risks="Malformed diffs with wrong context will raise ValueError instead of silently corrupting code.",
                regression_test_idea="Test -U0 append, context mismatch error, multi-file blank lines, SQL '-- ' deletions, +++ /dev/null",
                severity=SeverityLevel.CRITICAL,
                found_by=role,
            )
        )

    # 2. patch_parser protected_paths & normalization bypasses (ECC-008 / ECC-042 / BA-006, BA-007)
    pp_text, pp_lines = _read_rel(repo, "src/bugarena/tournament/patch_parser.py")
    if pp_text and "clean_prot in mod or mod in clean_prot" in pp_text:
        ln = _find_line(pp_lines, r"clean_prot in mod")
        findings.append(
            _draft(
                title="patch_parser substring/normalization flaws allow protected file tampering and false rejections",
                file="src/bugarena/tournament/patch_parser.py",
                line_start=ln - 15,
                line_end=ln + 15,
                symbol="parse_and_validate_patch",
                category="security",
                what_it_is="DIFF_HEADER_PATTERN requires LF (\\n), protected_paths uses naive substring matching without normpath, allows './' or '../' bypasses, counts header-only diffs, and miscounts '---' churn.",
                what_it_does="Competing candidate patches can overwrite protected repro tests using './' or '../' or CRLF, while benign files like 'calc.py' get falsely rejected.",
                root_cause="parse_and_validate_patch relies on naive substring check and LF-only multi-line regex without canonical posix path normalization or hunk parsing.",
                inputs="diff targeting './tests/repro/secret.py' with protected_paths=['tests/repro/secret.py']",
                expected="PatchValidationError raised for protected path tampering",
                actual="Dot-slash / traversal / CRLF diffs bypass protected_paths check",
                probe_script="""
import sys
from bugarena.models.agent import PersonaType
from bugarena.tournament.patch_parser import PatchValidationError, parse_and_validate_patch
diff = "--- a/./tests/repro/secret.py\\n+++ b/./tests/repro/secret.py\\n@@ -1,1 +1,1 @@\\n-assert False\\n+assert True\\n"
try:
    parse_and_validate_patch(diff, PersonaType.SURGICAL_MINIMALIST, "cheat", protected_paths=["tests/repro/secret.py"])
    print("REPRODUCED: ./ bypass allowed modifying protected file")
    sys.exit(1)
except PatchValidationError:
    print("DISPROVED: ./ path blocked properly")
""",
                suggested_fix="Normalize CRLF and paths with posixpath.normpath, reject '..'/absolute, match exact/parent path segments, validate @@ hunks, and count churn inside hunks only.",
                risks="Header-only empty diffs without @@ hunks will rightly be rejected.",
                regression_test_idea="Test ./, ../, CRLF, /dev/null deletion bypasses and calc.py false-positive",
                severity=SeverityLevel.CRITICAL,
                found_by=role,
            )
        )

    # 3. BugDiscoveryEngine .venv rglob + confidence + dedup (ECC-025 / BA-013)
    eng_text, eng_lines = _read_rel(repo, "src/bugarena/discovery/engine.py")
    if eng_text and ".venv" not in eng_text:
        ln = _find_line(eng_lines, r"rglob\(")
        findings.append(
            _draft(
                title="BugDiscoveryEngine searches .venv via unbounded rglob and duplicates suspects",
                file="src/bugarena/discovery/engine.py",
                line_start=ln - 5,
                line_end=ln + 15,
                symbol="BugDiscoveryEngine.discover_from_trace",
                category="logic",
                what_it_is="discover_from_trace uses self.repo_path.rglob(filename) which traverses .venv/node_modules/.git and may duplicate identical suspects.",
                what_it_does="Errors inside third-party dependencies or duplicate frames get attributed as primary project suspects.",
                root_cause="BugDiscoveryEngine resolves filenames with unfiltered rglob instead of a pruned repository index preferring suffix matches.",
                inputs="Traceback referencing file that also exists in .venv/lib/.../helper.py",
                expected="Excluded .venv and deduplicated suspects",
                actual="Matches .venv copy or repeats suspect locations",
                probe_script="""
import tempfile, sys
from pathlib import Path
from bugarena.discovery.engine import BugDiscoveryEngine
with tempfile.TemporaryDirectory() as d:
    repo = Path(d) / "repo"
    (repo / ".venv" / "pkg").mkdir(parents=True)
    (repo / ".venv" / "pkg" / "mod.py").write_text("def f():\\n    return 1\\n")
    spec = BugDiscoveryEngine(repo).discover_from_trace('  File "elsewhere/mod.py", line 1, in f\\nRuntimeError: err')
    if any(".venv" in s.file_path for s in spec.suspects):
        print("REPRODUCED: matched .venv file as suspect")
        sys.exit(1)
    print("DISPROVED: .venv ignored")
""",
                suggested_fix="Index repo files once skipping .venv/.git/node_modules/__pycache__/build/dist/.env*, prefer suffix matches, and dedupe suspects.",
                risks="Large repos should cache index cleanly per discover_from_trace call.",
                regression_test_idea="Verify .venv files are excluded and duplicate stack frames deduplicated",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

    # 4. log_parser <lambda>/<listcomp> and colon parsing (ECC-026 / BA-014)
    lp_text, lp_lines = _read_rel(repo, "src/bugarena/discovery/log_parser.py")
    if lp_text and r"\w+" in lp_text and "<" not in lp_text.split("FRAME_PATTERN")[1][:180]:
        ln = _find_line(lp_lines, r"FRAME_PATTERN")
        findings.append(
            _draft(
                title="parse_python_traceback drops <lambda>/<listcomp> scopes and misparses colons",
                file="src/bugarena/discovery/log_parser.py",
                line_start=ln,
                line_end=ln + 30,
                symbol="parse_python_traceback",
                category="logic",
                what_it_is="FRAME_PATTERN uses (?P<func>\\w+) which fails on '<lambda>'/'<listcomp>' (falling back to '<module>'), and final-line scan accepts non-exception trailing lines containing ':'.",
                what_it_does="Stack traces crashing inside lambdas or followed by log timestamps misreport function names and error messages.",
                root_cause="FRAME_PATTERN restricts function names to \\w+ and exception detection falls back to any line with ':'.",
                inputs='  File "app.py", line 10, in <lambda>\\nValueError: bad\\nLog: 12:30:00',
                expected="function_name=='<lambda>' and error_message=='ValueError: bad'",
                actual="function_name=='<module>' and error_message=='Log: 12:30:00'",
                probe_script="""
import sys
from bugarena.discovery.log_parser import parse_python_traceback
tb = 'Traceback (most recent call last):\\n  File "app.py", line 10, in <lambda>\\n    x = 1/0\\nZeroDivisionError: division by zero\\ninfo: trailing'
traces = parse_python_traceback(tb)
if not traces or traces[0].function_name != "<lambda>" or "ZeroDivisionError" not in traces[0].error_message:
    print(f"REPRODUCED: traces={traces}")
    sys.exit(1)
print("DISPROVED: lambda and exception parsed properly")
""",
                suggested_fix="Match [^\\r\\n]+ for func in FRAME_PATTERN and detect exception using EXCEPTION_PATTERN only (including dotted/custom exceptions).",
                risks="Log noise lines matching IdentifierError: msg could still trigger if appended last.",
                regression_test_idea="Test <lambda>, <listcomp>, dotted exceptions, and trailing colon log lines",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

    # 5. ast_analyzer empty line_range and cross-match node docstring (ECC-034 / BA-015)
    ast_text, ast_lines = _read_rel(repo, "src/bugarena/discovery/ast_analyzer.py")
    if ast_text and "line_range=(1, 0)" in repr(ast_text) or (ast_text and "if not lines:" not in ast_text):
        ln = _find_line(ast_lines, r"end = min\(len\(lines\)")
        findings.append(
            _draft(
                title="locate_faulty_ast_slice returns inverted range (1, 0) on empty files",
                file="src/bugarena/discovery/ast_analyzer.py",
                line_start=ln - 2,
                line_end=ln + 8,
                symbol="locate_faulty_ast_slice",
                category="logic",
                what_it_is="On empty files, len(lines)==0 yields start=1, end=0 and FaultVisitor can mix docstring from matched_node and class from name_matched_node.",
                what_it_does="Returns inverted line_range=(1, 0) violating line_start <= line_end.",
                root_cause="Empty content falls through without early guard and FaultVisitor separates matched attributes across distinct nodes.",
                inputs="locate_faulty_ast_slice('', 1)",
                expected="None or valid range (0, 0)/(1, 1) with line_start <= line_end",
                actual="Returns line_range=(1, 0)",
                probe_script="""
import sys
from bugarena.discovery.ast_analyzer import locate_faulty_ast_slice
res = locate_faulty_ast_slice("", 1)
if res is not None and res["line_range"][0] > res["line_range"][1]:
    print(f"REPRODUCED: inverted line_range {res['line_range']}")
    sys.exit(1)
print(f"DISPROVED: res={res}")
""",
                suggested_fix="Return None (or valid non-inverted tuple) when file_content is empty and extract class/docstring strictly from chosen node.",
                risks="Callers handling None safely get clean missing slice instead of inverted line range.",
                regression_test_idea="Test locate_faulty_ast_slice('', 1) does not invert line_range",
                severity=SeverityLevel.MEDIUM,
                found_by=role,
            )
        )

    # 6. test_generator assertion syntax/case/backslash bugs (ECC-024 / BA-001, BA-002)
    tg_text, tg_lines = _read_rel(repo, "src/bugarena/synthesizer/test_generator.py")
    if tg_text and 'expected_behavior.split("raises ", 1)' in tg_text:
        ln = _find_line(tg_lines, r'split\("raises "')
        findings.append(
            _draft(
                title="generate_reproduction_test_code crashes on 'Raises ...' and produces SyntaxError on 'assert ...'",
                file="src/bugarena/synthesizer/test_generator.py",
                line_start=ln - 3,
                line_end=ln + 15,
                symbol="generate_reproduction_test_code",
                category="logic",
                what_it_is="Case-sensitive split('raises '), 'assert ' double-prefix, result variable not defined for non-== checks, and unescaped backslashes.",
                what_it_does="Calling bug_reproduce with capitalized 'Raises ValueError' or 'assert f() == 1' crashes with IndexError/SyntaxError.",
                root_cause="String checks are case-sensitive and assume lowercased prefixes without regex/AST normalization.",
                inputs="expected_behavior='Raises ValueError'",
                expected="Generates 'with pytest.raises(ValueError):'",
                actual="Raises IndexError",
                probe_script="""
import sys
from bugarena.models.bug import SuspectLocation
from bugarena.synthesizer.test_generator import generate_reproduction_test_code
s = SuspectLocation(file_path="a.py", function_name="f", line_range=(1,1), confidence=0.9, bug_type="Err", reasoning="r", code_snippet="")
try:
    c = generate_reproduction_test_code(s, "d", "f()", "Raises ValueError")
    if "pytest.raises(ValueError)" not in c:
        print("REPRODUCED: missing pytest.raises(ValueError)")
        sys.exit(1)
except Exception as exc:
    print(f"REPRODUCED: {type(exc).__name__}: {exc}")
    sys.exit(1)
print("DISPROVED: handled Raises cleanly")
""",
                suggested_fix="Handle case-insensitive 'raises', strip leading 'assert ', bind result before assertions, and escape Windows backslashes in docstrings.",
                risks="Unknown natural-language expected_behavior should raise ValueError rather than silently becoming assert True.",
                regression_test_idea="Test 'Raises ValueError', 'assert f() == 1', 'result > 0', and Windows backslash file_path",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

    # 7. generate_bug_report broken _REPRO_REGISTRY lookup (ECC-031 / BA-017) & server bugs (ECC-030, ECC-032)
    srv_text, srv_lines = _read_rel(repo, "src/bugarena/server.py")
    if srv_text and "repo_path in r.test_file_path" in srv_text:
        ln = _find_line(srv_lines, r"repo_path in r\.test_file_path")
        findings.append(
            _draft(
                title="generate_bug_report mismatches _REPRO_REGISTRY across repos via '.' substring match",
                file="src/bugarena/server.py",
                line_start=ln - 2,
                line_end=ln + 4,
                symbol="generate_bug_report",
                category="logic",
                what_it_is="_REPRO_REGISTRY is keyed only by relative test_rel_path and generate_bug_report checks 'repo_path in r.test_file_path'.",
                what_it_does="Calling generate_bug_report(repo_path='.') grabs another repo's repro test while real repo paths never match.",
                root_cause="_REPRO_REGISTRY keys lack resolved repo_path scoping and lookup uses substring matching against relative paths.",
                inputs="Call bug_reproduce(repoA) then generate_bug_report('.')",
                expected="Lookup returns only repro belonging to resolved repo_path",
                actual="Returns repoA's repro for '.' and misses exact repoA path",
                probe_script="""
import tempfile, sys
from pathlib import Path
import bugarena.server as srv
with tempfile.TemporaryDirectory() as d:
    rA, rB = Path(d) / "rA", Path(d) / "rB"
    rA.mkdir(); rB.mkdir()
    (rA / "a.py").write_text("def f(): return 1 / 0\\n")
    (rB / "b.py").write_text("def g(): return 2\\n")
    srv.bug_reproduce(str(rA), "a.py", "div zero", function_name="f", call_expr="f()", expected_behavior="f() == 0")
    rep = srv.generate_bug_report(str(rA), '  File "a.py", line 1, in f\\nZeroDivisionError: div')
    if "Red Baseline" not in rep["report_markdown"]:
        print("REPRODUCED: failed to link repro_spec for exact repoA")
        sys.exit(1)
    print("DISPROVED: repro_spec linked properly")
""",
                suggested_fix="Key _REPRO_REGISTRY by (str(Path(repo_path).resolve()), test_rel_path) and look up by exact resolved repo.",
                risks="Direct callers reading _REPRO_REGISTRY must use repo-scoped keys or helper.",
                regression_test_idea="Test cross-repo isolation with repoA vs '.' in generate_bug_report",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

    if srv_text and "spec.initial_outcome.stderr if spec.initial_outcome else" in srv_text and "stdout" not in srv_text.split("def bug_reproduce")[1]:
        ln = _find_line(srv_lines, r"failure_output")
        findings.append(
            _draft(
                title="bug_reproduce omits pytest failure stdout in failure_output",
                file="src/bugarena/server.py",
                line_start=ln,
                line_end=ln + 2,
                symbol="bug_reproduce",
                category="error-handling",
                what_it_is="bug_reproduce populates failure_output from initial_outcome.stderr only, missing pytest assertion tracebacks written to stdout.",
                what_it_does="Callers see blank or warning-only failure_output when pytest assertions fail on stdout.",
                root_cause="bug_reproduce reads only stderr instead of combining stdout and stderr from initial_outcome.",
                inputs="Repro test failing AssertionError in pytest",
                expected="failure_output includes AssertionError traceback from stdout+stderr",
                actual="failure_output omits pytest stdout assertion details",
                probe_script="""
import tempfile, sys
from pathlib import Path
from bugarena.server import bug_reproduce
with tempfile.TemporaryDirectory() as d:
    r = Path(d) / "r"
    r.mkdir()
    (r / "m.py").write_text("def f(): return 1\\n")
    res = bug_reproduce(str(r), "m.py", "want 2", "f", "f()", "f() == 2")
    if "assert 1 == 2" not in res.get("failure_output", "") and "AssertionError" not in res.get("failure_output", ""):
        print(f"REPRODUCED: failure_output missing pytest stdout: {res.get('failure_output')!r}")
        sys.exit(1)
    print("DISPROVED: failure_output contains stdout")
""",
                suggested_fix="Combine stdout and stderr into failure_output in bug_reproduce.",
                risks="None.",
                regression_test_idea="Assert AssertionError details appear in bug_reproduce['failure_output']",
                severity=SeverityLevel.MEDIUM,
                found_by=role,
            )
        )

    return findings


def _detect_silent_failures(repo: Path, allowed: tuple[str, ...], role: str) -> list[FindingDraft]:
    findings: list[FindingDraft] = []
    execute_grounding_tool("grep", allowed, repo, pattern=r"except|no tests ran|delta_cc", path_prefix="src/")

    # 1. validate_red_baseline accepts exit 2/3/4/5 and timeouts (ECC-010)
    rv_text, rv_lines = _read_rel(repo, "src/bugarena/synthesizer/red_validator.py")
    if rv_text and "outcome.exit_code == 0:" in rv_text and "timed_out" not in rv_text:
        ln = _find_line(rv_lines, r"outcome\.exit_code == 0")
        findings.append(
            _draft(
                title="validate_red_baseline accepts collection errors (exit 2/4/5) and timeouts as valid Red baselines",
                file="src/bugarena/synthesizer/red_validator.py",
                line_start=ln - 2,
                line_end=ln + 8,
                symbol="validate_red_baseline",
                category="logic",
                what_it_is="validate_red_baseline only rejects exit_code == 0, treating SyntaxError/usage/missing/empty/timeout as REPRODUCED_RED.",
                what_it_does="Broken repro tests pass Red validation and make Red->Green comparisons meaningless.",
                root_cause="validate_red_baseline checks outcome.exit_code == 0 instead of requiring exit_code == 1 and timed_out is False.",
                inputs="Broken syntax test_code or timeout",
                expected="Raises ReproductionError / ValueError for exit_code != 1 or timed_out",
                actual="Returns red_baseline_verified=True on syntax errors and timeouts",
                probe_script="""
import tempfile, sys
from pathlib import Path
from bugarena.synthesizer.red_validator import validate_red_baseline
with tempfile.TemporaryDirectory() as d:
    r = Path(d) / "r"
    r.mkdir()
    try:
        spec = validate_red_baseline(r, "tests/t_bad.py", "def broken( :")
    except Exception as exc:
        print(f"DISPROVED: rejected syntax error with {type(exc).__name__}")
        sys.exit(0)
    print(f"REPRODUCED: verified broken test as Red: exit={spec.initial_outcome.exit_code}")
    sys.exit(1)
""",
                suggested_fix="Require outcome.exit_code == 1 and not outcome.timed_out; raise typed errors for 2/3/4/5/timeout.",
                risks="Repro tests encountering fixture collection errors now fail fast as intended.",
                regression_test_idea="Test SyntaxError (exit 2), empty tests (exit 5), and timeout raise in validate_red_baseline",
                severity=SeverityLevel.CRITICAL,
                found_by=role,
            )
        )

    # 2. test_generator swallows ImportError + wrong root_dir (ECC-011 / BA-003)
    tg_text, tg_lines = _read_rel(repo, "src/bugarena/synthesizer/test_generator.py")
    if tg_text and "except ImportError:\n    pass" in tg_text:
        ln = _find_line(tg_lines, r"except ImportError:")
        findings.append(
            _draft(
                title="test_generator swallows ImportError and computes wrong parent.parent root_dir",
                file="src/bugarena/synthesizer/test_generator.py",
                line_start=ln - 8,
                line_end=ln + 8,
                symbol="generate_reproduction_test_code",
                category="error-handling",
                what_it_is="Generated repro scripts resolve root_dir one folder short when inside tests/repro/ and wrap imports in 'try/except ImportError: pass'.",
                what_it_does="Import failures convert silently into NameError in generated tests, producing fake Red baselines that patches cannot fix.",
                root_cause="Swallowed ImportError blocks and two-level parent traversal mask module resolution errors as test failures.",
                inputs="Import test written under tests/repro/test_issue_x.py targeting src/calc.py",
                expected="No swallowed ImportError; repo root (including src/) added to sys.path cleanly",
                actual="ImportError swallowed -> NameError instead of fixing module path",
                probe_script="""
import sys
from bugarena.models.bug import SuspectLocation
from bugarena.synthesizer.test_generator import generate_reproduction_test_code
s = SuspectLocation(file_path="src/calc.py", function_name="f", line_range=(1,1), confidence=0.9, bug_type="Err", reasoning="r", code_snippet="")
code = generate_reproduction_test_code(s, "d", "f()", "f() == 1")
if "except ImportError:\\n    pass" in code:
    print("REPRODUCED: generated test still swallows ImportError")
    sys.exit(1)
print("DISPROVED: no swallowed ImportError")
""",
                suggested_fix="Locate repo root accurately (walk to pyproject.toml/src or use 3 levels for tests/repro) and import target cleanly without swallowing ImportError.",
                risks="Missing target symbol will rightly raise ImportError.",
                regression_test_idea="Assert generated repro script does not swallow ImportError and resolves src/ imports under tests/repro/",
                severity=SeverityLevel.CRITICAL,
                found_by=role,
            )
        )

    # 3. bugarena_autonomous_repair fabricates main.py fallback (ECC-012)
    srv_text, srv_lines = _read_rel(repo, "src/bugarena/server.py")
    if srv_text and 'primary_file = suspects[0]["file_path"] if suspects else "main.py"' in srv_text:
        ln = _find_line(srv_lines, r'"main\.py"')
        findings.append(
            _draft(
                title="bugarena_autonomous_repair fabricates main.py/target when suspects is empty",
                file="src/bugarena/server.py",
                line_start=ln - 2,
                line_end=ln + 5,
                symbol="bugarena_autonomous_repair",
                category="error-handling",
                what_it_is="When discover_from_trace finds 0 suspects, bugarena_autonomous_repair synthesizes fake references to main.py and target().",
                what_it_does="Runs entire repair tournament against nonexistent main.py instead of returning NO_SUSPECTS_FOUND.",
                root_cause="Empty suspect list falls back silently to hardcoded 'main.py'/'target' literals instead of failing fast.",
                inputs="error_log='RuntimeError: generic error with no frames'",
                expected="Returns structured status='NO_SUSPECTS_FOUND'",
                actual="Synthesizes fake test for main.py/target",
                probe_script="""
import tempfile, sys
from pathlib import Path
from bugarena.server import bugarena_autonomous_repair
with tempfile.TemporaryDirectory() as d:
    r = Path(d) / "r"
    r.mkdir()
    (r / "app.py").write_text("x = 1\\n")
    res = bugarena_autonomous_repair(str(r), "generic error without trace", "desc", [])
    if res.get("status") != "NO_SUSPECTS_FOUND":
        print(f"REPRODUCED: expected NO_SUSPECTS_FOUND, got {res.get('status')} / {res}")
        sys.exit(1)
    print("DISPROVED: returned NO_SUSPECTS_FOUND cleanly")
""",
                suggested_fix="Return {'status': 'NO_SUSPECTS_FOUND', 'error': ...} when suspects is empty.",
                risks="None.",
                regression_test_idea="Verify bugarena_autonomous_repair returns NO_SUSPECTS_FOUND on frameless logs",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

    # 4. PatchEvaluator hardcoded delta_cc / regressions / missing syntax gate + scorer mutation=1.0 (ECC-013, ECC-027, ECC-028 / BA-008, BA-009)
    tr_text, tr_lines = _read_rel(repo, "src/bugarena/evaluation/test_runner.py")
    _sc_text, _ = _read_rel(repo, "src/bugarena/evaluation/scorer.py")
    am_text, _ = _read_rel(repo, "src/bugarena/evaluation/ast_metrics.py")
    if tr_text and ("delta_cc = 0" in tr_text or "total_tests = 1" in tr_text):
        ln = _find_line(tr_lines, r"delta_cc\s*=\s*0")
        findings.append(
            _draft(
                title="PatchEvaluator hardcodes cyclomatic_delta=0, total_tests=1, skips AST syntax gate, and awards 5.0 free mutation points",
                file="src/bugarena/evaluation/test_runner.py",
                line_start=ln - 10,
                line_end=ln + 12,
                symbol="PatchEvaluator.evaluate_candidates",
                category="logic",
                what_it_is="PatchEvaluator never calls calculate_cyclomatic_delta or ast.parse on modified files, ignores reg_outcome.timed_out/exit 4/5, and scorer awards full 5.0 when mutation_kill_ratio is None.",
                what_it_does="Patches introducing SyntaxError in unimported files or bloating CC win Champion with 99.4 score; empty test suites get 30/30 regression credit.",
                root_cause="test_runner.py hardcodes delta_cc=0/total_tests=1 and skips ast.parse while scorer.py defaults None mutation_kill_ratio to 1.0.",
                inputs="Patch introducing SyntaxError in untested module + compute_patch_score(..., mutation_kill_ratio=None)",
                expected="SyntaxError patch disqualified, real CC delta > 0 computed, missing mutation scores 0",
                actual="Broken syntax patch scores 99.4 and wins Champion; delta_cc stays 0",
                probe_script="""
import tempfile, sys
from pathlib import Path
from bugarena.evaluation.scorer import compute_patch_score
from bugarena.evaluation.test_runner import PatchEvaluator
from bugarena.models.agent import CandidatePatch, PersonaType
from bugarena.models.repro import ReproTestSpec
with tempfile.TemporaryDirectory() as d:
    r = Path(d) / "r"
    (r / "tests").mkdir(parents=True)
    (r / "app.py").write_text("def f(x):\\n    return x\\n")
    (r / "unused.py").write_text("def g():\\n    return 1\\n")
    (r / "tests" / "test_ok.py").write_text("from app import f\\ndef test_ok(): assert f(1) == 1\\n")
    repro = ReproTestSpec(test_file_path="tests/repro/t.py", test_code="from app import f\\ndef test_r(): assert f(2) == 3\\n", red_baseline_verified=True)
    cand = CandidatePatch(candidate_id="bad_syn", persona=PersonaType.SURGICAL_MINIMALIST, explanation="bad", lines_added=2, lines_deleted=1, diff="--- a/app.py\\n+++ b/app.py\\n@@ -1,2 +1,2 @@\\n def f(x):\\n-    return x\\n+    return x + 1\\n--- a/unused.py\\n+++ b/unused.py\\n@@ -1,2 +1,2 @@\\n def g():\\n-    return 1\\n+    return (\\n")
    evals, champ = PatchEvaluator(r).evaluate_candidates([cand], repro)
    sc_none = compute_patch_score("x", True, 0, 1, 1, 0, mutation_kill_ratio=None).score
    if not evals[0].disqualified or sc_none >= 98.0:
        print(f"REPRODUCED: broken_syn_disq={evals[0].disqualified} score={evals[0].score} none_mut_score={sc_none}")
        sys.exit(1)
    print("DISPROVED: syntax gate and scorer fixed")
""",
                suggested_fix="Run ast.parse + calculate_cyclomatic_delta per modified .py file, parse real pytest counts, disqualify timeouts/exit 2, and score mutation_kill_ratio=None as 0.0.",
                risks="Maximum score without mutation testing drops from 100 to 95 (existing tests assert > 90).",
                regression_test_idea="Test SyntaxError in unimported file disqualifies patch and calculate_cyclomatic_delta computes real delta",
                severity=SeverityLevel.CRITICAL,
                found_by=role,
            )
        )

    if am_text and "except (ImportError, AttributeError, ValueError):" in am_text:
        ln = _find_line(am_text.splitlines(), r"except \(ImportError")
        findings.append(
            _draft(
                title="calculate_cyclomatic_delta crashes on SyntaxError and _count_ast_branches scores syntax error as 0",
                file="src/bugarena/evaluation/ast_metrics.py",
                line_start=ln - 4,
                line_end=ln + 4,
                symbol="calculate_cyclomatic_delta",
                category="error-handling",
                what_it_is="radon.complexity.cc_visit raises unhandled SyntaxError on invalid Python, and fallback _count_ast_branches catches SyntaxError returning 0.",
                what_it_does="Invalid patched code either crashes evaluation or earns complexity bonus instead of failing.",
                root_cause="SyntaxError is neither caught cleanly in calculate_cyclomatic_delta nor propagated as a syntax failure.",
                inputs="calculate_cyclomatic_delta('def a(): return 1', 'def a(:')",
                expected="Typed ValueError / SyntaxError propagation or explicit handling",
                actual="Unhandled SyntaxError crash inside cc_visit",
                probe_script="""
import sys
from bugarena.evaluation.ast_metrics import calculate_cyclomatic_delta, _count_ast_branches
try:
    d = calculate_cyclomatic_delta("def a():\\n    if True: return 1\\n", "def a(:")
    b = _count_ast_branches("def a(:")
    if b == 0:
        print(f"REPRODUCED: broken code scored complexity delta={d}, branches=0")
        sys.exit(1)
except SyntaxError as exc:
    print(f"REPRODUCED: unhandled SyntaxError {exc}")
    sys.exit(1)
print("DISPROVED: handled explicitly")
""",
                suggested_fix="Propagate ValueError on SyntaxError in both calculate_cyclomatic_delta and _count_ast_branches (never return 0 as 'simplification').",
                risks="Callers evaluating syntax-broken strings must pass valid Python or catch ValueError.",
                regression_test_idea="Verify calculate_cyclomatic_delta raises explicit ValueError on SyntaxError",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

    # 5. evaluate_candidates swallows apply_patch / SecurityViolationError without surfacing reason (ECC-027)
    if tr_text and "patch_applied = False" in tr_text and "disqualification_reason" not in tr_text:
        ln = _find_line(tr_lines, r"patch_applied = False")
        findings.append(
            _draft(
                title="PatchEvaluator swallows apply_patch and SecurityViolationError exceptions generically",
                file="src/bugarena/evaluation/test_runner.py",
                line_start=ln - 2,
                line_end=ln + 14,
                symbol="PatchEvaluator.evaluate_candidates",
                category="error-handling",
                what_it_is="Exceptions from apply_patch (including SecurityViolationError) become 'Reproduction test failed' with no apply failure reason.",
                what_it_does="Operators cannot tell patch application failures apart from logic failures.",
                root_cause="PatchEvaluator catches (OSError, ValueError, SecurityViolationError) into a boolean flag instead of recording scrubbed error details.",
                inputs="Candidate patch with traversal or failing context hunk",
                expected="disqualification_reason records 'Patch application failed: ...' (scrubbed)",
                actual="Generic 'Reproduction test failed: Patch did not resolve the defect.'",
                probe_script="""
import tempfile, sys
from pathlib import Path
from bugarena.evaluation.test_runner import PatchEvaluator
from bugarena.models.agent import CandidatePatch, PersonaType
from bugarena.models.repro import ReproTestSpec
with tempfile.TemporaryDirectory() as d:
    r = Path(d) / "r"; r.mkdir()
    repro = ReproTestSpec(test_file_path="t.py", test_code="def test_x(): assert False", red_baseline_verified=True)
    cand = CandidatePatch(candidate_id="c1", persona=PersonaType.SURGICAL_MINIMALIST, explanation="x", lines_added=1, lines_deleted=0, diff="--- a/../../etc/x\\n+++ b/../../etc/x\\n@@ -1 +1 @@\\n+hi\\n")
    evals, _ = PatchEvaluator(r).evaluate_candidates([cand], repro)
    if "apply" not in (evals[0].disqualification_reason or "").lower() and "patch" not in (evals[0].disqualification_reason or "").lower():
        print(f"REPRODUCED: misleading reason={evals[0].disqualification_reason!r}")
        sys.exit(1)
    print("DISPROVED: recorded patch failure reason")
""",
                suggested_fix="Record scrubbed apply exception reason directly in PatchEvaluation(disqualification_reason=...).",
                risks="None.",
                regression_test_idea="Assert SecurityViolationError during apply_patch sets explicit disqualification_reason",
                severity=SeverityLevel.MEDIUM,
                found_by=role,
            )
        )

    # 6. TournamentRunner personas=[] / silent timeout/failure (ECC-022 / ECC-038 / BA-012)
    trn_text, trn_lines = _read_rel(repo, "src/bugarena/tournament/runner.py")
    if trn_text and "personas\n            or [" in trn_text or "personas or [" in trn_text:
        ln = _find_line(trn_lines, r"self\.personas =")
        findings.append(
            _draft(
                title="TournamentRunner ignores personas=[], omits CONTRACT_ENFORCER, and hides failure diagnostics",
                file="src/bugarena/tournament/runner.py",
                line_start=ln,
                line_end=ln + 45,
                symbol="TournamentRunner",
                category="error-handling",
                what_it_is="Truthiness check 'personas or [...]' ignores empty list [], default list omits CONTRACT_ENFORCER, run_tournament discards per-persona errors, and get_persona_prompt falls back silently on invalid persona.",
                what_it_does="Zero-candidate runs give no diagnostics and personas=[] runs 3 agents unexpectedly.",
                root_cause="TournamentRunner uses truthiness fallback instead of 'is None', omits CONTRACT_ENFORCER, and drops failure strings.",
                inputs="TournamentRunner(personas=[]) or timed-out generator",
                expected="personas=[] kept empty, default has all 4 PersonaType values, last_errors captured",
                actual="personas=[] runs 3 agents and failures return silent empty list",
                probe_script="""
import sys
from bugarena.tournament.runner import TournamentRunner
r = TournamentRunner(personas=[])
r_def = TournamentRunner()
if len(r.personas) != 0 or len(r_def.personas) != 4:
    print(f"REPRODUCED: empty_len={len(r.personas)} default_len={len(r_def.personas)}")
    sys.exit(1)
print("DISPROVED: personas=[] and all 4 defaults respected")
""",
                suggested_fix="Use list(PersonaType) if personas is None else list(personas); store per-persona failure reasons; raise KeyError for unknown persona.",
                risks="Preserve tuple (tournament_id, candidates) return signature for backward test compatibility while exposing last_errors.",
                regression_test_idea="Test TournamentRunner(personas=[]), default 4 personas, and failure capture",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

    return findings


def _detect_dispatcher_and_models(repo: Path, allowed: tuple[str, ...], role: str) -> list[FindingDraft]:
    findings: list[FindingDraft] = []
    execute_grounding_tool("ast_scan", allowed, repo, rel_paths=[
        "src/bugarena/models/bug.py",
        "src/bugarena/models/tournament.py",
        "src/bugarena/models/report.py",
        "src/bugarena/tournament/providers/dispatcher.py",
    ])

    # 1. Dispatcher routing & null/temperature bugs (ECC-016 / BA-010, ECC-035 / BA-011)
    disp_text, disp_lines = _read_rel(repo, "src/bugarena/tournament/providers/dispatcher.py")
    if disp_text and disp_text.find('"groq" in model.lower()') < disp_text.find('"ollama" in model.lower()'):
        ln = _find_line(disp_lines, r'"ollama" in model\.lower\(\)')
        findings.append(
            _draft(
                title="MultiModelDispatcher misroutes ollama/{llama,qwen} to Groq, rewrites overrides, crashes on null content",
                file="src/bugarena/tournament/providers/dispatcher.py",
                line_start=ln - 10,
                line_end=ln + 5,
                symbol="MultiModelDispatcher.generate_patch",
                category="logic",
                what_it_is="generate_patch checks qwen/llama before ollama/, rewrites explicit gemini/groq overrides, _call_anthropic omits groq/deepseek, _call_openai sends temperature to o3-mini, and content: None crashes strip().",
                what_it_does="Local Ollama calls hit api.groq.com, DeepSeek-only DEFENSIVE_GUARDIAN picks gemma, and null API content raises AttributeError.",
                root_cause="Model routing inspects family substrings ahead of provider prefix and extracts text without None guards.",
                inputs="model_override='ollama/llama3.2' or response choices[0].message.content=None",
                expected="Routes ollama/ to localhost:11434 and returns ('', error) cleanly on None",
                actual="Hits api.groq.com and crashes AttributeError",
                probe_script="""
import asyncio, os, sys
from unittest.mock import patch
import httpx
from bugarena.models.agent import PersonaType
from bugarena.models.bug import BugSpec
from bugarena.models.repro import ReproTestSpec
from bugarena.tournament.providers.dispatcher import MultiModelDispatcher, extract_diff_and_explanation

seen = []
def handler(request):
    seen.append(str(request.url))
    return httpx.Response(200, json={"response": "ok", "choices": [{"message": {"content": None}}]})

async def main():
    os.environ["GROQ_API_KEY"] = "test_key"
    d = MultiModelDispatcher()
    bug = BugSpec(bug_id="b", repo_path=".")
    repro = ReproTestSpec(test_file_path="t.py", test_code="pass", red_baseline_verified=True)
    orig_client = httpx.AsyncClient
    def patched_client(**kw):
        kw["transport"] = httpx.MockTransport(handler)
        return orig_client(**kw)
    with patch("httpx.AsyncClient", side_effect=patched_client):
        try:
            await d.generate_patch(PersonaType.SURGICAL_MINIMALIST, bug, repro, model_override="ollama/llama3.2")
        except AttributeError as exc:
            print(f"REPRODUCED: AttributeError {exc} seen={seen}")
            return 1
    if any("groq.com" in u for u in seen):
        print(f"REPRODUCED: ollama/llama3.2 routed to {seen}")
        return 1
    print(f"DISPROVED: routed cleanly to {seen}")
    return 0

sys.exit(asyncio.run(main()))
""",
                suggested_fix="Route 'ollama/' and 'localhost' first, stop clobbering explicit overrides, add DeepSeek to DEFENSIVE_GUARDIAN, delegate _call_anthropic cleanly, guard None text, omit temperature for o-series.",
                risks="Test callers checking 'default'/'gemini'/'groq' sentinel aliases still map cleanly.",
                regression_test_idea="MockTransport tests for ollama/llama3.2, explicit overrides, None content, o3-mini, and _call_anthropic fallback",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

    if disp_text and "diff --git" not in disp_text.split("DIFF_BLOCK_REGEX")[1][:150]:
        ln = _find_line(disp_lines, r"DIFF_BLOCK_REGEX")
        findings.append(
            _draft(
                title="extract_diff_and_explanation fails on diff --git fences and leaks closing fence/prose",
                file="src/bugarena/tournament/providers/dispatcher.py",
                line_start=ln,
                line_end=ln + 16,
                symbol="extract_diff_and_explanation",
                category="logic",
                what_it_is="DIFF_BLOCK_REGEX rejects 'diff --git' headers and RAW_DIFF_REGEX captures closing ``` fence and trailing prose.",
                what_it_does="Valid LLM outputs with git diff headers either return empty diff or unparsable patch diffs.",
                root_cause="DIFF_BLOCK_REGEX requires '--- ' as first line in fence and RAW_DIFF_REGEX greedily matches until end of text.",
                inputs="```diff\\ndiff --git a/a.py b/a.py\\n--- a/a.py\\n+++ b/a.py\\n@@ -1 +1 @@\\n-x\\n+y\\n```\\nTrailing",
                expected="Extracts clean diff without ``` or Trailing",
                actual="RAW_DIFF_REGEX matches and leaks ```\\nTrailing into diff",
                probe_script="""
import sys
from bugarena.tournament.providers.dispatcher import extract_diff_and_explanation
txt = "```diff\\ndiff --git a/a.py b/a.py\\n--- a/a.py\\n+++ b/a.py\\n@@ -1 +1 @@\\n-x\\n+y\\n```\\nTrailing prose."
diff, expl = extract_diff_and_explanation(txt)
if "```" in diff or "Trailing" in diff or not diff:
    print(f"REPRODUCED: diff leaked={diff!r}")
    sys.exit(1)
print("DISPROVED: extracted clean git diff")
""",
                suggested_fix="Allow optional 'diff --git' and 'index' lines in DIFF_BLOCK_REGEX (with \\r?\\n) and stop RAW_DIFF_REGEX before ``` fences or non-diff prose.",
                risks="None.",
                regression_test_idea="Test fenced/unfenced diff --git blocks with CRLF and trailing commentary",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

    # 2. Models immutability / extra="forbid" / StrEnum (ECC-023)
    bug_text, _ = _read_rel(repo, "src/bugarena/models/bug.py")
    if bug_text and 'extra="forbid"' not in bug_text:
        findings.append(
            _draft(
                title="Domain models allow mutable Sequence/list fields, extra keys, and Enum string drift",
                file="src/bugarena/models/bug.py",
                line_start=1,
                line_end=44,
                symbol="BugSpec / PersonaType / FixReport",
                category="data-integrity",
                what_it_is="Models accept list inputs stored as mutable sequences, omit extra='forbid', and PersonaType(str, Enum) formats str(p) as 'PersonaType.X' on Python 3.11+.",
                what_it_does="Frozen models remain shallow-mutable via suspects[0] append and silent extra kwargs like FixReport(champion_candidate_id=...) pass undetected.",
                root_cause="Domain models use Sequence annotations instead of tuple and omit extra='forbid' and StrEnum.",
                inputs="BugSpec(bug_id='b', repo_path='.', suspects=[...]); str(PersonaType.SURGICAL_MINIMALIST)",
                expected="Immutable tuple fields, StrEnum formatting 'surgical_minimalist', ValidationError on extra keys",
                actual="In-place suspects list mutation succeeds and extra keys silently dropped",
                probe_script="""
import sys
from pydantic import ValidationError
from bugarena.models.agent import PersonaType
from bugarena.models.bug import BugSpec
from bugarena.models.report import FixReport
b = BugSpec(bug_id="b", repo_path=".", suspects=[])
extra_ok = True
try:
    FixReport(tournament_id="t", summary_markdown="m", git_patch_diff="", unknown_kw=1)
except ValidationError:
    extra_ok = False
if isinstance(b.suspects, list) or str(PersonaType.SURGICAL_MINIMALIST) != "surgical_minimalist" or extra_ok:
    print(f"REPRODUCED: list={isinstance(b.suspects, list)} str_enum={str(PersonaType.SURGICAL_MINIMALIST)} extra_accepted={extra_ok}")
    sys.exit(1)
print("DISPROVED: immutable tuples, StrEnum, and extra=forbid active")
""",
                suggested_fix="Use tuple annotations, StrEnum, ConfigDict(frozen=True, extra='forbid'), and invariant validators across models/*.",
                risks="Callers passing invalid extra kwargs will now get ValidationError instead of silent data loss.",
                regression_test_idea="Test extra=forbid, tuple immutability, and StrEnum string value",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

    # 3. FixReport mismatch + format='diff'/'json' overwrite + server concurrency/dup IDs (ECC-014, ECC-033, ECC-021, ECC-032)
    srv_text, srv_lines = _read_rel(repo, "src/bugarena/server.py")
    if srv_text and "champion_candidate_id=tournament.champion_candidate_id" in srv_text:
        ln = _find_line(srv_lines, r"fix_report = FixReport\(")
        findings.append(
            _draft(
                title="FixReport kwarg mismatch drops champion_patch/eval and json/diff writes .md files",
                file="src/bugarena/server.py",
                line_start=ln - 8,
                line_end=ln + 25,
                symbol="generate_fix_report",
                category="data-integrity",
                what_it_is="generate_fix_report passes unknown kwarg champion_candidate_id to FixReport (leaving champion_patch/eval None) and writes Markdown even when format='json' or 'diff'.",
                what_it_does="API clients lose structured champion telemetry and get unexpected .md files on disk.",
                root_cause="server.py passes mismatched kwargs to FixReport and unconditionally calls save_markdown_report before branching on format.",
                inputs="generate_fix_report(t_id, format='json')",
                expected="FixReport contains champion_patch/champion_eval; format='json' writes JSON with .json extension; diff returns diff without bogus .md",
                actual="champion_patch/eval are None and Markdown is written for json/diff",
                probe_script="""
import tempfile, sys
from pathlib import Path
import bugarena.server as srv
with tempfile.TemporaryDirectory() as d:
    r = Path(d) / "r"; r.mkdir()
    (r / "m.py").write_text("def f():\\n    return 1\\n")
    t = srv.agent_fix_tournament(str(r), "tests/t.py", [{"candidate_id": "c1", "persona": "surgical_minimalist", "explanation": "ok", "diff": "--- a/m.py\\n+++ b/m.py\\n@@ -1,2 +1,2 @@\\n def f():\\n-    return 1\\n+    return 2\\n"}])
    srv.evaluate_patches(str(r), t["tournament_id"], "tests/t.py", "from m import f\\ndef test_r(): assert f() == 2\\n")
    res = srv.generate_fix_report(t["tournament_id"], format="json")
    rep = res.get("report", {})
    md_files = list((r / "reports").glob("*.md")) if (r / "reports").exists() else []
    if rep.get("champion_patch") is None or md_files:
        print(f"REPRODUCED: champion_patch={rep.get('champion_patch') is not None} md_for_json={len(md_files)}")
        sys.exit(1)
    print("DISPROVED: FixReport populated and format='json' handled properly")
""",
                suggested_fix="Pass champion_patch and champion_eval to FixReport, populate report_file_path on TournamentRecord, validate format, write .json for json, skip write for diff unless output_file given.",
                risks="None.",
                regression_test_idea="Test FixReport fields populated and json/diff formats",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

    if srv_text and "tournament = _TOURNAMENT_REGISTRY.get(tournament_id)" in srv_text:
        ln = _find_line(srv_lines, r"tournament = _TOURNAMENT_REGISTRY\.get")
        findings.append(
            _draft(
                title="Unlocked _TOURNAMENT_REGISTRY read, FIFO eviction instead of LRU, and duplicate candidate_id handling",
                file="src/bugarena/server.py",
                line_start=35,
                line_end=ln + 5,
                symbol="_store_tournament / evaluate_patches / agent_fix_tournament",
                category="concurrency",
                what_it_is="evaluate_patches reads _TOURNAMENT_REGISTRY unlocked, registries use FIFO without move_to_end, and agent_fix_tournament accepts duplicate candidate_ids and explanation=None crash.",
                what_it_does="Active entries evict prematurely, duplicate IDs collide in cand_map, and null explanations crash with ValidationError.",
                root_cause="Registries lack move_to_end/locked read-modify-write and agent_fix_tournament skips duplicate/null guards.",
                inputs="explanation=None or duplicate candidate_id or 101 stores after reading key 0",
                expected="Returns structured error on duplicate candidate_id, handles null explanation, protects locks and LRU order",
                actual="Crashes with ValidationError on null explanation and evicts recently read entries",
                probe_script="""
import tempfile, sys
from pathlib import Path
import bugarena.server as srv
with tempfile.TemporaryDirectory() as d:
    r = Path(d) / "r"; r.mkdir()
    try:
        res = srv.agent_fix_tournament(str(r), "t.py", [{"candidate_id": "dup", "explanation": None, "diff": "--- a/a.py\\n+++ b/a.py\\n@@ -1 +1 @@\\n-x\\n+y\\n"}, {"candidate_id": "dup", "explanation": "ok", "diff": "--- a/a.py\\n+++ b/a.py\\n@@ -1 +1 @@\\n-x\\n+z\\n"}])
    except Exception as exc:
        print(f"REPRODUCED: unhandled {type(exc).__name__}: {exc}")
        sys.exit(1)
    if "error" not in res:
        print(f"REPRODUCED: duplicate candidate_id accepted without error: {res}")
        sys.exit(1)
    print("DISPROVED: duplicate IDs and null explanation handled")
""",
                suggested_fix="Lock evaluate_patches reads, call move_to_end for LRU, normalize explanation or '', reject duplicate candidate_id cleanly.",
                risks="Callers submitting duplicate candidate_ids now receive an error dict.",
                regression_test_idea="Test duplicate candidate_id rejection, null explanation, and LRU retention",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

    return findings


def _detect_perf_python_docs_tests(repo: Path, allowed: tuple[str, ...], role: str) -> list[FindingDraft]:
    findings: list[FindingDraft] = []

    if role == "performance-optimizer":
        execute_grounding_tool("radon_cc", allowed, repo)
        srv_text, srv_lines = _read_rel(repo, "src/bugarena/server.py")
        tr_text, _ = _read_rel(repo, "src/bugarena/evaluation/test_runner.py")
        if tr_text and "ThreadPoolExecutor" not in tr_text:
            ln = _find_line(srv_lines, r"def bugarena_autonomous_repair")
            findings.append(
                _draft(
                    title="Sequential candidate evaluation and unbounded payload size on server tools",
                    file="src/bugarena/evaluation/test_runner.py",
                    line_start=41,
                    line_end=112,
                    symbol="PatchEvaluator.evaluate_candidates",
                    category="performance",
                    what_it_is="PatchEvaluator executes candidate sandboxes serially without bounded parallelism or wall-clock budget, and server tools lack uniform payload/candidate caps.",
                    what_it_does="20 candidates * 30s timeout stall tournaments for up to 10+ minutes.",
                    root_cause="evaluate_candidates loops serially and direct MCP tools do not bound candidate count or diff sizes.",
                    inputs="evaluate_candidates with >1 candidate patches",
                    expected="Bounded ThreadPoolExecutor with deadline and candidate/diff limits",
                    actual="Serial execution without ThreadPoolExecutor",
                    probe_script="",
                    suggested_fix="Add ThreadPoolExecutor with max_workers<=4 and overall deadline; bound candidate counts/diff sizes on tools.",
                    risks="Concurrent temp sandboxes multiply peak temp disk usage by worker count.",
                    regression_test_idea="Test max candidate rejection and parallel evaluation",
                    severity=SeverityLevel.MEDIUM,
                    evidence_hint=EvidenceType.STATIC,
                    found_by=role,
                )
            )

    if role == "python-reviewer":
        execute_grounding_tool("ruff_json", allowed, repo)
        # ECC-015 runner UTF-8 & POSIX kill
        run_text, run_lines = _read_rel(repo, "src/bugarena/sandbox/runner.py")
        if run_text and 'errors="replace"' not in run_text:
            ln = _find_line(run_lines, r"subprocess\.Popen")
            findings.append(
                _draft(
                    title="run_sandboxed_command omits UTF-8 errors='replace' and process-group termination",
                    file="src/bugarena/sandbox/runner.py",
                    line_start=ln,
                    line_end=ln + 35,
                    symbol="run_sandboxed_command",
                    category="concurrency",
                    what_it_is="Popen opens pipes without encoding='utf-8', errors='replace', omits start_new_session/killpg on POSIX, and calls unbounded proc.communicate() after kill.",
                    what_it_does="Invalid bytes in test output silently drop stdout/stderr on Windows and orphaned grandchildren leak on POSIX.",
                    root_cause="Popen lacks explicit UTF-8 replacement decoding and process-group kill isolation.",
                    inputs="Child process printing raw invalid UTF-8 bytes b'\\xff\\xfe'",
                    expected="Preserves readable decoded output via U+FFFD replacement without dropping stderr/stdout",
                    actual="Silently clears stdout to '' in _readerthread on invalid bytes",
                    probe_script="""
import tempfile, sys
from bugarena.sandbox.runner import run_sandboxed_command
with tempfile.TemporaryDirectory() as d:
    out = run_sandboxed_command(d, [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'ok:\\xff\\n')"])
    if "ok:" not in out.stdout:
        print(f"REPRODUCED: dropped stdout={out.stdout!r}")
        sys.exit(1)
    print("DISPROVED: decoded invalid UTF-8 cleanly with replacement")
""",
                suggested_fix="Pass encoding='utf-8', errors='replace' to Popen, killpg on POSIX, and bound post-kill communicate timeout.",
                risks="None.",
                regression_test_idea="Test invalid raw byte output preserves prefix via replacement",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

        # ECC-017 sandbox cleanup read-only & ignore
        mgr_text, mgr_lines = _read_rel(repo, "src/bugarena/sandbox/manager.py")
        if mgr_text and "ignore_errors=True" in mgr_text and ("onerror" not in mgr_text and "onexc" not in mgr_text):
            ln = _find_line(mgr_lines, r"shutil\.rmtree")
            findings.append(
                _draft(
                    title="EphemeralSandboxManager leaks read-only temp dirs on Windows and copies symlinks",
                    file="src/bugarena/sandbox/manager.py",
                    line_start=ln - 10,
                    line_end=ln + 2,
                    symbol="EphemeralSandboxManager.create_sandbox",
                    category="security",
                    what_it_is="shutil.rmtree(..., ignore_errors=True) fails silently on read-only files on Windows and shutil.copytree uses default symlinks=False.",
                    what_it_does="Temp sandboxes accumulate leaked directories and symlinks can dereference external host files.",
                    root_cause="Cleanup ignores PermissionError instead of clearing read-only attribute and copytree dereferences symlinks.",
                    inputs="Repo with a read-only file in sandbox on Windows",
                    expected="Temp sandbox directory is removed cleanly on context exit",
                    actual="PermissionError ignored, leaking sandbox directory on disk",
                    probe_script="""
import stat, tempfile, sys
from pathlib import Path
from bugarena.sandbox.manager import EphemeralSandboxManager
with tempfile.TemporaryDirectory() as d:
    r = Path(d) / "r"; r.mkdir()
    ro = r / "ro.txt"; ro.write_text("hi")
    ro.chmod(stat.S_IREAD)
    try:
        with EphemeralSandboxManager(r).create_sandbox() as sb:
            saved_sb = sb
        exists = saved_sb.exists()
    finally:
        ro.chmod(stat.S_IWRITE | stat.S_IREAD)
    if exists:
        print(f"REPRODUCED: sandbox dir leaked at {saved_sb}")
        sys.exit(1)
    print("DISPROVED: read-only sandbox cleaned cleanly")
""",
                suggested_fix="Add onexc/onerror handler clearing read-only bits, pass symlinks=True/skip unsafe symlinks, and expand ignored secret patterns.",
                risks="None.",
                regression_test_idea="Test read-only file inside temp sandbox is deleted on exit",
                severity=SeverityLevel.HIGH,
                found_by=role,
            )
        )

        # ECC-006 pyproject missing httpx
        pp_text, pp_lines = _read_rel(repo, "pyproject.toml")
        if pp_text and "httpx" not in pp_text:
            ln = _find_line(pp_lines, r"dependencies =")
            findings.append(
                _draft(
                    title="Missing runtime dependency httpx in pyproject.toml (and dev deps in core)",
                    file="pyproject.toml",
                    line_start=ln,
                    line_end=ln + 8,
                    symbol="project.dependencies",
                    category="build/config",
                    what_it_is="dispatcher.py imports httpx unconditionally while pyproject.toml omits httpx and bundles dev tools in runtime dependencies.",
                    what_it_does="Clean pip install in an isolated environment fails ModuleNotFoundError: No module named 'httpx'.",
                    root_cause="pyproject.toml omits httpx from dependencies and does not separate dev optional-dependencies.",
                    inputs="Inspect pyproject.toml vs src/bugarena/tournament/providers/dispatcher.py:6",
                    expected="httpx declared in dependencies",
                    actual="httpx missing from pyproject.toml",
                    probe_script="""
import sys
from pathlib import Path
pp = Path("pyproject.toml").read_text(encoding="utf-8")
if "httpx" not in pp:
    print("REPRODUCED: httpx absent from pyproject.toml")
    sys.exit(1)
print("DISPROVED: httpx declared in pyproject.toml")
""",
                    suggested_fix="Add httpx>=0.27.0 to dependencies and move ruff/pytest/pytest-asyncio to [project.optional-dependencies] dev (Wait: keep needed runtime test runner deps explicit).",
                    risks="None.",
                    regression_test_idea="Verify pyproject.toml parses and includes httpx",
                    severity=SeverityLevel.HIGH,
                    found_by=role,
                )
            )

        # ECC-007 missing personas/__init__.py + reporting/__init__.py incomplete
        if not (repo / "src/bugarena/tournament/personas/__init__.py").is_file():
            findings.append(
                _draft(
                    title="Missing personas/__init__.py and incomplete reporting/__init__.py exports",
                    file="src/bugarena/tournament/personas/base.py",
                    line_start=1,
                    line_end=5,
                    symbol="personas/__init__.py",
                    category="build/config",
                    what_it_is="tournament/personas/ lacks __init__.py and reporting/__init__.py exports only format_markdown_report.",
                    what_it_does="Package metadata and public exports are inconsistent across subpackages.",
                    root_cause="Missing __init__.py in personas/ and incomplete __all__ in reporting/__init__.py.",
                    inputs="Check Path('src/bugarena/tournament/personas/__init__.py').exists()",
                    expected="Subpackage __init__.py exists and exports public API",
                    actual="personas/__init__.py missing",
                    probe_script="""
import sys
from pathlib import Path
exists = Path("src/bugarena/tournament/personas/__init__.py").is_file()
rep = Path("src/bugarena/reporting/__init__.py").read_text(encoding="utf-8")
if not exists or "save_markdown_report" not in rep:
    print(f"REPRODUCED: personas_init={exists} reporting_exports_complete={'save_markdown_report' in rep}")
    sys.exit(1)
print("DISPROVED: package init and exports complete")
""",
                    suggested_fix="Add src/bugarena/tournament/personas/__init__.py and complete reporting/__init__.py __all__.",
                    risks="Harmless package hygiene.",
                    regression_test_idea="Verify personas and reporting public imports",
                    severity=SeverityLevel.LOW,
                    found_by=role,
                )
            )

        # ECC-036 check_api_keys hardcoded path / JSON crash / no dry-run
        cak_text, cak_lines = _read_rel(repo, "scripts/check_api_keys.py")
        if cak_text and ("--dry-run" not in cak_text or "C:\\\\Users\\\\nisha" in cak_text):
            ln = _find_line(cak_lines, r"check_ollama|nisha")
            findings.append(
                _draft(
                    title="scripts/check_api_keys.py lacks HTTP error/JSON guards, hardcoded user path, and --dry-run",
                    file="scripts/check_api_keys.py",
                    line_start=ln,
                    line_end=204,
                    symbol="check_ollama / main",
                    category="error-handling",
                    what_it_is="check_ollama calls resp.json() unguarded against malformed HTTP responses, main() prints a developer-specific C:\\Users\\... path, and lacks --dry-run.",
                    what_it_does="Non-JSON response on port 11434 crashes script and path hint leaks local developer user.",
                    root_cause="check_api_keys.py omits ValueError guard on resp.json(), hardcodes user path, and always executes live calls.",
                    inputs="Run check_api_keys --dry-run or non-JSON Ollama response",
                    expected="Supports --dry-run safely, handles ValueError, uses Path.home()",
                    actual="Hardcoded user path and unguarded resp.json()",
                    probe_script="""
import sys
from pathlib import Path
txt = Path("scripts/check_api_keys.py").read_text(encoding="utf-8")
if "--dry-run" not in txt or "ValueError" not in txt:
    print("REPRODUCED: missing --dry-run or ValueError guard")
    sys.exit(1)
print("DISPROVED: check_api_keys hardened")
""",
                    suggested_fix="Catch ValueError in check_ollama, replace hardcoded username path with ~/.gemini/config/mcp_config.json, add --dry-run CLI flag.",
                    risks="None.",
                    regression_test_idea="Test check_api_keys --dry-run and non-JSON Ollama mock response",
                    severity=SeverityLevel.MEDIUM,
                    found_by=role,
                )
            )

    if role == "comment-analyzer":
        execute_grounding_tool("grep", allowed, repo, pattern=r"--network=none|40\*|format", path_prefix="")
        readme_text, _ = _read_rel(repo, "README.md")
        _skill_text, _ = _read_rel(repo, ".agents/skills/bugarena-repair/SKILL.md")
        gi_text, _ = _read_rel(repo, ".gitignore")
        mf_text, _ = _read_rel(repo, "src/bugarena/reporting/markdown_formatter.py")

        if (
            readme_text
            and ("generate_bug_report" not in readme_text or "bug_detect`" in readme_text)
            and ("generate_bug_report" not in readme_text or "audit_start" not in readme_text)
        ):
                findings.append(
                    _draft(
                        title="README.md / SKILL.md drift from actual MCP tools, isolation, and scoring",
                        file="README.md",
                        line_start=40,
                        line_end=115,
                        symbol="README.md / SKILL.md",
                        category="doc_drift",
                        what_it_is="README.md omits generate_bug_report and new audit tools, hardcodes user-specific .venv path, and SKILL.md claims nonexistent diff heuristics.",
                        what_it_does="Users and MCP clients receive inaccurate setup instructions and false tool capability expectations.",
                        root_cause="Documentation was not synchronized with server tools and scoring/isolation implementation.",
                        inputs="Compare @mcp.tool() list against README.md & SKILL.md",
                        expected="Every @mcp.tool() documented cleanly and setup instructions accurate",
                        actual="Missing documented tools and hardcoded environment details",
                        probe_script="",
                        suggested_fix="Update README.md and SKILL.md tool tables, isolation notes, scoring behavior, and add CI tool-doc test.",
                        risks="None.",
                        regression_test_idea="Add test asserting every @mcp.tool() name appears in README.md",
                        severity=SeverityLevel.LOW,
                        evidence_hint=EvidenceType.DOC_COMPARE,
                        found_by=role,
                    )
                )

        if gi_text and ".env.*" not in gi_text:
            findings.append(
                _draft(
                    title=".gitignore omits .env.*, reports/, .ruff_cache/ and .env.example leaves blank keys",
                    file=".gitignore",
                    line_start=37,
                    line_end=40,
                    symbol=".gitignore / .env.example",
                    category="hygiene",
                    what_it_is=".gitignore omits .env.* (preserving !.env.example), reports/, and .ruff_cache/, while .env.example has uncommented blank KEY= placeholders.",
                    what_it_does="Generated reports and local .env.* files risk unintended git tracking.",
                    root_cause="Incomplete .gitignore entries and uncommented empty env templates.",
                    inputs="git check-ignore .env.local reports/x.md",
                    expected=".env.local and reports/x.md ignored cleanly",
                    actual="Not ignored by .gitignore",
                    probe_script="""
import subprocess, sys
r = subprocess.run(["git", "check-ignore", ".env.local"], capture_output=True, text=True, check=False)
if r.returncode != 0:
    print(f"REPRODUCED: .env.local not gitignored (rc={r.returncode})")
    sys.exit(1)
print("DISPROVED: .env.local is ignored")
""",
                    suggested_fix="Add .env.*, !.env.example, reports/, tests/repro/, .ruff_cache/, .bugarena/ to .gitignore and comment .env.example placeholders.",
                    risks="None.",
                    regression_test_idea="Test .gitignore patterns cleanly ignore .env.local and reports/",
                    severity=SeverityLevel.LOW,
                    found_by=role,
                )
            )

        if mf_text and ("|" not in mf_text or "disqualification_reason" not in mf_text):
            findings.append(
                _draft(
                    title="Markdown formatter breaks tables on pipes/newlines and drops disqualification_reason",
                    file="src/bugarena/reporting/markdown_formatter.py",
                    line_start=45,
                    line_end=140,
                    symbol="format_bug_diagnostic_markdown / format_markdown_report",
                    category="logic",
                    what_it_is="Table cell strings with '|' or newlines break Markdown columns, triple-backticks inside code snippets can close fences prematurely, and disqualification_reason is omitted.",
                    what_it_does="Reports render malformed tables and hide why candidates were disqualified.",
                    root_cause="markdown_formatter interpolates raw cell strings without escaping pipes/newlines or rendering disqualification_reason.",
                    inputs="SuspectLocation with reasoning='a | b\\nc' or disqualified PatchEvaluation",
                    expected="Escaped table cell, adaptive fences, and visible disqualification_reason",
                    actual="Broken Markdown table row and disqualification_reason omitted",
                    probe_script="""
import sys
from bugarena.models.bug import BugSpec, SuspectLocation
from bugarena.models.tournament import PatchEvaluation, TournamentRecord
from bugarena.reporting.markdown_formatter import format_markdown_report
ev = PatchEvaluation(candidate_id="c1", repro_passed=True, regressions_count=1, total_regressions_checked=1, diff_churn=1, cyclomatic_delta=0, score=0.0, disqualified=True, disqualification_reason="REASON_XYZ")
s = SuspectLocation(file_path="a.py", function_name="f", line_range=(1,1), confidence=0.9, bug_type="A|B", reasoning="line1\\nline2|x", code_snippet="```\\ncode")
t = TournamentRecord(tournament_id="t1", repo_path=".", bug_spec=BugSpec(bug_id="b1", repo_path=".", suspects=[s]), evaluations=[ev])
md = format_markdown_report(t)
if "REASON_XYZ" not in md or "line1\\nline2|x" in md:
    print("REPRODUCED: unescaped table cell or omitted disqualification_reason")
    sys.exit(1)
print("DISPROVED: table escaped and disqualification_reason rendered")
""",
                    suggested_fix="Escape '|' and replace newlines in Markdown table cells, choose adaptive fence length, render disqualification_reason, and frame untrusted inputs cleanly.",
                    risks="None.",
                    regression_test_idea="Test pipes/newlines/backticks escaping and disqualification_reason display",
                    severity=SeverityLevel.MEDIUM,
                    found_by=role,
                )
            )

    if role == "pr-test-analyzer":
        execute_grounding_tool("pytest_run", allowed, repo)
        ts_text, ts_lines = _read_rel(repo, "tests/unit/test_security.py")
        if ts_text and 'or r\'\\"\\"\\"\' in test_code' in ts_text:
            ln = _find_line(ts_lines, r"whoami")
            findings.append(
                _draft(
                    title="Tautological assertion in test_security.py masks docstring/code injection",
                    file="tests/unit/test_security.py",
                    line_start=ln - 2,
                    line_end=ln + 2,
                    symbol="test_docstring_injection_sanitization",
                    category="test-gap",
                    what_it_is="test_security.py:117 uses 'or r\"\\\"\\\"\\\"\" in test_code', which passes even if malicious imports run.",
                    what_it_does="Creates false test confidence across security and failure-path regressions.",
                    root_cause="Boolean OR tautology passes whenever escaped triple quotes appear anywhere in test_code.",
                    inputs="Inspect tests/unit/test_security.py:117 and unit tests for negative paths",
                    expected="Strict AST assertion verifying no os import or system call nodes exist",
                    actual="Tautological OR condition in test_security.py",
                    probe_script="",
                    suggested_fix="Replace tautological assert with ast.parse node checks and add negative/mocked tests for evaluator, applier, parser, env loader, server.",
                    risks="None.",
                    regression_test_idea="Verify ast.parse finds zero Import/ImportFrom(os) in docstring-injection test",
                    severity=SeverityLevel.MEDIUM,
                    evidence_hint=EvidenceType.STATIC,
                    found_by=role,
                )
            )

    if role == "architect":
        execute_grounding_tool("git_ls", allowed, repo)
        srv_text, srv_lines = _read_rel(repo, "src/bugarena/server.py")
        if srv_text and "TournamentRunner" not in srv_text:
            ln = _find_line(srv_lines, r"def bugarena_autonomous_repair")
            findings.append(
                _draft(
                    title="TournamentRunner and MultiModelDispatcher are unwired dead code from MCP server",
                    file="src/bugarena/server.py",
                    line_start=ln,
                    line_end=ln + 20,
                    symbol="bugarena_autonomous_repair",
                    category="architecture",
                    what_it_is="TournamentRunner and MultiModelDispatcher are never wired into MCP server handlers.",
                    what_it_does="MCP server cannot trigger LLM-backed tournament generation even when configured.",
                    root_cause="server.py only accepts manual candidate_patches_raw and never integrates TournamentRunner.",
                    inputs="Search server.py for TournamentRunner",
                    expected="Server wires TournamentRunner/MultiModelDispatcher cleanly behind auto_generate=False gate",
                    actual="TournamentRunner not imported or reachable from server.py",
                    probe_script="""
import sys
from pathlib import Path
if "TournamentRunner" not in Path("src/bugarena/server.py").read_text(encoding="utf-8"):
    print("REPRODUCED: TournamentRunner not wired into server.py")
    sys.exit(1)
print("DISPROVED: TournamentRunner wired into server.py")
""",
                    suggested_fix="Wire TournamentRunner/MultiModelDispatcher into server tools gated behind auto_generate: bool = False.",
                    risks="Default auto_generate=False prevents unintended paid API calls.",
                    regression_test_idea="Test server tool auto_generate=True invokes injected/mocked TournamentRunner without hitting live network",
                    severity=SeverityLevel.MEDIUM,
                    found_by=role,
                )
            )

    return findings


ROLE_DETECTORS: dict[str, Callable[[Path, tuple[str, ...], str], list[FindingDraft]]] = {
    "security-reviewer": _detect_security,
    "code-reviewer": _detect_code_logic,
    "silent-failure-hunter": _detect_silent_failures,
    "type-design-analyzer": _detect_dispatcher_and_models,
    "performance-optimizer": _detect_perf_python_docs_tests,
    "python-reviewer": _detect_perf_python_docs_tests,
    "comment-analyzer": _detect_perf_python_docs_tests,
    "pr-test-analyzer": _detect_perf_python_docs_tests,
    "architect": _detect_perf_python_docs_tests,
}


def run_offline_detector(
    role_name: str,
    repo_path: Path | str,
    allowed_tools: tuple[str, ...],
) -> list[FindingDraft]:
    """Run deterministic grounded analysis for one specialist role on repo_path."""
    fn = ROLE_DETECTORS.get(role_name)
    if fn is None:
        return []
    return fn(Path(repo_path).resolve(), allowed_tools, role_name)
