# BugArena MCP — Read-Only Bug Audit Report

## 1. Executive Summary

- **Project:** `bugarena-mcp` (`d:\MCP server`, Git branch `main`, commit `46acbdee6cba97f74341636adc72794fc437bd87`)
- **Stack:** Python 3.14.0 (`requires-python = ">=3.11"`), `mcp>=2.0.0` (`MCPServer 2.3.0` over stdio), `pydantic>=2.0.0`, `radon 6.0.1`, `httpx` (present in `.venv` transitively via another env package, undeclared in `pyproject.toml`), `pytest 9.2.0`, `pytest-asyncio`, `ruff 0.17.5`; in-memory `OrderedDict` state (no database); headless CLI/MCP server (no web UI or GUI).
- **Audit Date:** 2026-11-25 (`18:18`–`19:00` IST)
- **Mode:** Strictly **READ-ONLY** audit. Zero project files edited, formatted, deleted, renamed, or committed. Zero live external API calls executed against `.env` credentials.
- **Rounds Run:** 6 rounds (reached 6-round hard cap after 100% coverage of all 13 target modules/configs; Round 5 confirmed the final `.gitignore`/template finding `BUG-043`, and Round 6 completed with zero new confirmed findings):
  - `Round 1: 40 new, 0 confirmed, 0 dismissed, coverage 50%`
  - `Round 2: 0 new, 35 confirmed, 4 dismissed, coverage 85%`
  - `Round 3: 2 new, 6 confirmed, 1 dismissed, coverage 95%`
  - `Round 4: 1 new, 1 confirmed, 0 dismissed, coverage 98%`
  - `Round 5: 0 new, 1 confirmed, 0 dismissed, coverage 100%`
  - `Round 6: 0 new, 0 confirmed, 0 dismissed, coverage 100%`

### Severity Counts (43 Confirmed Bugs, 0 Unverified Whole Bugs)

| Severity | Confirmed | Unverified | Notes |
| :--- | :---: | :---: | :--- |
| **Critical** | 14 | 0 | Remote code execution, arbitrary file read/write, broken sandbox & evaluator gates, packaging/schema failures |
| **High** | 22 | 0 | Parser normalization & corruptions, bypasses, LLM routing defects, concurrency/state bugs, test gaps |
| **Medium** | 7 | 0 | Telemetry truncation, schema/docs/gitignore drift, AST shadowing, path edge cases |
| **Low** | 0 | 0 | — |
| **Total** | **43** | **0** | Plus 5 dismissed sub-hypotheses (Appendix A) and 4 unverified sub-claims (Appendix B) |

### Top 3 Risks

1. **Remote Code Execution & Unsandboxed Host Execution (`BUG-001`, `BUG-002`, `BUG-005`):** Both `bug_reproduce` and `evaluate_patches` interpolate or execute arbitrary caller-supplied Python code (`call_expr`, `expected_behavior`, `repro_code`) inside host `subprocess.Popen` processes with **no** OS container, filesystem jail, or `--network=none` isolation despite documentation claiming container/jail confinement.
2. **Arbitrary Host File Write & Secret Exfiltration (`BUG-003`, `BUG-004`, `BUG-019`, `BUG-029`):** Unvalidated `output_file` writes arbitrary `.md` files anywhere on the host filesystem, forged tracebacks in `bug_detect`/`generate_bug_report` read `.env` secrets unscrubbed, and `load_env_file` / `scrub_sensitive_data` leak secrets via permissive parsing and slash/pattern ordering bugs.
3. **Evaluation Integrity & Fail-Open Validation (`BUG-008`, `BUG-009`, `BUG-010`, `BUG-011`, `BUG-013`, `BUG-014`):** Empty or timed-out tests pass Red-baseline validation (`exit 5`, `-1`), custom unified diff patching silently corrupts files, `PatchEvaluator` omits `calculate_cyclomatic_delta` and awards 99.4+ scores when `tests/` is absent or broken files are untested, and `FixReport` silently drops `champion_patch`/`champion_eval`.

---

## 2. Coverage and Method

### ECC Agents & Skills Used

- **Used ECC Agents (12):**
  - Orchestration & QA: `loop-operator`, `agent-evaluator`
  - Round 1 Static Sweep (8 parallel): `python-reviewer`, `code-reviewer`, `security-reviewer`, `silent-failure-hunter`, `performance-optimizer`, `type-design-analyzer`, `pr-test-analyzer`, `comment-analyzer`
  - Round 3–5 Independent Verification & Deep Dives: `architect`, `code-architect`
- **Used ECC Skills (4):** `security-review`, `verification-loop`, `python-patterns`, `python-testing`
- **Unavailable / Skipped Agents & Tools:**
  - `spec-miner`: Not installed / disallowed in this environment (`subagent not found`).
  - `code-explorer`: Stalled while invoking `context-mode` (`ctx_execute`) during Phase 0; replaced cleanly by direct file reading across all 49 tracked files.
  - Framework/UI/DB specialists (`database-reviewer`, `e2e-runner`, `a11y-architect`, `react-reviewer`, `vue-reviewer`, `django-reviewer`, `fastapi-reviewer`): Not applicable (headless Python MCP stdio library with no database or UI).
  - `pyright` / `mypy`: Not installed in workspace `.venv` or host `PATH`.

### Verification Commands Executed (Read-Only)

1. Baseline & Final Unit/Integration Suite: `.venv\Scripts\pytest.exe -q --tb=short` (`43 passed in 20.65s` in Phase 0; `43 passed in 20.61s` in Round 6).
2. Lint on Tracked Code vs Full Workspace:
   - `.venv\Scripts\ruff.exe check .` in Phase 0 ([`./evidence/phase0_baseline.txt`](./evidence/phase0_baseline.txt)) -> `All checks passed!` (`EXIT=0`).
   - `.venv\Scripts\ruff.exe check .` in Round 6 ([`./evidence/R6-final-git-proof.txt`](./evidence/R6-final-git-proof.txt)) -> `41 errors` exclusively inside untracked external directory `bug_report\evidence\*.py`, with zero errors in `src/`, `tests/`, or `scripts/` (see Cleanliness Note below).
3. Cyclomatic Complexity: `.venv\Scripts\radon.exe cc "src" -s -a` (`73 blocks analyzed, Average complexity B (5.356)`, peak `C (20)` in `get_recommended_model_for_persona`).
4. Isolated Dynamic Probes in `$env:TEMP` (`./evidence/R2-*.txt`, `./evidence/R3-*.txt`, `./evidence/R4-*.txt`, `./evidence/R5-*.txt`, using `os.environ.pop` after import and `httpx.MockTransport` — zero live API calls or project workspace writes).
5. Headless MCP Stdio Handshake: Spawned `.venv\Scripts\python.exe -m bugarena.server` and `bugarena.exe` sending `initialize`, `notifications/initialized`, and `tools/list` ([`./evidence/R2-probe-a-packaging-mcp.txt`](./evidence/R2-probe-a-packaging-mcp.txt), [`./evidence/R3-deep-edge-probes.txt`](./evidence/R3-deep-edge-probes.txt), [`./evidence/R3-mcp-tool-schemas.txt`](./evidence/R3-mcp-tool-schemas.txt)).

### Areas Covered vs. Limitations

- **Coverage Achieved:** All **13/13** repository areas inspected statically (all 49 tracked non-`.env` files read in full) and exercised dynamically (`config.py`, `server.py`, `__init__.py`, `models/`, `discovery/`, `synthesizer/`, `sandbox/`, `tournament/`, `evaluation/`, `reporting/`, `scripts/check_api_keys.py`, `pyproject.toml` + `.agents/skills/bugarena-repair/SKILL.md`, `tests/`).
- **Deliberate Non-Coverage / Environmental Limits (Appendix B):**
  1. `.env` was never read and live provider endpoints (`GEMINI`, `OPENAI`, `DEEPSEEK`, `GROQ`, `ANTHROPIC`) were never contacted per Hard Rule 5 (verified offline via `httpx.MockTransport`).
  2. Symlink dereference copy inside `EphemeralSandboxManager.create_sandbox` could not be dynamically executed on this Windows host without Developer Mode/Admin privileges (`OSError [WinError 1314]`).
  3. POSIX child-process group orphans (`proc.kill()`) and >64KB OS pipe buffer deadlock under `subprocess.TimeoutExpired` remain statically confirmed rather than triggered dynamically.

### Clean `git status` & `git diff --stat` Proof (Round 6)

Full output captured in [`./evidence/R6-final-git-proof.txt`](./evidence/R6-final-git-proof.txt):

```text
--- git rev-parse HEAD & branch ---
46acbdee6cba97f74341636adc72794fc437bd87
main

--- git status ---
On branch main
Your branch is ahead of 'origin/main' by 2 commits.
  (use "git push" to publish your local commits)

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	bug-report/
	bug_report/

nothing added to commit but untracked files present (use "git add <file>..." to include in what will be committed)

--- git diff --stat ---
<EMPTY (0 tracked files modified)>

--- git ls-files count ---
Tracked files: 49
```

> [!NOTE]
> **Provenance of Untracked `bug_report/` Directory:** During the audit window (`18:21–18:49 IST`), a concurrent external session (`c7cc1425-1d39-42bd-981e-1ed9875f1407`, verified via session transcript search) created `d:\MCP server\bug_report\`. None of this audit's deliverables or 16 subagents created or modified `bug_report/`, and it was left untouched in strict compliance with Hard Rule 1 (`never delete or modify files outside ./bug-report/`). All deliverables for this audit reside strictly inside `./bug-report/`.

> [!NOTE]
> **Pre-Deduplication Evidence Tag Cross-Reference:** Exploratory Round 4–5 evidence files in `./evidence/` occasionally reference preliminary working tags (`BUG-042a`, `BUG-042b`, `BUG-043`, `BUG-044`, `BUG-045`). Following Round 5 root-cause deduplication, `BUG-042b` merged into `BUG-008`, `BUG-043` merged into `BUG-024`, `BUG-044` merged into `BUG-019`, `.gitignore`/`.env.example` (`BUG-045`) became canonical `BUG-043`, and `.strip()` + `b/`-normalization drift became `BUG-042`.

---

## 3. Bug List

> **Severity Tier: Critical (14 Bugs — `BUG-001`..`BUG-006`, `BUG-008`..`BUG-014`, `BUG-016`)**

### BUG-001 — Arbitrary Python Code Execution via Unsanitized `call_expr` and `expected_behavior` in `bug_reproduce`
- Severity: Critical   Confidence: Confirmed
- Category: security
- Location: `src/bugarena/synthesizer/test_generator.py:35-46,73-75`; `src/bugarena/server.py:92-125,386-393`
- Found by: security-reviewer, code-reviewer, python-reviewer, pr-test-analyzer   Verified by: architect, Round 2 Dynamic Probe
- **What the bug is:** `generate_reproduction_test_code` directly interpolates untrusted strings `call_expr`, `expected_behavior`, `clean_func`, and `import_path` into Python source (`target_call`, `with pytest.raises({exc_name}):`, `assert {expected_behavior}`, `result = {target_call}`) and executes the generated file immediately via `validate_red_baseline`. Only `bug_description` passes through `_sanitize_docstring`.
- **What the bug does:** Any prompt-injected repository error log, malicious MCP client, or compromised LLM calling `bug_reproduce` or `bugarena_autonomous_repair` achieves immediate arbitrary Python code execution on the host machine (filesystem reads/writes, environment reading via `Path('.env')`, lateral network calls).
- **How to reproduce:**
  1. Call `bug_reproduce(repo_path=<temp_repo>, suspect_file="app.py", bug_description="test", call_expr="__import__('pathlib').Path('<marker>').write_text('PWNED') or 1/0", expected_behavior="True")`.
  2. Expected: Untrusted expression strings are parsed/validated against a safe AST allowlist (or never evaluated directly via executable template interpolation).
  3. Actual: `bug_reproduce` writes and executes the test in `pytest`, executes the side-effect writing `"PWNED"` to disk, and returns `"status": "REPRODUCED_RED"`.
- **Screenshots / evidence:** No screenshot: headless stdio MCP server and Python library with no web or GUI interface; captured output from [`./evidence/R2-probe-b-security.txt`](./evidence/R2-probe-b-security.txt):
  ```text
  === BUG-001: RCE in bug_reproduce call_expr ===
  bug_reproduce status: REPRODUCED_RED marker_exists? True content: PWNED
  ```
- **Recommended fix (NOT applied):** Validate `call_expr` and `expected_behavior` via `ast.parse(..., mode="eval")` against a strict safe AST node whitelist (only `ast.Call`, `ast.Attribute`, `ast.Name`, `ast.Constant`, `ast.Compare`, `ast.Tuple`, `ast.List`; zero `Import`, `Lambda`, or dunder attributes like `__import__`/`__builtins__`) and reject statements/newlines.
  ```python
  # BEFORE (src/bugarena/synthesizer/test_generator.py:35-44)
  target_call = call_expr or f"{clean_func}()"
  if expected_behavior and "raises " in expected_behavior.lower():
      exc_name = expected_behavior.split("raises ", 1)[1].strip()
      assertion_block = f"    with pytest.raises({exc_name}):\n        {target_call}\n"

  # AFTER
  target_call = _validate_safe_python_expr(call_expr or f"{clean_func}()")
  if expected_behavior and (m := re.search(r"\braises\s+([A-Za-z_][A-Za-z0-9_.]*)", expected_behavior, re.I)):
      exc_name = _validate_identifier_chain(m.group(1))
      assertion_block = f"    with pytest.raises({exc_name}):\n        {target_call}\n"
  ```
  - *Risks/Side effects:* Complex inline setup expressions will be rejected unless modeled via fixture arguments or dedicated test parameters.
  - *Suggested regression tests:* Unit tests verifying `call_expr="__import__('os').system('id')"` and `expected_behavior="ValueError)\nimport os"` raise `ValueError` before `ast.parse` file execution.
- Related bugs: BUG-002, BUG-005, BUG-024

---

### BUG-002 — Arbitrary Code Execution via Unvalidated `repro_code` in `evaluate_patches`
- Severity: Critical   Confidence: Confirmed
- Category: security
- Location: `src/bugarena/server.py:203-226`; `src/bugarena/evaluation/test_runner.py:44-46,69-74`
- Found by: security-reviewer   Verified by: architect, Round 2 Dynamic Probe
- **What the bug is:** `evaluate_patches` accepts an arbitrary `repro_code: str` directly from the MCP tool caller instead of looking up the verified reproduction test stored during `bug_reproduce`, constructs a fresh `ReproTestSpec(..., red_baseline_verified=True)` at `server.py:216-220`, and immediately writes and executes `repro_code` in `PatchEvaluator`.
- **What the bug does:** Allows arbitrary code execution directly on the host machine (including mutating/reading host files if `validate_red_baseline` was never run) and lets callers spoof `red_baseline_verified=True` using a trivial or malicious test file.
- **How to reproduce:**
  1. Register a minimal tournament via `agent_fix_tournament`.
  2. Call `evaluate_patches(repo_path=<temp_repo>, tournament_id=tid, repro_test_file="tests/repro/t.py", repro_code="from pathlib import Path\ndef test_pwn():\n    Path('<marker>').write_text('EVAL_PWN')\n    assert True\n")`.
  3. Expected: `evaluate_patches` binds to the verified `ReproTestSpec` stored on `tournament.repro_spec` (or requires sandboxed Red-baseline validation + restricted execution).
  4. Actual: Writes `'EVAL_PWN'` directly to the host path and crowns candidate `c1` as Champion.
- **Screenshots / evidence:** No screenshot: headless stdio MCP server with no GUI; captured output from [`./evidence/R2-probe-b-security.txt`](./evidence/R2-probe-b-security.txt):
  ```text
  === BUG-002: evaluate_patches arbitrary repro_code RCE ===
  eval champion: c1 marker2_exists? True
  ```
- **Recommended fix (NOT applied):** Require `tournament.repro_spec` generated by `bug_reproduce` (or run `validate_red_baseline` on any newly supplied `repro_code` inside an isolated OS container) and verify `repro_code` matches the registered spec hash unless explicitly re-validated.
  ```python
  # BEFORE (src/bugarena/server.py:216-225)
  repro_spec = ReproTestSpec(
      test_file_path=repro_test_file,
      test_code=repro_code,
      red_baseline_verified=True,
  )

  # AFTER
  if tournament.repro_spec and not repro_code:
      repro_spec = tournament.repro_spec
  else:
      repro_spec = validate_red_baseline(repo_path, repro_test_file, repro_code)
  ```
  - *Risks/Side effects:* Breaks direct unit callers passing already-fixed repro code without prior `bug_reproduce` unless a two-stage flow is enforced; full security still requires OS containerization (`BUG-005`).
  - *Suggested regression tests:* Verify `evaluate_patches` rejects arbitrary passing `repro_code` that fails Red-baseline validation.
- Related bugs: BUG-001, BUG-005, BUG-018

---

### BUG-003 — Arbitrary Host File Overwrite via Unvalidated `output_file` in Report Tools
- Severity: Critical   Confidence: Confirmed
- Category: security
- Location: `src/bugarena/reporting/markdown_formatter.py:10-17`; `src/bugarena/server.py:248-279,316-350,441`
- Found by: security-reviewer, code-reviewer, python-reviewer, pr-test-analyzer   Verified by: architect, Round 2 Dynamic Probe
- **What the bug is:** `save_markdown_report(report_markdown, output_path)` resolves `Path(output_path).resolve()` and writes UTF-8 text without calling `validate_safe_path`. All three MCP reporting endpoints (`generate_fix_report`, `generate_bug_report`, `bugarena_autonomous_repair`) pass `output_file` directly into `save_markdown_report`.
- **What the bug does:** Any caller passing `../../outside.md` or an absolute path such as `~/.ssh/authorized_keys` / `.bashrc` / `AGENTS.md` overwrites or creates arbitrary files anywhere on the host filesystem, including auto-creating parent directories via `mkdir(parents=True, exist_ok=True)`.
- **How to reproduce:**
  1. Invoke `generate_bug_report(repo_path=<repo>, error_log="...", output_file=str(Path(repo).parent / "escaped_dir" / "outside.md"))`.
  2. Expected: Raises `SecurityViolationError` because `output_file` escapes `repo_path`.
  3. Actual: Creates `escaped_dir` outside `repo_path` and writes `outside.md`.
- **Screenshots / evidence:** No screenshot: headless stdio MCP server with no GUI; captured output from [`./evidence/R2-probe-b-security.txt`](./evidence/R2-probe-b-security.txt):
  ```text
  === BUG-003: save_markdown_report writes outside repo ===
  outside.md written outside repo? True in escaped_dir? True
  ```
- **Recommended fix (NOT applied):** Validate `output_path` inside both `server.py` handlers and `save_markdown_report` using `validate_safe_path(repo_path, out_path)` (and reject symlinks or non-`.md`/`.json` extensions as appropriate).
  ```python
  # BEFORE (src/bugarena/reporting/markdown_formatter.py:10-17)
  def save_markdown_report(report_markdown: str, output_path: str | Path) -> Path:
      target = Path(output_path).resolve()
      target.parent.mkdir(parents=True, exist_ok=True)
      target.write_text(report_markdown, encoding="utf-8")
      return target

  # AFTER
  def save_markdown_report(
      report_markdown: str, output_path: str | Path, base_dir: str | Path | None = None
  ) -> Path:
      if base_dir is not None:
          target = validate_safe_path(base_dir, str(output_path))
      else:
          target = Path(output_path).resolve()
      target.parent.mkdir(parents=True, exist_ok=True)
      target.write_text(report_markdown, encoding="utf-8")
      return target
  ```
  - *Risks/Side effects:* Workflows intentionally writing reports to a centralized directory outside `repo_path` would require passing an explicit allowed `base_dir` or server-configured output root.
  - *Suggested regression tests:* Test `generate_fix_report(..., output_file="../../evil.md")` and `generate_bug_report(..., output_file=...)` raise `SecurityViolationError`.
- Related bugs: BUG-004, BUG-033, BUG-041

---

### BUG-004 — Arbitrary File Read & Secret Exfiltration via `bug_detect` and `generate_bug_report`
- Severity: Critical   Confidence: Confirmed
- Category: security
- Location: `src/bugarena/server.py:63-88,316-357`; `src/bugarena/discovery/engine.py:35-68,100-107`
- Found by: security-reviewer   Verified by: architect, Round 2 Dynamic Probe
- **What the bug is:** `BugDiscoveryEngine.discover_from_trace` accepts attacker-controlled file paths inside `error_log`, resolves them against `repo_path` (`candidate.is_relative_to(self.repo_path)`), reads file contents into `SuspectLocation.code_snippet`, and returns both raw snippets and raw `error_log` in `bug_detect` and `generate_bug_report` without ignoring `.env`/secret files or calling `scrub_sensitive_data`.
- **What the bug does:** A forged traceback pointing at `.env`, `.env.local`, `.ssh/`, or any non-code file inside `repo_path` returns verbatim plaintext secrets inside `code_snippet` (while `.resolve()` rejects symlinks pointing outside `repo_path`, secret files located *inside* `repo_path` pass the containment check cleanly). `generate_bug_report` also writes those unscrubbed secrets to disk in Markdown.
- **How to reproduce:**
  1. Create a temp repo containing `.env` with a dummy secret token (`sk-d…`, 49 chars total).
  2. Call `bug_detect(repo_path=str(repo), error_log='  File ".env", line 1, in <module>\nError')`.
  3. Expected: Dotenv/secret/non-Python files are excluded and outputs are scrubbed.
  4. Actual: Returns `suspects` containing the full plaintext secret line of length 49 (`prefix leaked? True`).
- **Screenshots / evidence:** No screenshot: headless stdio MCP server with no GUI; captured output from [`./evidence/R2-probe-b-security.txt`](./evidence/R2-probe-b-security.txt) (secret value redacted):
  ```text
  === BUG-004: bug_detect reads .env and exposes snippet unscrubbed ===
  suspect count: 1 prefix leaked? True len: 49
  ```
- **Recommended fix (NOT applied):** Restrict `BugDiscoveryEngine` to source extensions (`.py` or configured code extensions), explicitly exclude `.env*`, `.git/`, `.venv/`, and key files, check `candidate.lstat()` before resolving symlinks, and pass `code_snippet` and `error_log` through `scrub_sensitive_data`.
  ```python
  # BEFORE (src/bugarena/discovery/engine.py:42-64)
  if candidate_path.is_file() and candidate_path.is_relative_to(self.repo_path):
      resolved_file = candidate_path
  ...
  content = resolved_file.read_text(encoding="utf-8", errors="replace")

  # AFTER
  if (
      resolved_file.suffix == ".py"
      and not any(part.startswith(".env") or part in {".git", ".venv", ".ssh"} for part in resolved_file.parts)
      and resolved_file.is_relative_to(self.repo_path)
  ):
      ...
  ```
  - *Risks/Side effects:* Non-Python stack traces targeting config files would no longer return file snippets unless explicitly allowlisted.
  - *Suggested regression tests:* Verify `bug_detect` and `generate_bug_report` ignore `.env` and scrub API key patterns when present inside `error_log`.
- Related bugs: BUG-003, BUG-025, BUG-029

---

### BUG-005 — No OS, Process, or Network Sandbox Isolation Despite `--network=none` / Container Documentation
- Severity: Critical   Confidence: Confirmed
- Category: security
- Location: `src/bugarena/sandbox/manager.py:21-60`; `src/bugarena/sandbox/runner.py:18-49`; `README.md:41-45`; `.agents/skills/bugarena-repair/SKILL.md:8,71`
- Found by: security-reviewer, comment-analyzer   Verified by: architect, Round 2 Dynamic Probe
- **What the bug is:** `EphemeralSandboxManager` merely calls `shutil.copytree` into `tempfile.mkdtemp`, and `run_sandboxed_command` launches a plain host `subprocess.Popen` using `sys.executable` with no Docker/container runtime, OS namespace, seccomp/AppArmor policy, read-only root mount, or `--network=none` restriction.
- **What the bug does:** Untrusted code in target repositories, synthesized tests, or candidate patches executes directly as the MCP server OS user with full host filesystem read/write access and full LAN/internet outbound network access, contradicting `README.md:43-44` (`--network=none, jails, isolated subshell/tempfs`).
- **How to reproduce:**
  1. Execute `bug_reproduce` or `evaluate_patches` with test code that writes outside the temp directory or opens an outbound socket (as demonstrated in `BUG-001` and `BUG-002`).
  2. Expected: Writes outside the ephemeral sandbox and outbound network connections are blocked by OS isolation (`--network=none`).
  3. Actual: Both succeed directly on the host OS.
- **Screenshots / evidence:** No screenshot: headless library/MCP server with no GUI; architectural inspection across `manager.py:21-60` and `runner.py:18-49` plus host file creation observed in [`./evidence/R2-probe-b-security.txt`](./evidence/R2-probe-b-security.txt):
  ```text
  bug_reproduce status: REPRODUCED_RED marker_exists? True content: PWNED
  eval champion: c1 marker2_exists? True
  ```
- **Recommended fix (NOT applied):** Either run untrusted test executions inside a container runtime (`docker run --rm --network=none --read-only --cap-drop=ALL ...`) / OS sandbox (`bwrap`, AppContainer), OR immediately remove all `--network=none` / jail claims from documentation and warn operators that sandboxing is temporary-directory copy-only.
  ```python
  # BEFORE (src/bugarena/sandbox/runner.py:41-49)
  proc = subprocess.Popen(
      clean_args, cwd=str(ws_path), stdout=subprocess.PIPE,
      stderr=subprocess.PIPE, text=True, env=base_env, shell=False,
  )

  # AFTER (runner.py: wrap test command in an isolated container when enabled)
  cmd = ["docker", "run", "--rm", "--network=none", "--pids-limit=64", "--memory=512m",
         "-v", f"{ws_path}:/work:rw", "-w", "/work", image, *clean_args]
  ```
  - *Risks/Side effects:* Container execution requires Docker/Podman installed on the host and pre-warmed Python test environments.
  - *Suggested regression tests:* Integration test verifying outbound socket connections fail inside sandbox runner when container mode is active.
- Related bugs: BUG-001, BUG-002, BUG-017, BUG-040

---

### BUG-006 — Undeclared Direct Dependency `httpx` in `pyproject.toml`
- Severity: Critical   Confidence: Confirmed
- Category: build/config
- Location: `pyproject.toml:14-21`; `src/bugarena/tournament/providers/dispatcher.py:6`; `scripts/check_api_keys.py:9`
- Found by: python-reviewer, type-design-analyzer, comment-analyzer, code-reviewer   Verified by: architect, Round 2 Dynamic Probe
- **What the bug is:** `dispatcher.py:6` and `scripts/check_api_keys.py:9` directly `import httpx`, yet `pyproject.toml:14-21` omits `httpx` from `dependencies`. Meanwhile `mcp 2.3.0` depends on `httpx2>=2.10.0`, **not** `httpx`.
- **What the bug does:** Installing `bugarena-mcp` (`pip install .` or `pip install -e .`) into a clean Python environment installs `mcp` + `httpx2`, leaving `httpx` absent. Any caller importing `TournamentRunner`, `MultiModelDispatcher`, or running `scripts/check_api_keys.py` crashes with `ModuleNotFoundError: No module named 'httpx'`.
- **How to reproduce:**
  1. Inspect package metadata via `importlib.metadata.requires('bugarena-mcp')` and `importlib.metadata.requires('mcp')`.
  2. Expected: `'httpx>=...'` appears in `bugarena-mcp` dependencies.
  3. Actual: `httpx` is missing from `bugarena-mcp`, and `mcp` requires `'httpx2>=2.10.0'`.
- **Screenshots / evidence:** No screenshot: CLI metadata inspection; captured output from [`./evidence/R2-probe-a-packaging-mcp.txt`](./evidence/R2-probe-a-packaging-mcp.txt):
  ```text
  === DEPENDENCY CHECK ===
  bugarena-mcp requires = ['mcp>=2.0.0', 'pydantic>=2.0.0', 'radon>=6.0.0', 'ruff>=0.5.0', 'pytest>=8.0.0', 'pytest-asyncio>=0.23.0']
  mcp requires = ["anyio>=4.10; python_version >= '3.14'", ..., 'httpx2>=2.10.0', ...]
  ```
- **Recommended fix (NOT applied):** Add `"httpx>=0.27.0"` to `[project].dependencies` in `pyproject.toml` (and consider splitting dev-only dependencies `pytest`, `pytest-asyncio`, `ruff` into `[project.optional-dependencies].dev`).
  ```toml
  # BEFORE (pyproject.toml:14-21)
  dependencies = [
      "mcp>=2.0.0",
      "pydantic>=2.0.0",
      "radon>=6.0.0",
      "ruff>=0.5.0",
      "pytest>=8.0.0",
      "pytest-asyncio>=0.23.0"
  ]

  # AFTER
  dependencies = [
      "httpx>=0.27.0",
      "mcp>=2.0.0",
      "pydantic>=2.0.0",
      "radon>=6.0.0",
      "ruff>=0.5.0",
      "pytest>=8.0.0",
      "pytest-asyncio>=0.23.0",
  ]
  ```
  - *Risks/Side effects:* Increases installed dependency footprint slightly (minimal, as `httpx` is pure Python with existing `anyio`/SSL deps).
  - *Suggested regression tests:* Clean-venv build/install smoke check (`python -m venv ... && pip install . && python -c "import bugarena.tournament.runner"`).
- Related bugs: BUG-007, BUG-022

---

### BUG-008 — Unified Diff Parser Protected-Path Bypasses, Greedy False Positives, Churn Undercount, and Malformed Hunk Acceptance
- Severity: Critical   Confidence: Confirmed
- Category: security
- Location: `src/bugarena/tournament/patch_parser.py:14-60`; `src/bugarena/evaluation/test_runner.py:44-52`
- Found by: code-reviewer, security-reviewer, python-reviewer, silent-failure-hunter, type-design-analyzer, pr-test-analyzer   Verified by: architect, code-architect, Round 2 & 4 Dynamic Probes
- **What the bug is:** `parse_and_validate_patch` (`patch_parser.py:14-60`) has multiple validation defects in the same security boundary:
  1. `DIFF_HEADER_PATTERN` requires `\n` (not `\r?\n`), so CRLF diffs fail altogether, whereas mixed LF/CRLF headers (e.g., first file LF, second file `\r\n`) stop `finditer` at the `\r\n` header, skipping protected-path checks on the second file while `apply_patch` (`splitlines()`) still applies it!
  2. Normalized paths keep `./`, `../`, uppercase Windows characters (`TESTS/...`), and `/dev/null` unnormalized, bypassing `clean_prot in mod or mod in clean_prot`.
  3. Substring matching `clean_prot in mod or mod in clean_prot` (`line 48`) causes false-positive rejections whenever a protected path contains or shares a substring with another file (e.g., editing `calc.py` is rejected when a protected path contains `calc.py`, or `repro/calc.py` shares a suffix).
  4. Does not verify `@@` hunk syntax (accepting header-only diffs), and churn counting uses `line.startswith(("---", ...))` (`line 55`), ignoring deleted SQL comments like `-- comment`.
- **What the bug does:** A competing patch or malicious client can rewrite protected reproduction tests using `./`, `../`, mixed LF/CRLF headers, uppercase paths on Windows, or delete protected files via `/dev/null` to cheat the Red-to-Green gate and win Champion unconditionally; meanwhile valid fixes like `calc.py` are falsely rejected.
- **How to reproduce:**
  1. Call `parse_and_validate_patch` with `protected_paths=["tests/repro/secret_test.py"]` and:
     - `./tests/repro/secret_test.py`, `src/../tests/repro/secret_test.py`, `TESTS/REPRO/SECRET_TEST.PY`, `+++ /dev/null`, or a two-file diff whose second header ends with `\r\n` (LF/CRLF mix).
  2. Call with `--- a/calc.py` when `protected_paths=["tests/repro/test_calc.py"]` or `["tests/calc.py"]` -> rejected!
  3. Call with deleted `-- select 1` -> `lines_deleted=0`.
- **Screenshots / evidence:** No screenshot: headless stdio MCP server/library; captured output from [`./evidence/R2-probe-b2-parser-dup.txt`](./evidence/R2-probe-b2-parser-dup.txt) and [`./evidence/R4-new-edge-probes.txt`](./evidence/R4-new-edge-probes.txt):
  ```text
  dot-slash bypass: ACCEPTED add=1, del=1
  dot-dot bypass: ACCEPTED add=1, del=1
  uppercase win bypass: ACCEPTED add=1, del=1
  del /dev/null bypass: ACCEPTED add=0, del=1
  false positive calc.py: REJECTED (Patch modifies protected test file: 'calc.py')
  deleted -- comment churn undercount: ACCEPTED add=0, del=0
  empty hunk header-only diff accepted: ACCEPTED add=1, del=0
  mixed LF/CRLF ACCEPTED despite modifying protected tests/repro/secret_test.py! add= 2
  secret_test.py in sandbox AFTER apply_patch: 'assert True\n'
  ```
- **Recommended fix (NOT applied):** Parse diffs line-by-line via `splitlines()` (normalizing CRLF and checking both `---` and `+++` headers), resolve paths with `posixpath.normpath` + casefolding on Windows, reject any `..` traversal or `/dev/null` deletion of protected files, check `Exact/Parent` match instead of arbitrary substrings, require at least one `@@ -... +... @@` hunk, and count churn inside hunks only for single `-`/`+` lines (not file headers).
  ```python
  # BEFORE (src/bugarena/tournament/patch_parser.py:44-49)
  if protected_paths:
      for protected in protected_paths:
          clean_prot = protected.replace("\\", "/")
          for mod in modified_files:
              if clean_prot in mod or mod in clean_prot:
                  raise PatchValidationError(f"Patch modifies protected test file: '{mod}'")

  # AFTER
  norm_prot = {os.path.normcase(posixpath.normpath(p.replace("\\", "/"))) for p in (protected_paths or ())}
  for mod in modified_files:  # normalized from both old_file and new_file
      if mod == ".." or mod.startswith("../") or Path(mod).is_absolute():
          raise PatchValidationError(f"Unsafe path in diff: '{mod}'")
      if os.path.normcase(mod) in norm_prot:
          raise PatchValidationError(f"Patch modifies protected test file: '{mod}'")
  ```
  - *Risks/Side effects:* Tighter hunk validation rejects hand-written malformed diffs (such as the buggy example in `SKILL.md:106` — see `BUG-040`).
  - *Suggested regression tests:* Parametrized pytest cases covering `./`, `../`, Windows uppercase, mixed LF/CRLF, `/dev/null`, SQL `--`, and header-only diffs.
- Related bugs: BUG-009, BUG-040, BUG-041, BUG-042

---

### BUG-009 — Custom Unified Diff Applier `EphemeralSandboxManager.apply_patch` Silently Corrupts Files
- Severity: Critical   Confidence: Confirmed
- Category: data-integrity
- Location: `src/bugarena/sandbox/manager.py:62-160`
- Found by: python-reviewer, code-reviewer, silent-failure-hunter, pr-test-analyzer, comment-analyzer   Verified by: architect, Round 2 Dynamic Probe
- **What the bug is:** `apply_patch` / `_apply_hunks` implements an ad-hoc line slicer rather than verifying context lines or running `git apply`:
  1. Pure `-U0` insertions (`old_count == 0` at `line 141`) do `old_start = int(match.group(1)) - 1`, inserting BEFORE line `old_start` instead of AFTER (`actual_start` off by 1 in git unified diff `-U0` semantics).
  2. Multi-file separator blank lines fall into `elif hline.startswith(" ") or not hline: additions.append(...)` (`line 151`), appending blank lines to file 1 instead of ignoring trailing separators before the next `diff --git` / `---`.
  3. Line `111`: `while ... and not lines[i].startswith("--- ")` prematurely terminates a hunk when a deleted SQL comment (`-- comment`) creates a `"--- comment"` diff line!
  4. Context mismatches and out-of-range `@@` line numbers are ignored cleanly via `max(0, ...)` / `min(len(res_lines), ...)` clamping (`lines 155-158`), silently appending hunks to EOF.
  5. `+++ /dev/null` file deletions call `validate_safe_path(sandbox_path, "/dev/null")`, raising `SecurityViolationError`.
- **What the bug does:** Valid competing patches generated with `-U0`, SQL `--` deletions, or multi-file separators silently corrupt source files, scramble line ordering, truncate trailing code, or fail spuriously in evaluation while valid fixes are mis-scored.
- **How to reproduce:**
  1. Apply a `-U0` insertion diff (`@@ -4,0 +5,1 @@\n+5`) to `[1,2,3,4,6]`.
  2. Apply a multi-file diff with a blank line between files, a diff deleting `-- comment` in SQL, an out-of-range hunk `@@ -999,1 +999,1 @@`, and a file deletion diff (`+++ /dev/null`).
  3. Expected: Clean `[1,2,3,4,5,6]`, exact multi-file edits, untouched SQL trailing statement, context-mismatch error, and file removal.
  4. Actual: Output becomes `['1','2','3','4','6','5']`, `['a = 2', '']`, `['SELECT 1;']`, `['a = 2', '', 'CORRUPTED_APPEND']`, and `SecurityViolationError`.
- **Screenshots / evidence:** No screenshot: headless library; captured output from [`./evidence/R2-probe-c-sandbox-runner.txt`](./evidence/R2-probe-c-sandbox-runner.txt):
  ```text
  === BUG-009a: -U0 insertion off-by-one ===
  expected [1..6], actual: ['1', '2', '3', '4', '6', '5']
  === BUG-009b: multi-file blank line corruption ===
  f1 lines: ['a = 2', ''] f2 lines: ['b = 3']
  === BUG-009c: deleted -- comment splits hunk ===
  sql lines: ['SELECT 1;']
  === BUG-009d: context mismatch / out-of-range silent clamp ===
  bad out-of-range f1 lines: ['a = 2', '', 'CORRUPTED_APPEND']
  === BUG-009e: +++ /dev/null deletion error ===
  del /dev/null raised: SecurityViolationError Path traversal detected: '/dev/null' escapes base directory ...
  ```
- **Recommended fix (NOT applied):** Track exact remaining `(old_rem, new_rem)` hunk counts from the `@@ -a,b +c,d @@` header so only hunk body lines (exact `-`, `+`, ` ` prefixes within expected line budget) are parsed, adjust 0-count insertion offset (`old_start = max(0, int(g1))` when `old_count == 0`), verify all `-` and `' '` context lines against `res_lines` raising `ValueError` on mismatch, handle `+++ /dev/null` by unlinking `old_file`, or delegate application to `git apply --check && git apply`.
  ```python
  # BEFORE (src/bugarena/sandbox/manager.py:140-157)
  old_start = int(match.group(1)) - 1  # wrong when old_count == 0 (-U0)
  old_count = int(match.group(2)) if match.group(2) is not None else 1
  ...
  res_lines[actual_start:actual_end] = additions  # no context verification

  # AFTER
  raw_start = int(match.group(1))
  old_count = int(match.group(2)) if match.group(2) is not None else 1
  old_start = raw_start if old_count == 0 else max(0, raw_start - 1)
  # Also match expected old_block == res_lines[actual_start:actual_end] before replacing!
  ```
  - *Risks/Side effects:* Fuzz/offset-shifted LLM diffs whose context doesn't match line numbers exactly will need an explicit fuzz window or be rejected cleanly instead of corrupting files.
  - *Suggested regression tests:* Unit tests for `-U0` insert, `--` SQL comment deletion, multi-file blank line separation, context mismatch error, and `/dev/null` deletion.
- Related bugs: BUG-008, BUG-027, BUG-042

---

### BUG-010 — `validate_red_baseline` Accepts Infrastructure Errors, Empty Test Suites (`exit 5`), and Timeouts as Valid Red Baselines
- Severity: Critical   Confidence: Confirmed
- Category: logic
- Location: `src/bugarena/synthesizer/red_validator.py:41-57`
- Found by: silent-failure-hunter, python-reviewer, pr-test-analyzer, code-reviewer   Verified by: architect, Round 2 Dynamic Probe
- **What the bug is:** `validate_red_baseline` checks only `if outcome.exit_code == 0:` (`line 46`) and marks **any** non-zero exit code — including pytest exit code `2` (`SyntaxError` / `ImportError` / CLI error), `3` (internal error), `4` (usage/option error), `5` (`0 tests collected`), or timeout `exit_code == -1` — as `red_baseline_verified=True`.
- **What the bug does:** Broken or empty reproduction tests pass Stage 2 with `REPRODUCED_RED`. Any candidate patch can then spuriously pass or fail depending on whether it accidentally bypasses an unrelated import/collection error, completely invalidating the Red-to-Green guarantee.
- **How to reproduce:**
  1. Pass empty `test_code = ""` to `validate_red_baseline` (pytest exits with `5`).
  2. Pass infinite loop `def test_hang():\n import time; time.sleep(5)` with `timeout_seconds=0.3` (runner returns `exit_code=-1, timed_out=True`).
  3. Expected: Rejects both with an explicit validation error (only pytest exit code `1` — tests collected and failed without timeout — is a valid Red baseline).
  4. Actual: Both return `ReproTestSpec(..., red_baseline_verified=True)`.
- **Screenshots / evidence:** No screenshot: headless library; captured output from [`./evidence/R2-probe-d-eval-discovery.txt`](./evidence/R2-probe-d-eval-discovery.txt):
  ```text
  === BUG-010: red_validator accepts pytest exit 5 (0 tests) & timeout ===
  empty test verified? True exit_code: 5
  timed-out test verified? True timed_out: True exit_code: -1
  ```
- **Recommended fix (NOT applied):** Require `not outcome.timed_out and outcome.exit_code == 1` (pytest exit code 1 = tests collected cleanly and at least one assertion/runtime error failed), and raise a dedicated error on exit codes 2/3/4/5 or timeouts.
  ```python
  # BEFORE (src/bugarena/synthesizer/red_validator.py:46-50)
  if outcome.exit_code == 0:
      raise ReproductionFalsePositiveError(...)

  # AFTER
  if outcome.timed_out:
      raise RuntimeError(f"Reproduction test '{test_rel_path}' timed out during Red baseline.")
  if outcome.exit_code == 0:
      raise ReproductionFalsePositiveError(...)
  if outcome.exit_code != 1:
      raise ValueError(f"Invalid reproduction test execution (pytest exit {outcome.exit_code}): {outcome.stdout or outcome.stderr}")
  ```
  - *Risks/Side effects:* Tests intentionally reproducing an infinite loop bug (`TimeoutError`) would need an explicit `timeout`-expected mode or internal `signal`/thread timeout inside the test itself.
  - *Suggested regression tests:* Verify `validate_red_baseline` rejects empty test (`exit 5`), `SyntaxError` (`exit 2`), `--unknown-flag` (`exit 4`), and timed-out infinite loops (`timed_out=True`).
- Related bugs: BUG-011, BUG-012, BUG-018

---

### BUG-011 — Synthesized Repro Tests Add `tests/` Instead of Repo Root to `sys.path` and Silently Swallow `ImportError`
- Severity: Critical   Confidence: Confirmed
- Category: error-handling
- Location: `src/bugarena/synthesizer/test_generator.py:59-70`
- Found by: silent-failure-hunter, python-reviewer, comment-analyzer, code-reviewer   Verified by: architect, Round 2 Dynamic Probe
- **What the bug is:** When `bug_reproduce` saves a generated test at `tests/repro/test_issue_xxxxxx.py` (2 levels below repo root, 3 levels total from `__file__`), `test_generator.py:59` injects `Path(__file__).resolve().parent.parent`, which resolves to `tests/` instead of the repository root (`tests/repro/../../` -> `.parent.parent.parent` for `tests/repro/*.py`). Worse, `lines 63-70` wrap both module imports in `try: ... except ImportError: pass`.
- **What the bug does:** Whenever a module cannot be imported directly from `tests/`, `ImportError` is silently swallowed, leaving `clean_func` undefined. Executing the test raises `NameError: name '<clean_func>' is not defined`, which `validate_red_baseline` accepts as `REPRODUCED_RED` (`BUG-010`) and then disqualifies every valid patch with score `0.0`!
- **How to reproduce:**
  1. Generate a repro test via `bug_reproduce` targeting `missing_or_nested_mod.py` (`function_name="calc"`) stored at `tests/repro/test_issue_abc.py`.
  2. Inspect `root_dir` and run `validate_red_baseline`.
  3. Expected: Fails fast on `ImportError` / adds actual repo root to `sys.path`.
  4. Actual: `parent.parent` points to `tests/`, `ImportError` is swallowed, and `NameError` is verified as `REPRODUCED_RED`.
- **Screenshots / evidence:** No screenshot: headless library; captured output from [`./evidence/R2-probe-d-eval-discovery.txt`](./evidence/R2-probe-d-eval-discovery.txt):
  ```text
  === BUG-011: test_generator wrong root_dir & swallowed ImportError -> false NameError RED ===
  uses parent.parent (points to tests/)? True
  missing module NameError verified as RED? True stdout_has_NameError? True
  ```
- **Recommended fix (NOT applied):** Remove `except ImportError: pass` (or raise explicitly so missing modules fail at collection/import time with clear diagnostics, never `NameError`), and pass repo root dynamically (or walk up until finding repo root / add both `parent.parent` and `parent.parent.parent`, though `red_validator` and `test_runner` already set `PYTHONPATH="."`).
  ```python
  # BEFORE (src/bugarena/synthesizer/test_generator.py:59-70)
  root_dir = Path(__file__).resolve().parent.parent
  if str(root_dir) not in sys.path:
      sys.path.insert(0, str(root_dir))
  try:
      from {import_path} import *
  except ImportError:
      pass
  try:
      from {import_path} import {clean_func}
  except ImportError:
      pass

  # AFTER
  for candidate_root in (Path(__file__).resolve().parents[1], Path(__file__).resolve().parents[2]):
      if str(candidate_root) not in sys.path:
          sys.path.insert(0, str(candidate_root))
  from {import_path} import {clean_func}
  ```
  - *Risks/Side effects:* Tests where `call_expr` explicitly imports another module rather than using `suspect.file_path` should avoid generating bogus `from ...` imports for placeholder filenames (`BUG-012`).
  - *Suggested regression tests:* Verify `test_reproduction_*` located at `tests/repro/test_issue_xxxxxx.py` imports `src/pkg/mod.py` cleanly without `PYTHONPATH` hacks and raises `ImportError` (never `NameError`) when the target symbol is missing.
- Related bugs: BUG-010, BUG-012, BUG-024

---

### BUG-012 — `bugarena_autonomous_repair` Silently Falls Back to Non-Existent `"main.py"` When `suspects` Is Empty
- Severity: Critical   Confidence: Confirmed
- Category: error-handling
- Location: `src/bugarena/server.py:381-383`; `src/bugarena/tournament/providers/dispatcher.py:138-139`
- Found by: silent-failure-hunter   Verified by: architect, Round 2 & 5 Dynamic Probes
- **What the bug is:** When `bug_detect` matches no traceback frames (e.g., plain-text error messages, non-Python logs, or non-matching stack frames), `suspects` is `[]`. Instead of returning a structured error or requiring caller-supplied `suspect_file`, `server.py:382-383` falls back to `primary_file = "main.py"` and `primary_func = "target"`. (`dispatcher.py:138-139` similarly falls back to `"src/main.py"`.)
- **What the bug does:** When `call_expr` is omitted, `bug_reproduce` generates `from main import target`, hits `BUG-011`'s `NameError: name 'target' is not defined`, falsely passes Red-baseline verification, runs the entire tournament against `main.py`/`target()`, and disqualifies **every** valid candidate patch fixing the actual source file with score `0.0`.
- **How to reproduce:**
  1. Call `bugarena_autonomous_repair` on a repo containing `src/app.py` (no `main.py`) with `error_log="Completely unrelated error text"` and no `call_expr`.
  2. Expected: Fails fast with a clear `"NO_SUSPECTS_FOUND"` diagnostic instructing the caller to supply a stack trace or target file.
  3. Actual: `TournamentRecord.bug_spec.suspects == []`, repro targets `target in main.py`, fails `NameError`, and disqualifies valid patch `c1` with score `0.0`.
- **Screenshots / evidence:** No screenshot: headless MCP server; captured output from [`./evidence/R5-gap-closure.txt`](./evidence/R5-gap-closure.txt):
  ```text
  === 3. BUG-012: bugarena_autonomous_repair empty suspects -> main.py fallback ===
  stored TournamentRecord.bug_spec.suspects=[]
  no call_expr -> champion=None leaderboard=[{'candidate_id': 'c1', 'repro_passed': False, ..., 'score': 0.0, 'disqualified': True, 'disqualification_reason': 'Reproduction test failed: Patch did not resolve the defect.'}]
  no call_expr repro header: ['"""Automated bug reproduction test case.', 'Bug description: f returns wrong value', 'Target function: target in main.py', '"""', '', 'import sys']
  ```
- **Recommended fix (NOT applied):** Fail fast in `bugarena_autonomous_repair` if `not suspects and not call_expr` (or add an optional `suspect_file` parameter). Do not fabricate `"main.py"`/`"target"`.
  ```python
  # BEFORE (src/bugarena/server.py:381-383)
  suspects = detect_res["suspects"]
  primary_file = suspects[0]["file_path"] if suspects else "main.py"
  primary_func = suspects[0]["function_name"] if suspects else "target"

  # AFTER
  suspects = detect_res["suspects"]
  if not suspects and not call_expr:
      return {
          "status": "NO_SUSPECTS_FOUND",
          "error": "Could not localize suspect file from error_log; provide call_expr or stack trace.",
          "bug_id": detect_res["bug_id"],
      }
  primary_file = suspects[0]["file_path"] if suspects else ""
  primary_func = suspects[0]["function_name"] if suspects else "target"
  ```
  - *Risks/Side effects:* Callers passing non-traceback logs without `call_expr` will receive an actionable error instead of a deceptive 0-score tournament.
  - *Suggested regression tests:* Test `bugarena_autonomous_repair` with empty traceback log and no `call_expr` returns `NO_SUSPECTS_FOUND`.
- Related bugs: BUG-010, BUG-011, BUG-026

---

### BUG-013 — `PatchEvaluator` Broken Regression, Complexity, and Mutation Scoring Gates
- Severity: Critical   Confidence: Confirmed
- Category: logic
- Location: `src/bugarena/evaluation/test_runner.py:78-119`; `src/bugarena/evaluation/scorer.py:36-58`; `README.md:65-75`; `.agents/skills/bugarena-repair/SKILL.md:71-76`
- Found by: python-reviewer, code-reviewer, silent-failure-hunter, performance-optimizer, comment-analyzer   Verified by: architect, Round 2 & 4 Dynamic Probes
- **What the bug is:** Multiple scoring & gating failures combine in `PatchEvaluator` and `compute_patch_score`:
  1. `test_runner.py:100` hardcodes `delta_cc = 0` instead of calling `calculate_cyclomatic_delta` (`ast_metrics.py:47`), rendering `Q_complexity` constant `10.0`.
  2. `test_runner.py:93-97` hardcodes `regressions = 0` or `1`, hardcodes `total_tests = 1`, ignores `reg_outcome.timed_out`, and treats `"no tests ran" in reg_outcome.stdout.lower()` as 0 regressions even though on `pytest 9.2.0` a **missing** `tests/` directory (exit code `4`) still prints `"\nno tests ran in 0.02s\n"` to `stdout`!
  3. No AST/syntax gate checks unimported modified `.py` files (`README.md:68` claims "Syntax & AST Gate"), so a patch breaking syntax in an untested file (`src/other.py`) scores `99.4` and beats clean patches (`score=97.3`).
  4. `scorer.py:55` assigns `1.0 * 5.0 = 5.0` full mutation points when `mutation_kill_ratio is None`, giving an unmeasured patch (`99.7`) a higher score than a patch with `0.9` measured kill ratio (`99.2`)! Additionally, `scorer.py:52` hardcodes `30.0` instead of scaling by `regressions/total` when `total_regressions > 0`, and never validates negative `regressions_count` or `total_regressions == 0`.
- **What the bug does:** Syntactically broken patches can win Champion (`score=99.4`), bloated complex patches receive zero complexity penalty, repositories lacking `tests/` receive full 30/30 regression credit, and unmeasured mutation patches outscore tested ones.
- **How to reproduce:**
  1. Call `PatchEvaluator` on a repo lacking `tests/`, or a repo with `tests/test_calc.py` + `src/other.py` where candidate `break_unused_syntax` introduces `SyntaxError` in `src/other.py` and `bloated_cc` adds deep branching.
  2. Call `compute_patch_score("p1", True, 0, 1, 1, 0, mutation_kill_ratio=None)` vs `mutation_kill_ratio=0.9`.
  3. Expected: `break_unused_syntax` is disqualified by syntax gate, `bloated_cc` receives `cc_delta > 0`, missing `tests/` yields reduced/flagged score, and `mutation_kill_ratio=None` does not beat `0.9`.
  4. Actual: `break_unused_syntax` wins Champion (`score=99.4`), `bloated_cc` gets `cc_delta=0`, missing `tests/` scores `99.4`, and `None` mutation scores `99.7 > 99.2`.
- **Screenshots / evidence:** No screenshot: headless library; captured output from [`./evidence/R2-probe-d-eval-discovery.txt`](./evidence/R2-probe-d-eval-discovery.txt) and [`./evidence/R2-probe-f-eval-runner-flags.txt`](./evidence/R2-probe-f-eval-runner-flags.txt):
  ```text
  no tests/ repo -> champ: c_fix eval: {'candidate_id': 'c_fix', 'repro_passed': True, 'regressions_count': 0, 'total_regressions_checked': 1, 'diff_churn': 2, 'cyclomatic_delta': 0, 'mutation_kill_ratio': None, 'score': 99.4, 'disqualified': False, 'disqualification_reason': None}
  mutation_kill_ratio=None score=99.7 > 0.9 measured score=99.2
  break_unused_syntax -> disqualified: False reg: 0 total: 1 cc_delta: 0 score: 99.4
  bloated_cc -> disqualified: False reg: 0 total: 1 cc_delta: 0 score: 97.3
  champion: break_unused_syntax
  ```
- **Recommended fix (NOT applied):** Parse all modified `.py` files with `ast.parse` (disqualifying `SyntaxError`), compute `calculate_cyclomatic_delta(orig, patched)` across modified `.py` files, parse actual passed/failed/error counts from `pytest` (disqualifying timeouts and collection/missing-suite failures when regression checks are expected, or separating `pytest.ExitCode` states), and award `0.0` (not `5.0`) when `mutation_kill_ratio is None`.
  ```python
  # BEFORE (src/bugarena/evaluation/test_runner.py:93-100 & scorer.py:55)
  regressions = 0
  total_tests = 1
  if reg_outcome.exit_code != 0 and "no tests ran" not in reg_outcome.stdout.lower():
      regressions = 1
  delta_cc = 0
  # scorer.py:
  q_mutation = (mutation_kill_ratio if mutation_kill_ratio is not None else 1.0) * 5.0

  # AFTER
  for rel in modified_py_files:
      orig_src = (base_repo / rel).read_text(encoding="utf-8", errors="replace")
      new_src = (sandbox_path / rel).read_text(encoding="utf-8", errors="replace")
      ast.parse(new_src, filename=rel)  # Disqualify SyntaxError
      delta_cc += calculate_cyclomatic_delta(orig_src, new_src)
  if reg_outcome.timed_out or reg_outcome.exit_code == 2:
      regressions = 1  # Disqualify timed-out or collection-error runs
  # scorer.py:
  q_mutation = (mutation_kill_ratio if mutation_kill_ratio is not None else 0.0) * 5.0
  ```
  - *Risks/Side effects:* Scores across all un-mutated runs drop by 5 points maximum (from 99.x to 94.x), which existing tests checking `assert score > 90.0` still pass (`surgical_eval` scores ~94.4 at `churn=2, cc=1`).
  - *Suggested regression tests:* Add unit tests where a patch introduces `SyntaxError` in an unimported `.py` file, increases CC, or skips missing `tests/`.
- Related bugs: BUG-009, BUG-027, BUG-028, BUG-040

---

### BUG-014 — `FixReport` Schema Mismatch Silently Drops Champion Data and `TournamentRecord.report_file_path` Is Never Populated
- Severity: Critical   Confidence: Confirmed
- Category: data-integrity
- Location: `src/bugarena/server.py:281-287,418-429`; `src/bugarena/models/report.py:9-19`; `src/bugarena/models/tournament.py:42`
- Found by: type-design-analyzer, pr-test-analyzer, python-reviewer, code-reviewer, silent-failure-hunter   Verified by: architect, Round 2 & 5 Checks
- **What the bug is:** `generate_fix_report` instantiates `FixReport(tournament_id=..., champion_candidate_id=tournament.champion_candidate_id, ...)` (`server.py:281-287`), whereas `FixReport` (`models/report.py:14-19`) defines `champion_patch: CandidatePatch | None = None` and `champion_eval: PatchEvaluation | None = None` — and **no** `champion_candidate_id` field! Because `FixReport` has default `extra="ignore"`, Pydantic silently discards `champion_candidate_id` and leaves `champion_patch=None` and `champion_eval=None`. Separately, `TournamentRecord.report_file_path` (`models/tournament.py:42`) is never populated by either `generate_fix_report` or `bugarena_autonomous_repair`.
- **What the bug does:** Downstream MCP consumers inspecting `res["report"]["champion_patch"]` or `res["report"]["champion_eval"]` always receive `None` even when a winning champion exists and is present in Markdown.
- **How to reproduce:**
  1. Run a successful tournament yielding a champion (`champion_candidate_id != None`), then call `generate_fix_report(t_id, format="json")`.
  2. Inspect `res["report"]` and `srv._TOURNAMENT_REGISTRY[t_id].report_file_path`.
  3. Expected: `champion_patch` and `champion_eval` hold the winning `CandidatePatch` and `PatchEvaluation` objects, and `TournamentRecord.report_file_path` records `saved_path`.
  4. Actual: `champion_patch is None` and `champion_eval is None`.
- **Screenshots / evidence:** No screenshot: headless MCP server; captured output from [`./evidence/R2-probe-e-server-dispatcher.txt`](./evidence/R2-probe-e-server-dispatcher.txt):
  ```text
  BUG-014 FixReport dict keys: ['tournament_id', 'champion_patch', 'champion_eval', 'summary_markdown', 'git_patch_diff', 'report_file_path']
  BUG-014 champion_patch is None? True champion_eval is None? True
  ```
- **Recommended fix (NOT applied):** Look up `champion_obj` (`CandidatePatch`) and `champion_eval_obj` (`PatchEvaluation`) in `generate_fix_report`, pass them into `FixReport(champion_patch=..., champion_eval=...)`, add `ConfigDict(frozen=True, extra="forbid")` across models (`BUG-023`), and update the stored `TournamentRecord.report_file_path`.
  ```python
  # BEFORE (src/bugarena/server.py:281-287)
  fix_report = FixReport(
      tournament_id=tournament.tournament_id,
      champion_candidate_id=tournament.champion_candidate_id,
      summary_markdown=report_md,
      git_patch_diff=champion_patch or "",
      report_file_path=str(saved_path),
  )

  # AFTER
  champ_obj = next((c for c in tournament.candidates if c.candidate_id == tournament.champion_candidate_id), None)
  champ_eval = next((e for e in tournament.evaluations if e.candidate_id == tournament.champion_candidate_id), None)
  fix_report = FixReport(
      tournament_id=tournament.tournament_id,
      champion_patch=champ_obj,
      champion_eval=champ_eval,
      summary_markdown=report_md,
      git_patch_diff=champ_obj.diff if champ_obj else "",
      report_file_path=str(saved_path),
  )
  ```
  - *Risks/Side effects:* Adding `extra="forbid"` to `FixReport` will raise `ValidationError` on any legacy caller passing invalid extra kwargs (intended fail-fast behavior).
  - *Suggested regression tests:* Assert `res["report"]["champion_patch"]["candidate_id"] == champion_id` and `res["report"]["champion_eval"]["score"] > 0` in `test_reporting_and_server.py`.
- Related bugs: BUG-023, BUG-033

---

### BUG-016 — LLM Dispatcher Misroutes Models, Overwrites Explicit `model_override`, Mis-Targets Ollama/DeepSeek, and Crashes on `None` Content / Reasoning Parameters
- Severity: Critical   Confidence: Confirmed
- Category: logic
- Location: `src/bugarena/tournament/providers/dispatcher.py:19-71,164-348`
- Found by: python-reviewer, type-design-analyzer, pr-test-analyzer, silent-failure-hunter, comment-analyzer, code-reviewer   Verified by: architect, Round 2 MockTransport Probe
- **What the bug is:** `MultiModelDispatcher` and `get_recommended_model_for_persona` contain multiple confirmed routing and payload defects:
  1. `DEFENSIVE_GUARDIAN` (`lines 40-47`) ignores `DEEPSEEK_API_KEY` and falls back to `"gemma-4-26b-a4b-it"`, even when only DeepSeek/OpenAI keys exist.
  2. `generate_patch` (`lines 177-180`) checks `"llama" in model.lower()` BEFORE `"ollama" in model.lower()`, so `"ollama/llama3.2"` routes to Groq (`https://api.groq.com/openai/v1/chat/completions`) instead of local Ollama (`localhost:11434`).
  3. `_call_gemini` (`line 191`) and `_call_groq` (`line 275`) silently clobber valid explicit `model_override` names (`"gemini-2.0-flash"` -> `"gemma-4-26b-a4b-it"`, `"llama-3.3-70b-versatile"` -> `"qwen/qwen3.8-27b"`).
  4. `_call_anthropic` (`lines 321-325`) checks only `gemini`/`gemma` before falling back to `_call_openai`, routing Groq and DeepSeek fallback models (`"qwen/qwen3.8-27b"`, `"deepseek-reasoner"`) to OpenAI and failing with `"Missing OPENAI_API_KEY"`.
  5. `_call_openai`, `_call_deepseek`, and `_call_groq` call `extract_diff_and_explanation(text)` where `text = data["choices"][0]["message"]["content"]` can be JSON `null` (`None` on tool calls / refusal / reasoning-only messages), raising uncaught `AttributeError: 'NoneType' object has no attribute 'strip'`, while `_call_openai` unconditionally sends `temperature=0.2` to reasoning models like `o3-mini` (`line 55` vs `line 227`), which reject `temperature`.
  6. *Note (Model IDs & Endpoints):* Default model IDs (`"qwen/qwen3.8-27b"`, `"gemma-4-26b-a4b-it"`, `"o3-mini"`, `"deepseek-reasoner"`) and live provider endpoints were not queried online during this read-only audit per Hard Rule 5 (see `UNV-003` in Appendix B).
- **What the bug does:** Multi-agent repairs fail on local Ollama `llama*` models, raise unhandled `AttributeError` crashes on `content: null` API responses, break `o3-mini` OpenAI calls, silently disregard caller-specified `model_override` values, and fail DeepSeek-only/Groq-only fallback paths.
- **How to reproduce:**
  1. Unset all keys except `DEEPSEEK_API_KEY`, call `get_recommended_model_for_persona(PersonaType.DEFENSIVE_GUARDIAN)`.
  2. Mock `httpx.AsyncClient.post` and call `dispatcher.generate_patch(..., model_override="ollama/llama3.2")` returning `{"choices":[{"message":{"content":None}}]}`.
  3. Unset `ANTHROPIC_API_KEY`, set only `GROQ_API_KEY`, call `_call_anthropic(...)`.
  4. Expected: `DEFENSIVE_GUARDIAN` uses DeepSeek; `"ollama/llama3.2"` hits `localhost:11434`; `content: None` returns `("", error)` cleanly; `_call_anthropic` delegates via `generate_patch`.
  5. Actual: `DEFENSIVE_GUARDIAN` picks `"gemma-4-26b-a4b-it"`, `"ollama/llama3.2"` hits `api.groq.com` then crashes `AttributeError`, and `_call_anthropic` errors `"Missing OPENAI_API_KEY"`.
- **Screenshots / evidence:** No screenshot: headless library; captured `httpx.MockTransport` output from [`./evidence/R2-probe-e-server-dispatcher.txt`](./evidence/R2-probe-e-server-dispatcher.txt):
  ```text
  DEFENSIVE_GUARDIAN with only DEEPSEEK+GROQ (unset GROQ): gemma-4-26b-a4b-it
  ollama/llama3.2 + null content CRASHED: AttributeError 'NoneType' object has no attribute 'strip' seen_urls: ['https://api.groq.com/openai/v1/chat/completions']
  _call_anthropic with GROQ_API_KEY fallback returned: ('', 'Missing OPENAI_API_KEY environment variable') seen_urls: []
  ```
- **Recommended fix (NOT applied):** Check `"ollama/"` prefix before `"llama"` in `generate_patch`; remove `model_override` rewriting in `_call_gemini`/`_call_groq` (only map `"default"`/`"gemini"`/`"groq"`); add `DEEPSEEK` to `DEFENSIVE_GUARDIAN`; delegate `_call_anthropic` fallback through `self.generate_patch` (guarding infinite recursion via `has_claude`); guard `text or ""` in all `_call_*` extractors; and omit `temperature` for `o3-`/`o1-` reasoning models.
  ```python
  # BEFORE (src/bugarena/tournament/providers/dispatcher.py:173-180,191,275)
  elif "groq" in model.lower() or "llama" in model.lower() or "qwen" in model.lower():
      return await self._call_groq(model, system_msg, prompt)
  elif "ollama" in model.lower() or "localhost" in model.lower():
      return await self._call_ollama(model, system_msg, prompt)
  ...
  clean_model = "gemma-4-26b-a4b-it" if model.lower() in ("gemini", "default", "gemini-2.0-flash") else model

  # AFTER
  if model.lower().startswith("ollama/") or "localhost" in model.lower():
      return await self._call_ollama(model, system_msg, prompt)
  ...
  clean_model = "gemma-4-26b-a4b-it" if model.lower() in ("gemini", "default") else model
  ```
  - *Risks/Side effects:* Existing callers expecting `"gemini-2.0-flash"` to auto-translate to `"gemma-4-26b-a4b-it"` will call `"gemini-2.0-flash"` literally as requested.
  - *Suggested regression tests:* Add `httpx.MockTransport` tests for `ollama/llama3.2`, explicit `model_override`, `content: None`, `o3-mini` payload shape, `DEFENSIVE_GUARDIAN` + `DEEPSEEK_API_KEY`, and `_call_anthropic` with `GROQ_API_KEY`.
- Related bugs: BUG-020, BUG-022, BUG-035, BUG-038

---

> **Severity Tier: High (22 Bugs — `BUG-007`, `BUG-015`, `BUG-017`..`BUG-029`, `BUG-031`, `BUG-032`, `BUG-035`, `BUG-037`..`BUG-039`, `BUG-042`)**

### BUG-007 — Missing `__init__.py` in `personas/` Subpackage and Incomplete Package Exports
- Severity: High   Confidence: Confirmed
- Category: build/config
- Location: `src/bugarena/tournament/personas/base.py` (no `__init__.py` in `src/bugarena/tournament/personas/`); `src/bugarena/reporting/__init__.py:1-5` (contrast with complete `src/bugarena/discovery/__init__.py:1-11`)
- Found by: python-reviewer, type-design-analyzer   Verified by: architect, Round 2 Dynamic Probe
- **What the bug is:** `src/bugarena/tournament/personas/` lacks an `__init__.py` file, and `pyproject.toml` uses default `setuptools.build_meta` without `find_namespace_packages`. Additionally, `reporting/__init__.py` exports only `format_markdown_report`, omitting `format_bug_diagnostic_markdown` and `save_markdown_report`.
- **What the bug does:** Building a non-editable wheel (`pip wheel .` / `pip install .`) excludes `bugarena/tournament/personas/base.py`, causing `dispatcher.py:11` (`from bugarena.tournament.personas.base import get_persona_prompt`) to fail with `ModuleNotFoundError` when installed outside editable mode.
- **How to reproduce:**
  1. Check `Path("src/bugarena/tournament/personas/__init__.py").exists()`.
  2. Expected: `True` (all subpackages are regular Python packages included in wheel builds).
  3. Actual: `False`; `personas/` is missing `__init__.py`.
- **Screenshots / evidence:** No screenshot: headless Python package; captured output from [`./evidence/R2-probe-a-packaging-mcp.txt`](./evidence/R2-probe-a-packaging-mcp.txt):
  ```text
  === PERSONAS PACKAGE CHECK ===
  personas/__init__.py exists? False
  ```
- **Recommended fix (NOT applied):** Add `src/bugarena/tournament/personas/__init__.py` re-exporting `PERSONA_PROMPTS` and `get_persona_prompt`, and complete `__all__` in `src/bugarena/reporting/__init__.py`.
  ```python
  # NEW FILE (src/bugarena/tournament/personas/__init__.py)
  """Agent persona prompt definitions."""
  from bugarena.tournament.personas.base import PERSONA_PROMPTS, get_persona_prompt
  __all__ = ["PERSONA_PROMPTS", "get_persona_prompt"]

  # BEFORE (src/bugarena/reporting/__init__.py:1-5)
  from bugarena.reporting.markdown_formatter import format_markdown_report
  __all__ = ["format_markdown_report"]

  # AFTER (src/bugarena/reporting/__init__.py)
  from bugarena.reporting.markdown_formatter import (
      format_bug_diagnostic_markdown,
      format_markdown_report,
      save_markdown_report,
  )
  __all__ = ["format_bug_diagnostic_markdown", "format_markdown_report", "save_markdown_report"]
  ```
  - *Risks/Side effects:* Minimal; ensures built wheels mirror editable installs cleanly.
  - *Suggested regression tests:* Run `python -m build --wheel` / inspect wheel ZIP entries in CI to verify `bugarena/tournament/personas/base.py` is packaged.
- Related bugs: BUG-006, BUG-022

---

### BUG-015 — `run_sandboxed_command` Drops Invalid Byte Output in `_readerthread`, Lacks Explicit Encoding Strategy, and Risks Pipe Deadlock / Orphan Child Trees on POSIX
- Severity: High   Confidence: Confirmed
- Category: concurrency
- Location: `src/bugarena/sandbox/runner.py:41-86`
- Found by: performance-optimizer, python-reviewer, silent-failure-hunter, security-reviewer   Verified by: architect, Round 2 Dynamic Probe
- **What the bug is:** `subprocess.Popen(..., text=True)` (`runner.py:46`) omits `encoding="utf-8", errors="replace"`, so CPython's internal `_readerthread` uses `locale.getpreferredencoding()` and raises `UnicodeDecodeError` internally on invalid bytes (silently truncating `stdout`/`stderr` to `""`), or crashes outright on non-UTF-8 OS locales (e.g., `cp1252` hosts emitting `✓`). On POSIX (`lines 72-73`), `proc.kill()` targets only the direct child PID without process-group isolation (`start_new_session=True` + `os.killpg`), and `proc.communicate()` after timeout (`line 74`) without a bounded second timeout can hang if grandchildren inherit pipes (`UNV-001` in Appendix B). *(Downgraded from Critical to High in Round 2/5 after confirming Python 3.14 on this Windows host uses UTF-8 for valid UTF-8 characters, while invalid byte sequences still drop output silently.)*
- **What the bug does:** Child test runners emitting non-UTF-8 bytes (e.g., latin-1 test data, binary dumps) lose all captured `stdout`/`stderr` silently (`stdout=''`, `stderr=''`), breaking downstream diagnostic triage and regression inspection; on POSIX, timed-out test subprocesses can leak orphaned worker processes holding sandbox files/ports.
- **How to reproduce:**
  1. Run `run_sandboxed_command(workspace, [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\x81\\x82bad\\n')"])`.
  2. Expected: Valid text plus replacement character (e.g., `'\ufffd\ufffdbad\n'`) is captured without silent loss.
  3. Actual: `stdout == ''` and `stderr == ''` while `exit_code == 0`.
- **Screenshots / evidence:** No screenshot: headless subprocess runner; captured output from [`./evidence/R2-probe-c2-pytest-bytes-ollama.txt`](./evidence/R2-probe-c2-pytest-bytes-ollama.txt):
  ```text
  === CHECK BUG-015 invalid locale/utf-8 bytes in Popen ===
  default preferredencoding: utf-8 runner stdout test:
  raw bytes outcome: exit_code=0 stdout='' stderr='' duration_seconds=0.175 timed_out=False
  ```
- **Recommended fix (NOT applied):** Add `encoding="utf-8", errors="replace"` to `subprocess.Popen`, use `start_new_session=True` + `os.killpg` on POSIX timeouts, and pass a short bounded timeout to post-kill `communicate(timeout=5)` with pipe cleanup fallback.
  ```python
  # BEFORE (src/bugarena/sandbox/runner.py:41-49)
  proc = subprocess.Popen(
      clean_args, cwd=str(ws_path),
      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
      text=True, env=base_env, shell=False,
  )

  # AFTER
  proc = subprocess.Popen(
      clean_args, cwd=str(ws_path),
      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
      text=True, encoding="utf-8", errors="replace",
      start_new_session=(os.name != "nt"), env=base_env, shell=False,
  )
  ```
  - *Risks/Side effects:* Invalid UTF-8 bytes become U+FFFD (`\ufffd`) instead of raw bytes; test assertions needing exact binary output would need binary capture mode.
  - *Suggested regression tests:* Verify `b"\x81\x82hello\n"` returns `"hello"` with replacement chars instead of `stdout == ""`.
- Related bugs: BUG-017, BUG-019, BUG-030

---

### BUG-017 — `EphemeralSandboxManager` Leaks Temp Directories on Windows Read-Only Files, Omits Build Excludes, and Dereferences Symlinks
- Severity: High   Confidence: Confirmed
- Category: security
- Location: `src/bugarena/sandbox/manager.py:27-60`
- Found by: security-reviewer, performance-optimizer, silent-failure-hunter, pr-test-analyzer   Verified by: architect, Round 2 Dynamic Probe
- **What the bug is:** Three related bugs in `EphemeralSandboxManager.create_sandbox`:
  1. `shutil.rmtree(temp_dir, ignore_errors=True)` (`line 60`) fails silently on Windows when a copied repo contains any file with the `FILE_ATTRIBUTE_READONLY` bit (e.g., vendor assets or `.git`-adjacent artifacts), leaking full repository copies inside `$env:TEMP`.
  2. `ignore_patterns` (`lines 30-50`) ignores `.venv`, `.git`, `node_modules`, and `.env*` at top/subdirectory basenames, but omits `dist/`, `build/`, `htmlcov/`, `.tox/`, `reports/`, `*.egg-info/`, `*.sqlite*`, causing bloated temp copies and recursive report bloat.
  3. `shutil.copytree` uses default `symlinks=False` (`lines 52-57`), which dereferences symlinks inside the repository and copies external target files directly into the sandbox *(verified statically by inspection; runtime creation blocked on unprivileged Windows by `WinError 1314`, recorded as `UNV-002` in Appendix B)*.
- **What the bug does:** Repeated tournaments leak megabytes/gigabytes of orphaned sandbox copies in the host temp directory on Windows, copy unintended build/report artifacts per candidate evaluation, and risk pulling outside-repo files into sandboxes when symlinks exist inside a target repository.
- **How to reproduce:**
  1. Create a temp repo containing a file marked read-only (`os.chmod(path, stat.S_IREAD)`).
  2. Enter and exit `with EphemeralSandboxManager(repo).create_sandbox() as sb:` and test `sb.exists()`.
  3. Expected: `sb.exists()` is `False` (read-only permissions cleared during cleanup).
  4. Actual: `sb.exists()` is `True` — the temp directory and file remain permanently on disk.
- **Screenshots / evidence:** No screenshot: headless sandbox manager; captured output from [`./evidence/R2-probe-c-sandbox-runner.txt`](./evidence/R2-probe-c-sandbox-runner.txt):
  ```text
  === BUG-017: rmtree leaks read-only files on Windows ===
  sandbox leaked on read-only file? True
  ```
- **Recommended fix (NOT applied):** Pass `symlinks=True` (or reject symlinks pointing outside `base_repo_path`) to `shutil.copytree`, expand `ignore_patterns` (`dist`, `build`, `reports`, `.tox`, `.eggs`, `*.egg-info`), and pass an `onexc` handler to `shutil.rmtree` clearing `stat.S_IWRITE` before retrying unlink.
  ```python
  # BEFORE (src/bugarena/sandbox/manager.py:52-60)
  shutil.copytree(self.base_repo_path, temp_dir, dirs_exist_ok=True, ignore=ignore_patterns)
  yield temp_dir
  finally:
  shutil.rmtree(temp_dir, ignore_errors=True)

  # AFTER
  def _clear_readonly(func, path, _exc):
      os.chmod(path, stat.S_IWRITE)
      func(path)
  shutil.copytree(self.base_repo_path, temp_dir, dirs_exist_ok=True, symlinks=True, ignore=ignore_patterns)
  yield temp_dir
  finally:
  shutil.rmtree(temp_dir, onexc=_clear_readonly)
  ```
  - *Risks/Side effects:* `symlinks=True` leaves broken relative symlinks broken or raises if Windows lacks symlink privileges (`copytree` needs `symlinks=True` fallback check or explicit symlink filtering in `ignore_patterns`).
  - *Suggested regression tests:* Test `create_sandbox` cleans up directories containing read-only files on Windows and skips `dist/`, `build/`, `reports/`.
- Related bugs: BUG-005, BUG-037, BUG-043

---

### BUG-018 — Pytest CLI Option Injection (`--version`/`--junitxml`), Secret Env Leakage (`MYSQL_PWD`/`PYTHONSTARTUP`/`GH_PAT`/`HTTP_PROXY`), and `-c` Bypass in `sandbox/security.py`
- Severity: High   Confidence: Confirmed
- Category: security
- Location: `src/bugarena/sandbox/security.py:12-33,63-99`; `src/bugarena/synthesizer/red_validator.py:41-43`; `src/bugarena/evaluation/test_runner.py:71-89`
- Found by: security-reviewer, python-reviewer   Verified by: architect, Round 2 & 3 Dynamic Probes
- **What the bug is:** Three related security-control gaps in command execution & validation:
  1. `red_validator.py:41` and `test_runner.py:71,80` pass `repro_spec.test_file_path` or `regression_test_dir` directly to `pytest` without a `--` end-of-options separator (`pytest -- ...`) or checking `not path.startswith("-")`.
  2. `sanitize_env` (`security.py:12-33,63-75`) uses blocklists missing `MYSQL_PWD`, `PYTHONSTARTUP`, `LD_PRELOAD`, `GH_PAT`, `HTTP_PROXY`, `HTTPS_PROXY`, `CI_JOB_JWT`, and `PGPASSFILE`, allowing secret leakage and Python startup code injection into subprocesses.
  3. `sanitize_command_args` (`security.py:78-99`) skips all metacharacter checks after `"-c"` (`bash -c "id; cat /etc/passwd"`) and still allows newlines `\n`, `;`-free subshells if `-c` is present, or Python `-m`/`python -c` payloads unchecked.
- **What the bug does:** Passing `repro_test_file="--version"` to `evaluate_patches` runs `pytest --version -q` (returning `exit_code=0`, bypassing the reproduction test check completely and crowning a `dummy_noop` patch with score `99.4` without ever creating `--version` on disk!), or `--junitxml=...` writes arbitrary XML inside the sandbox; `MYSQL_PWD`, `GH_PAT`, `HTTP_PROXY`, and `PYTHONSTARTUP` leak into untrusted test runs.
- **How to reproduce:**
  1. Call `evaluate_patches(repo, tid, repro_test_file="--version", repro_code="assert False")` with a no-op patch.
  2. Call `sanitize_env({"MYSQL_PWD":"pw", "PYTHONSTARTUP":"/tmp/evil.py", "GH_PAT":"ghp_123", "HTTP_PROXY":"http://..."})` and `sanitize_command_args(["bash", "-c", "id; cat /etc/passwd"])`.
  3. Expected: Option-prefixed test paths raise `SecurityViolationError`/`ValueError`; secret env vars and `PYTHONSTARTUP` are stripped; `-c` exemption applies only to approved interpreters or uses allowlists.
  4. Actual: `evaluate_patches("--version")` crowns `dummy_noop` with score `99.4`; `MYSQL_PWD`, `PYTHONSTARTUP`, `GH_PAT`, and `HTTP_PROXY` leak cleanly; `bash -c 'id; cat /etc/passwd'` passes validation.
- **Screenshots / evidence:** No screenshot: headless security layer; captured outputs from [`./evidence/R2-probe-b2-parser-dup.txt`](./evidence/R2-probe-b2-parser-dup.txt), [`./evidence/R2-probe-f-eval-runner-flags.txt`](./evidence/R2-probe-f-eval-runner-flags.txt), and [`./evidence/R3-deep-edge-probes.txt`](./evidence/R3-deep-edge-probes.txt):
  ```text
  sanitize_env leaked keys: ['MYSQL_PWD', 'PYTHONSTARTUP', 'GH_PAT', 'HTTP_PROXY']
  sanitize_command_args bash -c: ['bash', '-c', 'id; cat /etc/passwd']
  validate_red_baseline interpreted --version as pytest CLI flag and passed (0 tests ran)!
  evaluate_patches('--version') champion: dummy_noop score: 99.4 created '--version' file inside repo?: False
  ```
- **Recommended fix (NOT applied):** Insert `"--"` before path arguments in all `pytest` invocations, reject `target_path.startswith("-")` in `agent_fix_tournament`/`evaluate_patches`, switch `sanitize_env` to a minimal safe allowlist (`PATH`, `SYSTEMROOT`, `PATHEXT`, `COMSPEC`, `TEMP`, `TMP`, `HOME`, `LANG`, `LC_ALL`, `PYTHONPATH`), and restrict `sanitize_command_args` executable names (`sys.executable`) rather than blindly allowing any `-c`.
  ```python
  # BEFORE (src/bugarena/evaluation/test_runner.py:71 & sandbox/security.py:67-72)
  args=[self.python_executable, "-m", "pytest", repro_spec.test_file_path, "-q"]

  # AFTER
  if repro_spec.test_file_path.startswith("-"):
      raise SecurityViolationError(f"Invalid test path starting with '-': {repro_spec.test_file_path!r}")
  args=[self.python_executable, "-m", "pytest", "-q", "--", repro_spec.test_file_path]
  ```
  - *Risks/Side effects:* Test suites relying on custom non-allowlisted environment variables will need explicit `env_override` allowlisting.
  - *Suggested regression tests:* Verify `evaluate_patches(..., "--version", ...)` fails validation, and `MYSQL_PWD`/`PYTHONSTARTUP`/`GH_PAT`/`HTTP_PROXY` are stripped by `sanitize_env`.
- Related bugs: BUG-001, BUG-002, BUG-010, BUG-029

---

### BUG-019 — `load_env_file` Ignores Precedence of Explicit `dotenv_path`, Crashes on UTF-16 `.env`, and Mis-Parses Quotes / `export` / `#` / Empty `KEY=`
- Severity: High   Confidence: Confirmed
- Category: security
- Location: `src/bugarena/config.py:7-36`; `src/bugarena/server.py:29`; `.env.example:5,8,11,14`
- Found by: security-reviewer, python-reviewer, silent-failure-hunter   Verified by: architect, code-architect, Round 2 & 4 Dynamic Probes
- **What the bug is:** `load_env_file` (`config.py:7-36`) suffers from five combined config defects:
  1. When an explicit `dotenv_path` is supplied (`lines 13-22`), it still unconditionally appends and parses `project_root/.env`, `Path.cwd() / ".env"`, and `~/.gemini/.env`, causing untrusted CWD `.env` files to inject variables even during isolated calls!
  2. `server.py:29` invokes `load_env_file()` at import time from untrusted CWD (`Path.cwd() / ".env"`), allowing untrusted checked-out repositories to inject `OPENAI_API_KEY`/`GROQ_API_KEY` or other process env vars.
  3. `target.read_text(encoding="utf-8")` (`line 26`) catches only `OSError` (`line 35`), crashing with uncaught `UnicodeDecodeError` on Windows UTF-16LE `.env` files (common from Notepad/PowerShell redirection).
  4. Line parsing (`lines 30-34`) does not strip `export ` prefixes (`export KEY=val`), preserves inline `# comments` inside unquoted values (`"val # inline comment"`), uses `.strip("'\"")` which corrupts nested quotes, and stores empty placeholder values (`KEY=` from `.env.example`) as `os.environ[key] = ""`! Because `line 33` checks `key not in os.environ`, a blank placeholder blocks valid fallback files (`~/.gemini/.env`) from supplying the key.
- **What the bug does:** Untrusted workspace `.env` files contaminate explicit `dotenv_path` calls, Windows UTF-16 `.env` files crash MCP server startup on import, copied `.env.example` templates with one unused blank key silently mask real keys in `~/.gemini/.env`, and inline comments corrupt API tokens sent in HTTP headers (`httpx.LocalProtocolError` / auth failures).
- **How to reproduce:**
  1. Pass explicit `load_env_file(explicit_env)` while `cwd/.env` defines `AUDIT_LEAK_VAR=from_cwd`, and another `.env` has `AUDIT_TEST_EMPTY=`, `AUDIT_INLINE=val # inline comment`, `export AUDIT_EXPORTED=1`, `AUDIT_QUOTED='"abc"'`.
  2. Write UTF-16LE BOM bytes to `.env` and call `load_env_file(utf16_env)`.
  3. Expected: Explicit path loads only that file; blank keys don't block fallbacks; `#` comments & `export ` work; UTF-16 doesn't crash server startup.
  4. Actual: `AUDIT_LEAK_VAR=from_cwd`, `AUDIT_INLINE='val # inline comment'`, `export` ignored (`False`), `AUDIT_QUOTED='abc'`, `AUDIT_TEST_EMPTY=''`, and UTF-16 raises `UnicodeDecodeError`.
- **Screenshots / evidence:** No screenshot: headless config loader; captured output from [`./evidence/R2-probe-c-sandbox-runner.txt`](./evidence/R2-probe-c-sandbox-runner.txt) and [`./evidence/R4-new-edge-probes-part2.txt`](./evidence/R4-new-edge-probes-part2.txt):
  ```text
  === BUG-019: load_env_file UTF-16 crash ===
  utf16 env CRASHED: UnicodeDecodeError 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte
  === BUG-044: config.py explicit dotenv_path, empty KEY=, quotes, inline # ===
  AUDIT_LEAK_VAR loaded despite explicit dotenv_path?: from_cwd
  AUDIT_INLINE: 'val # inline comment'
  export AUDIT_EXPORTED in os.environ?: False
  AUDIT_QUOTED: 'abc'
  AUDIT_TEST_EMPTY in os.environ: True ''
  ```
- **Recommended fix (NOT applied):** If `dotenv_path` is provided, load ONLY that path; drop `Path.cwd() / ".env"` from automatic import-time scanning (allow only explicit `project_root/.env` and `~/.gemini/.env`); catch `(OSError, UnicodeDecodeError)` with `utf-8-sig`/`utf-16` fallback; strip `export `, skip inline `#` outside quotes, only strip a matching single outer pair of quotes, and do not overwrite/block missing keys with empty string `""` (check `not os.environ.get(key)`).
  ```python
  # BEFORE (src/bugarena/config.py:13-35)
  if dotenv_path:
      candidates.append(Path(dotenv_path).resolve())
  candidates.append(Path(__file__).resolve().parent.parent.parent / ".env")
  candidates.append(Path.cwd() / ".env")
  ...
  if key and key not in os.environ:
      os.environ[key] = val

  # AFTER
  candidates = [Path(dotenv_path).resolve()] if dotenv_path else [
      Path(__file__).resolve().parent.parent.parent / ".env",
      Path.home() / ".gemini" / ".env",
  ]
  ...
  if key and val and not os.environ.get(key):
      os.environ[key] = val
  ```
  - *Risks/Side effects:* Removing `Path.cwd() / ".env"` requires users running `bugarena` from outside the repo root to place `.env` in `~/.gemini/.env`, project root, or MCP `env` config.
  - *Suggested regression tests:* Unit tests for UTF-16 `.env`, explicit `dotenv_path` isolation, blank `KEY=` fallback behavior, `export `, and inline `#` comments.
- Related bugs: BUG-043

---

### BUG-020 — Prompt Injection and Unescaped Markdown/Code-Fence Injection in Repair Prompts and Reports
- Severity: High   Confidence: Confirmed
- Category: security
- Location: `src/bugarena/tournament/providers/dispatcher.py:114-144`; `src/bugarena/reporting/markdown_formatter.py:28-80,120-174`
- Found by: security-reviewer, python-reviewer   Verified by: architect
- **What the bug is:** `build_repair_prompt` (`dispatcher.py:114-144`) and `format_bug_diagnostic_markdown` / `format_markdown_report` (`markdown_formatter.py:28-80,120-174`) embed untrusted `error_log`, `code_snippet`, `hint`, `explanation`, `file_path`, and `champion.diff` straight into triple-backtick code fences (` ``` `) and single-line Markdown table cells (`| col |`) without escaping backticks, pipes `|`, or newlines.
- **What the bug does:** A repository stack trace or code comment containing ```` ``` ```` + adversarial instructions breaks out of the code block inside LLM repair prompts (stealing context or steering `TournamentRunner` into proposing a backdoor diff), while diffs or `explanation` strings containing ```` ``` ```` or `| \n` corrupt generated Markdown reports and leaderboard tables.
- **How to reproduce:**
  1. Pass `bug_description="bug | ok\n```\n# System override..."` or a `code_snippet` containing ```` ``` ```` to `build_repair_prompt` or `format_markdown_report`.
  2. Expected: Delimiter fences use longer adaptive backtick fences (`~~~~` / N+1 backticks) and Markdown table cells escape `|` and `\n`.
  3. Actual: Unescaped ```` ``` ```` closes the fenced block prematurely and unescaped `|\n` splits the table row cleanly in the output Markdown.
- **Screenshots / evidence:** No screenshot: headless library; confirmed via direct static code inspection across `src/bugarena/tournament/providers/dispatcher.py:118-131` and `src/bugarena/reporting/markdown_formatter.py:45-64,137-159`.
- **Recommended fix (NOT applied):** Compute a fence length exceeding the longest backtick sequence inside content (`~~~~` or ```` ````` ````), escape `|`/`\r`/`\n` in Markdown table cells (`markdown_formatter.py:46,138`), and frame untrusted repository text explicitly as data in `build_repair_prompt`.
  ```python
  # BEFORE (src/bugarena/reporting/markdown_formatter.py:137-138)
  lines.append(
      f"| {idx} | `{ev.candidate_id}` | {persona_str} | {repro_str} | {ev.regressions_count} | {ev.diff_churn} | {ev.cyclomatic_delta} | **{ev.score:.1f}** | `{status_str}` |"
  )

  # AFTER
  safe_cid = ev.candidate_id.replace("|", "\\|").replace("`", "\\`").replace("\n", " ")
  # Also wrap raw code_snippet / error_log / diff with a fence longer than any backtick run inside them.
  ```
  - *Risks/Side effects:* Minor visual change when diffs/logs contain long backtick runs or newlines.
  - *Suggested regression tests:* Verify `format_markdown_report` and `build_repair_prompt` preserve valid Markdown structure when `error_log`, `code_snippet`, and `diff` contain triple backticks and `|` characters.
- Related bugs: BUG-001, BUG-016, BUG-032

---

### BUG-021 — Unlocked Registry Read (`evaluate_patches`), FIFO-Not-LRU Eviction, Read-Modify-Write Race, and Cross-Repo Collision
- Severity: High   Confidence: Confirmed
- Category: concurrency
- Location: `src/bugarena/server.py:34-59,212,216-238,258,415-429`
- Found by: performance-optimizer, code-reviewer, type-design-analyzer, python-reviewer, silent-failure-hunter, comment-analyzer   Verified by: code-architect, Round 5 Dynamic Probe
- **What the bug is:** Despite `server.py:33` claiming `"Bounded, thread-safe in-memory registries"` (`MAX_REGISTRY_SIZE = 100`):
  1. `_store_tournament`, `_store_repro`, and `_store_bug` (`lines 41-59`) assign `_TOURNAMENT_REGISTRY[k] = v` without calling `.move_to_end(k)`, causing pure FIFO eviction instead of LRU eviction (actively reused entries still get evicted after 100 newer inserts!).
  2. `evaluate_patches` (`line 212`) accesses `_TOURNAMENT_REGISTRY.get(tournament_id)` **without** acquiring `_REGISTRY_LOCK`, then constructs and stores `updated_tournament` (`lines 228-238`) via a non-atomic read-modify-write, risking lost updates (`bug_spec`/`repro_spec`) under concurrent calls.
  3. `_REPRO_REGISTRY` (`lines 48-52`) keys solely on relative `tests/repro/test_issue_<6hex>.py` without `repo_path`, risking collisions across repositories (`BUG-031`).
- **What the bug does:** Re-evaluated or updated active tournaments get evicted while idle newer ones survive (`t_000` evicted after touch + `t_new`), concurrent tool calls can read unlocked state or overwrite enrichment metadata (`bug_spec`/`repro_spec`), and repro lookups lack repository scoping.
- **How to reproduce:**
  1. Fill `_TOURNAMENT_REGISTRY` with `t_000..t_099` (`100` entries), re-store `t_000` (`_store_tournament("t_000", rec)`), then insert `t_new`.
  2. Check `"t_000" in _TOURNAMENT_REGISTRY`.
  3. Expected: `True` (`t_000` was most recently touched, so `t_001` should be evicted).
  4. Actual: `False` (`t_000` was evicted first due to FIFO ordering; note tight concurrent thread `OrderedDict` crash did not trigger inside short CPython GIL benchmark — recorded as `UNV-004`).
- **Screenshots / evidence:** No screenshot: headless MCP server; captured output from [`./evidence/R5-gitignore-and-lru.txt`](./evidence/R5-gitignore-and-lru.txt):
  ```text
  === REGISTRY NON-LRU FIFO EVICTION TEST (BUG-021) ===
  After touching t_000 and adding t_new, is t_000 EVICTED anyway (FIFO bug)?: True
  ```
- **Recommended fix (NOT applied):** Guard `_TOURNAMENT_REGISTRY.get` at `server.py:212` with `with _REGISTRY_LOCK:`, move updated keys with `.move_to_end(key)` on write/read inside `_store_*`, and combine `bug_spec`/`repro_spec` atomically under `_REGISTRY_LOCK` when updating evaluations.
  ```python
  # BEFORE (src/bugarena/server.py:41-45 & 212)
  def _store_tournament(t_id: str, tournament: TournamentRecord) -> None:
      with _REGISTRY_LOCK:
          _TOURNAMENT_REGISTRY[t_id] = tournament
          if len(_TOURNAMENT_REGISTRY) > MAX_REGISTRY_SIZE:
              _TOURNAMENT_REGISTRY.popitem(last=False)
  # line 212:
  tournament = _TOURNAMENT_REGISTRY.get(tournament_id)

  # AFTER
  def _store_tournament(t_id: str, tournament: TournamentRecord) -> None:
      with _REGISTRY_LOCK:
          _TOURNAMENT_REGISTRY[t_id] = tournament
          _TOURNAMENT_REGISTRY.move_to_end(t_id)
          while len(_TOURNAMENT_REGISTRY) > MAX_REGISTRY_SIZE:
              _TOURNAMENT_REGISTRY.popitem(last=False)
  # line 212:
  with _REGISTRY_LOCK:
      tournament = _TOURNAMENT_REGISTRY.get(tournament_id)
      if tournament:
          _TOURNAMENT_REGISTRY.move_to_end(tournament_id)
  ```
  - *Risks/Side effects:* Requires consistent locking around any helper iterating `_TOURNAMENT_REGISTRY` (`server.py` already holds `_REGISTRY_LOCK` on `_REPRO_REGISTRY` iteration at `line 332`).
  - *Suggested regression tests:* Verify re-storing `t_000` then inserting `t_100` evicts `t_001` instead of `t_000`, and verify `evaluate_patches` preserves concurrent `bug_spec` updates.
- Related bugs: BUG-031, BUG-037

---

### BUG-022 — `TournamentRunner` Is Disconnected from All MCP Tools and Default Personas Omit `CONTRACT_ENFORCER`
- Severity: High   Confidence: Confirmed
- Category: other
- Location: `src/bugarena/server.py:145-199,361-452`; `src/bugarena/tournament/runner.py:25-39`; `README.md:10`; `.agents/skills/bugarena-repair/SKILL.md:6-7,34`
- Found by: comment-analyzer, code-reviewer, type-design-analyzer   Verified by: code-architect, Round 2 Dynamic Probe
- **What the bug is:** None of the 7 `@mcp.tool()` endpoints in `src/bugarena/server.py` import or call `TournamentRunner` or `MultiModelDispatcher`. Both `agent_fix_tournament` and `bugarena_autonomous_repair` require the MCP caller to pass pre-generated diffs in `candidate_patches_raw`. Meanwhile, `TournamentRunner.__init__` (`runner.py:30-37`) defaults to only 3 personas (`SURGICAL_MINIMALIST`, `DEFENSIVE_GUARDIAN`, `ARCHITECTURAL_FIXER`), silently omitting `PersonaType.CONTRACT_ENFORCER` even though `PersonaType` and `README.md:10` / `SKILL.md:6-7` advertise all 4.
- **What the bug does:** The multi-provider LLM repair engine (`MultiModelDispatcher` + `TournamentRunner`, plus configured Gemini/Groq/OpenAI/DeepSeek API keys) is dead code from an MCP client's perspective unless manually invoked in Python, and users instantiating `TournamentRunner()` directly never invoke `CONTRACT_ENFORCER` unless passed explicitly.
- **How to reproduce:**
  1. Instantiate `TournamentRunner()` and inspect `[p.value for p in r.personas]`.
  2. Grep `src/bugarena/server.py` for `TournamentRunner` or `MultiModelDispatcher`.
  3. Expected: Default runner includes all 4 `PersonaType` members (or explicitly documents 3-persona subset), and MCP server exposes optional LLM-backed generation when `candidate_patches_raw` is omitted.
  4. Actual: `TournamentRunner().personas` contains 3 items (missing `contract_enforcer`), and `server.py` contains zero imports or calls to `TournamentRunner` / `MultiModelDispatcher`.
- **Screenshots / evidence:** No screenshot: headless MCP server; captured output from [`./evidence/R2-probe-f-eval-runner-flags.txt`](./evidence/R2-probe-f-eval-runner-flags.txt):
  ```text
  === PROBE BUG-022 & BUG-038: TournamentRunner defaults, empty list, timeout ===
  default personas (missing CONTRACT_ENFORCER): ['surgical_minimalist', 'defensive_guardian', 'architectural_fixer']
  ```
- **Recommended fix (NOT applied):** Include `list(PersonaType)` as the default `personas` list when `personas is None` (`runner.py:30`), and optionally invoke `TournamentRunner` inside `agent_fix_tournament` / `bugarena_autonomous_repair` when `candidate_patches_raw` is omitted/empty (or clarify documentation).
  ```python
  # BEFORE (src/bugarena/tournament/runner.py:30-37)
  self.personas = list(
      personas or [PersonaType.SURGICAL_MINIMALIST, PersonaType.DEFENSIVE_GUARDIAN, PersonaType.ARCHITECTURAL_FIXER]
  )

  # AFTER
  self.personas = list(PersonaType) if personas is None else list(personas)
  ```
  - *Risks/Side effects:* Enabling auto-LLM dispatch in `server.py` would trigger paid API calls and async latency unless gated behind an explicit parameter (e.g., `auto_generate: bool = False`).
  - *Suggested regression tests:* Assert `len(TournamentRunner().personas) == 4` and verify `PersonaType.CONTRACT_ENFORCER` is included by default.
- Related bugs: BUG-016, BUG-038, BUG-040

---

### BUG-023 — Frozen Pydantic Models Allow In-Place `Sequence` Mutation, Lack Domain Validators, and `str(PersonaType)` Breaks under Python 3.11+
- Severity: High   Confidence: Confirmed
- Category: data-integrity
- Location: `src/bugarena/models/agent.py:8-38`; `src/bugarena/models/bug.py:8-44`; `src/bugarena/models/report.py:9-19`; `src/bugarena/models/repro.py:6-27`; `src/bugarena/models/tournament.py:12-42`
- Found by: type-design-analyzer, python-reviewer   Verified by: code-architect, Round 2 Dynamic Probe
- **What the bug is:** Three type-design & immutability bugs span `src/bugarena/models/`:
  1. `BugSpec.suspects`, `BugSpec.traces`, `TournamentRecord.candidates`, and `TournamentRecord.evaluations` are annotated `Sequence[...]` without converting caller-supplied `list` values into `tuple`, allowing post-creation in-place mutation (`.append()`, `.clear()`, `[0] = ...`) on supposedly `frozen=True` models (`BugSpec`).
  2. `PersonaType(str, Enum)` (`agent.py:8`) instead of `enum.StrEnum` (available in Python 3.11+) evaluates `str(PersonaType.SURGICAL_MINIMALIST)` to `"PersonaType.SURGICAL_MINIMALIST"` under Python 3.11+ instead of `"surgical_minimalist"`.
  3. Domain models omit `extra="forbid"` (`BUG-014`) and key invariant validators (`SuspectLocation.line_range[0] <= line_range[1]` with `>= 1`, `FaultTrace.line_number >= 1`, `PatchEvaluation`: `regressions_count <= total_regressions_checked`, non-empty `bug_id`/`tournament_id`/`candidate_id`, `repro_test_spec.red_baseline_verified` coherence).
- **What the bug does:** Downstream callers can silently mutate `bug.suspects` inside cached registry entries, `FixReport` silently ignores typoed keyword arguments (`BUG-014`), invalid line ranges `(1, 0)` pass validation silently (`BUG-034`), and f-strings formatting `PersonaType` without `.value` emit `"PersonaType.X"`.
- **How to reproduce:**
  1. Run `b = BugSpec(bug_id="1", repo_path=".", suspects=[s1]); b.suspects.append(s1); print(len(b.suspects))` and `print(str(PersonaType.SURGICAL_MINIMALIST))`.
  2. Expected: Attempting to mutate `b.suspects` raises `AttributeError` (`tuple` has no `append`), and `str(PersonaType.SURGICAL_MINIMALIST) == 'surgical_minimalist'`.
  3. Actual: `BugSpec.suspects` mutates in place (`len = 2`), and `str(PersonaType.SURGICAL_MINIMALIST)` outputs `'PersonaType.SURGICAL_MINIMALIST'`.
- **Screenshots / evidence:** No screenshot: headless Pydantic models; captured output from [`./evidence/R2-probe-e-server-dispatcher.txt`](./evidence/R2-probe-e-server-dispatcher.txt):
  ```text
  === BUG-023: frozen BugSpec mutation & StrEnum ===
  BugSpec.suspects mutated in place len = 2 str(PersonaType) = PersonaType.SURGICAL_MINIMALIST
  ```
- **Recommended fix (NOT applied):** Annotate immutable collections as `tuple[..., ...]` (Pydantic automatically coerces input `list` -> `tuple`), migrate `PersonaType` to `StrEnum`, add `extra="forbid"` to `ConfigDict`, and add `@model_validator` / `@field_validator` invariant checks.
  ```python
  # BEFORE (src/bugarena/models/agent.py:8 & models/bug.py:37,43)
  class PersonaType(str, Enum): ...
  suspects: Sequence[SuspectLocation] = Field(default_factory=tuple)

  # AFTER
  class PersonaType(StrEnum): ...
  model_config = ConfigDict(frozen=True, extra="forbid")
  suspects: tuple[SuspectLocation, ...] = Field(default_factory=tuple)
  ```
  - *Risks/Side effects:* Code checking `isinstance(spec.suspects, list)` would break (must treat as `Sequence`/`tuple`); adding `extra="forbid"` surfaces hidden schema mismatches (`BUG-014`) immediately.
  - *Suggested regression tests:* Update `test_models.py` to test `AttributeError` on `b.suspects.append(...)`, `str(PersonaType.SURGICAL_MINIMALIST) == "surgical_minimalist"`, and rejection of `line_range=(10, 5)` or `regressions_count > total_regressions_checked`.
- Related bugs: BUG-014, BUG-034

---

### BUG-024 — `generate_reproduction_test_code` Produces `SyntaxError`, `IndexError`, `NameError`, or Silent Assertion Drops Across Common Inputs
- Severity: High   Confidence: Confirmed
- Category: logic
- Location: `src/bugarena/synthesizer/test_generator.py:9-15,26-52,63-75`
- Found by: code-reviewer, python-reviewer, type-design-analyzer, silent-failure-hunter, pr-test-analyzer   Verified by: architect, code-architect, Round 2 & 4 Dynamic Probes
- **What the bug is:** Beyond RCE (`BUG-001`) and swallowed `ImportError` (`BUG-011`), `generate_reproduction_test_code` fails on benign real-world inputs:
  1. `"Raises ValueError"`: checks `"raises " in expected_behavior.lower()` (`line 39`), then splits case-sensitively on `"raises "` (`line 40`) -> `IndexError: list index out of range`.
  2. `"assert a == 1"`: matches `"assert" in expected_behavior` (`line 42`) and prepends another `assert `, emitting invalid `assert assert a == 1` (`ValueError: Generated test code failed syntax validation`).
  3. `"result == 0"` or `"actual == 5"`: matches `"==" in expected_behavior` (`line 42`) and emits `    assert result == 0\n` **without** first executing `result = {target_call}` (`line 46`), triggering a runtime `NameError: name 'result' is not defined` that falsely passes Red-baseline validation!
  4. Non-`==`, non-`assert`, non-`raises` strings like `"returns positive int"`: falls into `else:` (`lines 44-46`), silently discarding the user's expectation and asserting `result is not None`.
  5. Trailing `\` in `bug_description` (`safe_desc`), raw `suspect.file_path` interpolated unscrubbed at `line 50` (including Windows backslashes `\`), non-identifier `clean_func` like `<lambda>`, or hyphenated filenames like `my-mod.py` (`from my-mod import ...`) produce invalid triple-quoted strings / Python `SyntaxError`.
- **What the bug does:** Frequent crashes (`IndexError`/`ValueError`) abort Stage 2 reproduction, silently discarded expectations fail to test the actual bug, and `"result == 0"` produces bogus `NameError` failures that validate false Red baselines.
- **How to reproduce:**
  1. Call `generate_reproduction_test_code` with:
     - `expected_behavior="Raises ValueError"` -> `IndexError`
     - `expected_behavior="assert x == 1"` -> `ValueError` (double `assert`)
     - `expected_behavior="result == 0"` -> runtime `NameError`
     - `bug_description="bad\\"` -> unterminated string `ValueError`
     - `suspect.file_path="my-mod.py"` -> invalid `from my-mod` `SyntaxError`
     - `expected_behavior="positive return"` -> emits `assert result is not None`
- **Screenshots / evidence:** No screenshot: headless library; captured outputs from [`./evidence/R2-probe-b-security.txt`](./evidence/R2-probe-b-security.txt) and [`./evidence/R4-new-edge-probes.txt`](./evidence/R4-new-edge-probes.txt):
  ```text
  Raises IndexError: RAISED IndexError: list index out of range
  assert double-assert ValueError: RAISED ValueError: Generated test code failed syntax validation: invalid syntax (<unknown>, line 28)
  trailing backslash: RAISED ValueError: Generated test code failed syntax validation: unterminated triple-quoted string literal (detected at line 30) (<unknown>, line 27)
  non-eq silent drop: OK, has_default_not_none=True
  win_abs_lambda: RAISED ValueError: Generated test code failed syntax validation: invalid syntax (<unknown>, line 17)
  expected_behavior='result == 0' -> verified RED? True stdout has NameError? True
  hyphenated file_path: ValueError Generated test code failed syntax validation: invalid syntax (<unknown>, line 17)
  ```
- **Recommended fix (NOT applied):** Escape `\` in `_sanitize_docstring` and apply it to `suspect.file_path` (`line 50`) too; handle `raises ` case-insensitively with regex; strip leading `assert `; evaluate `result = {target_call}` *before* asserting `result == ...`; handle `<lambda>`/`<listcomp>` cleanly; validate `import_path` segments with `.isidentifier()` (using `importlib.util.spec_from_file_location` fallback for hyphenated scripts); and reject unknown non-empty `expected_behavior` forms rather than silently ignoring them.
  ```python
  # BEFORE (src/bugarena/synthesizer/test_generator.py:39-46)
  if expected_behavior and "raises " in expected_behavior.lower():
      exc_name = expected_behavior.split("raises ", 1)[1].strip()
      ...
  elif expected_behavior and ("==" in expected_behavior or "assert" in expected_behavior):
      assertion_block = f"    assert {expected_behavior}\n"

  # AFTER
  if expected_behavior and (m := re.search(r"\braises\s+([A-Za-z_][A-Za-z0-9_.]*)", expected_behavior, re.I)):
      assertion_block = f"    with pytest.raises({m.group(1)}):\n        {target_call}\n"
  elif expected_behavior:
      expr = re.sub(r"^\s*assert\s+", "", expected_behavior.strip())
      if re.search(r"\bresult\b", expr):
          assertion_block = f"    result = {target_call}\n    assert {expr}\n"
      else:
          assertion_block = f"    assert {expr}\n"
  ```
  - *Risks/Side effects:* Changing `import *` fallback for non-identifier filenames (`my-mod.py`) requires `importlib` dynamic loading if invoked directly.
  - *Suggested regression tests:* Unit tests for `"Raises ValueError"`, `"assert x == 1"`, `"result == 0"`, `"desc\\"`, `"<lambda>"`, `"my-mod.py"`, and Windows paths.
- Related bugs: BUG-001, BUG-011, BUG-012

---

### BUG-025 — `BugDiscoveryEngine` `rglob` Matches Files Inside `.venv/` / Build Artifacts and Assigns Misleading Frame Confidence / Logs
- Severity: High   Confidence: Confirmed
- Category: logic
- Location: `src/bugarena/discovery/engine.py:32-72,94-107`
- Found by: code-reviewer, performance-optimizer, silent-failure-hunter, python-reviewer, security-reviewer   Verified by: code-architect, Round 2 Dynamic Probe
- **What the bug is:** When a traceback path (`File "..."`) fails direct resolution relative to `self.repo_path`, `engine.py:46-52` runs `list(self.repo_path.rglob(Path(trace.file_path).name))` and picks `matches[0]` **without** filtering `.venv/`, `venv/`, `.git/`, `node_modules/`, `__pycache__/`, or `site-packages/`, nor sorting paths cleanly. It also lacks path deduplication (`utils.py` visited across multiple frames creates duplicate suspects), allows non-`.py` reads (`.env` in `BUG-004`), uses frame index `idx` decoupled from match quality for `confidence` (`line 70`), and triggers a full directory traversal on every unmatched frame.
- **What the bug does:** When a repository contains a `.venv/` (like `d:\MCP server` itself!), `bug_detect` matches third-party `.venv/pkg/utils.py` with `confidence=0.95` ahead of genuine application code (`src/real.py`, `confidence=0.8`), directing repair agents to patch `.venv/` files! Large monorepos suffer repeated full-tree `rglob` stalls on every traceback frame.
- **How to reproduce:**
  1. Create a repo with `.venv/pkg/utils.py` and `src/real.py`, plus a traceback referencing external `/ext/utils.py` (line 10, bottom frame) called by `src/real.py` (line 2).
  2. Run `BugDiscoveryEngine(repo).discover_from_trace(...)`.
  3. Expected: `.venv/` is excluded from discovery, returning only `src/real.py`.
  4. Actual: Returns `[('.venv/pkg/utils.py', 0.95), ('src/real.py', 0.8)]`.
- **Screenshots / evidence:** No screenshot: headless discovery engine; captured output from [`./evidence/R2-probe-d-eval-discovery.txt`](./evidence/R2-probe-d-eval-discovery.txt):
  ```text
  === BUG-025: discovery engine matches .venv & shifts confidence ===
  suspects: [('.venv/pkg/utils.py', 0.95), ('src/real.py', 0.8)]
  ```
- **Recommended fix (NOT applied):** Index repository `.py` files once per `discover_from_trace` call (excluding `.venv`, `venv`, `.git`, `node_modules`, `__pycache__`, `build`, `dist`, `.env*`), prefer suffix-path matches before basename fallback, deduplicate suspects by `(rel_path, function_name)`, and penalize confidence when resolved via heuristic basename lookup rather than exact path match.
  ```python
  # BEFORE (src/bugarena/discovery/engine.py:46)
  matches = list(self.repo_path.rglob(Path(trace.file_path).name))

  # AFTER
  IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}
  # Build candidate index once excluding IGNORED_DIRS and match suffix before basename.
  ```
  - *Risks/Side effects:* Repositories intentionally storing editable target code under an ignored dir name like `build/` would be skipped unless configurable.
  - *Suggested regression tests:* Add a test with `.venv/lib/calc.py` + `src/calc.py` proving `BugDiscoveryEngine` never picks `.venv/` files.
- Related bugs: BUG-004, BUG-026, BUG-034

---

### BUG-026 — `parse_python_traceback` Breaks on `<lambda>` / `<listcomp>` Frames, Colon Source Lines, Chained Exceptions, and Unindented Context
- Severity: High   Confidence: Confirmed
- Category: logic
- Location: `src/bugarena/discovery/log_parser.py:7-15,28-74`
- Found by: code-reviewer, python-reviewer, silent-failure-hunter, comment-analyzer   Verified by: code-architect, Round 2 & 3 Dynamic Probes
- **What the bug is:** Three brittle regex/heuristics inside `log_parser.py`:
  1. `FRAME_PATTERN` (`line 8`) uses `in (?P<func>\w+)` which fails to match Python frame names containing angle brackets like `<lambda>`, `<listcomp>`, `<dictcomp>`, or `<module>`, falling back to `<module>` and leaking `'File "app.py", line 4, in <lambda>'` as the source code snippet!
  2. Exception detection (`line 35`) checks `if exc_match or ":" in line_clean and not line_clean.startswith("File "):` without checking indentation or `EXCEPTION_PATTERN` exclusively; any trailing code/context line ending in `:` (such as `else:` or `def foo():` after a traceback or inline log message) is captured as `error_message` instead of the real exception line.
  3. `parse_python_traceback` assigns the *single* trailing `error_message` (`lines 29-37`) globally to every frame across chained exceptions (`During handling of the above exception...` / `The above exception was the direct cause...`), misattributing inner root-cause exceptions cleanly as the outer exception.
- **What the bug does:** Lambdas, list comprehensions, chained exception tracebacks, and log outputs containing colons (`else:`, timestamps, URLs) yield corrupted `function_name`, `error_message`, and `code` fields, misguiding `locate_faulty_ast_slice` and LLM repair prompts.
- **How to reproduce:**
  1. Pass a traceback containing `File "app.py", line 4, in <lambda>` followed by `else:` and `ZeroDivisionError: ...`.
  2. Pass a chained traceback with inner `ValueError: inner` followed by `RuntimeError: outer`.
  3. Expected: Parses `function_name="<lambda>"`, `error_message="ZeroDivisionError: ..."`, and attaches each exception to its own traceback block.
  4. Actual: `<lambda>` becomes `<module>`, `error_message` becomes `else:`, `code` echoes the `'File "app.py", ...'` header, and both frames in chained traces share `RuntimeError: outer`.
- **Screenshots / evidence:** No screenshot: headless traceback parser; captured output from [`./evidence/R2-probe-d-eval-discovery.txt`](./evidence/R2-probe-d-eval-discovery.txt) and [`./evidence/R3-deep-edge-probes.txt`](./evidence/R3-deep-edge-probes.txt):
  ```text
  === BUG-026: log_parser regex failures ===
  parsed func (expected <lambda>): <module> error_message: else: code lines: 'File "app.py", line 4, in <lambda>'
  === TEST 6: Discovery chained tracebacks ===
  chained traces count: 2 trace0 code: 'line2' trace0 err: RuntimeError: outer
  ```
- **Recommended fix (NOT applied):** Change `(?P<func>[^\r\n]+)` in `FRAME_PATTERN`, match exceptions strictly with `EXCEPTION_PATTERN` (not arbitrary `":" in line_clean`), and parse exception blocks sequentially (flushing accumulated frames in each traceback chain block whenever `EXCEPTION_PATTERN` fires).
  ```python
  # BEFORE (src/bugarena/discovery/log_parser.py:8 & 35)
  FRAME_PATTERN = re.compile(r'File\s+["\'](?P<file>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>\w+))?', re.I)
  if exc_match or ":" in line_clean and not line_clean.startswith("File "):

  # AFTER
  FRAME_PATTERN = re.compile(r'File\s+["\'](?P<file>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>[^\r\n]+))?', re.I)
  # Match EXCEPTION_PATTERN sequentially per traceback group instead of backward ":" scan
  ```
  - *Risks/Side effects:* Plain exception lines without standard `XxxError:` suffixes would require extending `EXCEPTION_PATTERN` instead of relying on arbitrary `":"`.
  - *Suggested regression tests:* Add unit tests for `<lambda>` frames, trailing `else:` lines, chained `raise ... from ...` tracebacks, and multi-line exception messages.
- Related bugs: BUG-025, BUG-034

---

### BUG-027 — `PatchEvaluator` Silently Swallows `apply_patch` Failures and `SecurityViolationError`
- Severity: High   Confidence: Confirmed
- Category: error-handling
- Location: `src/bugarena/evaluation/test_runner.py:49-66`
- Found by: silent-failure-hunter   Verified by: code-architect
- **What the bug is:** When `manager.apply_patch(sandbox_path, cand.diff)` throws `OSError`, `ValueError`, or `SecurityViolationError` (`test_runner.py:52`), `PatchEvaluator` catches it silently, sets `patch_applied = False`, and calls `compute_patch_score(repro_passed=False, ...)` (`lines 55-66`), emitting `"Reproduction test failed: Patch did not resolve the defect."` (`scorer.py:32`).
- **What the bug does:** Path-traversal security attacks inside candidate diffs, encoding errors, or malformed-patch I/O errors are completely hidden from callers and users, presenting every security violation or patch-application crash identically to a normal failing bug fix.
- **How to reproduce:**
  1. Submit a candidate diff targeting `../../../etc/passwd` to `evaluate_patches`.
  2. Expected: Records a clear `"Patch application rejected (SecurityViolationError): ..."` disqualification reason (or raises/logs the violation explicitly).
  3. Actual: Disqualification reason claims `"Reproduction test failed: Patch did not resolve the defect."` with zero mention of the security violation.
- **Screenshots / evidence:** No screenshot: headless evaluator; verified at `src/bugarena/evaluation/test_runner.py:49-66` and `src/bugarena/sandbox/manager.py:92` (plus confirmed `SecurityViolationError` exception path observed during `R2-probe-c` when `+++ /dev/null` threw `SecurityViolationError` inside `apply_patch`).
- **Recommended fix (NOT applied):** Capture `apply_error = str(exc)` when `apply_patch` fails and pass an explicit `disqualification_reason=f"Patch application failed ({type(exc).__name__}): {exc}"` (or optional override param on `compute_patch_score`) plus structured `logger.warning`.
  ```python
  # BEFORE (src/bugarena/evaluation/test_runner.py:50-66)
  except (OSError, ValueError, SecurityViolationError):
      patch_applied = False
  if not patch_applied:
      evaluations.append(compute_patch_score(..., repro_passed=False, ...))

  # AFTER
  except (OSError, ValueError, SecurityViolationError) as exc:
      evaluations.append(PatchEvaluation(
          candidate_id=cand.candidate_id, repro_passed=False, regressions_count=0,
          total_regressions_checked=0, diff_churn=cand.lines_added + cand.lines_deleted,
          cyclomatic_delta=0, score=0.0, disqualified=True,
          disqualification_reason=f"Patch rejected during apply ({type(exc).__name__}): {exc}",
      ))
      continue
  ```
  - *Risks/Side effects:* Exposes internal sandbox exception messages — ensure `scrub_sensitive_data(..., base_dir=sandbox_path)` wraps `str(exc)` before returning.
  - *Suggested regression tests:* Evaluate a diff containing `../../outside.py` and assert `"SecurityViolationError"` appears in `disqualification_reason`.
- Related bugs: BUG-009, BUG-013, BUG-029

---

### BUG-028 — `calculate_cyclomatic_delta` Crashes Uncaught on `SyntaxError` and `_count_ast_branches` Silently Returns `0`
- Severity: High   Confidence: Confirmed
- Category: error-handling
- Location: `src/bugarena/evaluation/ast_metrics.py:26-32,47-59`
- Found by: python-reviewer, silent-failure-hunter, performance-optimizer, code-reviewer   Verified by: code-architect, Round 2 Dynamic Probe
- **What the bug is:** `calculate_cyclomatic_delta` (`ast_metrics.py:52-58`) calls `radon.complexity.cc_visit(...)` inside `try ... except (ImportError, AttributeError, ValueError):` — omitting `SyntaxError`. When `patched_code` contains a syntax error, `cc_visit` raises an uncaught `SyntaxError` and crashes callers. Meanwhile, `_count_ast_branches` (`lines 28-31`) catches `SyntaxError` and returns `0` (`complexity_score(0) = 1.0`), treating unparsable Python code as maximally simple!
- **What the bug does:** Actually wiring `calculate_cyclomatic_delta` into `PatchEvaluator` (to fix `BUG-013`) would crash the entire tournament whenever any single candidate produces broken syntax, while the AST fallback hides syntax errors behind a perfect `0`-complexity score.
- **How to reproduce:**
  1. Call `calculate_cyclomatic_delta("def f():\n    return 1\n", "def broken(:\n")`.
  2. Expected: Raises an explicit domain error (or signals syntax failure for hard gating) rather than uncaught `SyntaxError` or `0`.
  3. Actual: Raises uncaught `SyntaxError: invalid syntax (<unknown>, line 1)`.
- **Screenshots / evidence:** No screenshot: headless library; captured output from [`./evidence/R2-probe-d-eval-discovery.txt`](./evidence/R2-probe-d-eval-discovery.txt):
  ```text
  radon SyntaxError UNCAUGHT: SyntaxError invalid syntax (<unknown>, line 1)
  ```
- **Recommended fix (NOT applied):** Explicitly `ast.parse(patched_code)` upfront raising `ValueError("Syntax error in patched code")` for the evaluator syntax gate (`BUG-013`), and handle `(ImportError, SyntaxError, ...)` cleanly only when falling back intentionally or separating syntax validation from complexity measurement.
  ```python
  # BEFORE (src/bugarena/evaluation/ast_metrics.py:52-59)
  try:
      from radon.complexity import cc_visit
      ...
  except (ImportError, AttributeError, ValueError):
      return _count_ast_branches(patched_code) - _count_ast_branches(original_code)

  # AFTER
  ast.parse(original_code)
  ast.parse(patched_code)  # raises SyntaxError cleanly if invalid; caller gates before scoring
  ```
  - *Risks/Side effects:* Callers must validate syntax before invoking `calculate_cyclomatic_delta` (desirable for failing the Syntax & AST Gate in `BUG-013`).
  - *Suggested regression tests:* Verify syntax-invalid `patched_code` is rejected/flagged rather than scoring complexity `0`.
- Related bugs: BUG-013, BUG-027

---

### BUG-029 — `scrub_sensitive_data` Leaks Paths & Keys Due to Regex Order, Forward-Slash Windows Paths, and Runner Pattern Gaps
- Severity: High   Confidence: Confirmed
- Category: security
- Location: `src/bugarena/sandbox/security.py:102-133`; `src/bugarena/sandbox/runner.py:50-53,92`
- Found by: code-reviewer, security-reviewer, python-reviewer, comment-analyzer   Verified by: code-architect, Round 2 Dynamic Probe
- **What the bug is:** Output scrubbing fails across multiple common paths:
  1. Execution order (`security.py:128-131`): `re.sub(r"[a-zA-Z]:\\[Uu]sers\\[^\/\s\\]+", "[REDACTED_PATH]", scrubbed)` replaces `C:\Users\<USER>` BEFORE `scrubbed.replace(str(base_dir), "[WORKSPACE]")`, breaking exact `base_dir` matching and leaving `[REDACTED_PATH]\AppData\Local\Temp\...` exposed!
  2. Windows regex matches only backslashes (`\\`), so forward-slash Windows paths (`C:/Users/<USER>/work/a.py` and `d:/MCP server/src/a.py`) bypass redaction or leak `C:[REDACTED_PATH]/...` via `/Users/...`.
  3. `runner.py:50-53` passes `sensitive_keys` matching only `("KEY", "TOKEN", "SECRET", "AUTH", "PASS")` (omitting `URL`, `DSN`, `CONNECTION`, `PRIVATE`, `CREDENTIAL` from `BLOCKED_ENV_SUBSTRINGS` as well as `STRIPE_SK` and `MONGO_URI` from `BLOCKED_ENV_EXACT`) and skips short secrets `len(v) <= 5` (alongside the `len(pat) > 3` filter in `scrub_sensitive_data` at `security.py:116`, which skips `<= 3`-char values).
  4. `runner.py:92` error handler (`except (OSError, subprocess.SubprocessError)`) calls `scrub_sensitive_data(f"Execution error: {exc}")` **without** passing `sensitive_patterns` or `base_dir`.
  5. `security.py:120-125` misses common key prefixes (`AIza` 39-char variants / `xoxb-` / `glpat-` / `hf_`).
- **What the bug does:** Host OS paths, repository directories, and database URLs / short tokens leak into MCP tool responses and Markdown reports written to disk.
- **How to reproduce:**
  1. Call `scrub_sensitive_data(r"C:\Users\<USER>\AppData\Local\Temp\box\a.py", base_dir=r"C:\Users\<USER>\AppData\Local\Temp\box")`.
  2. Call `scrub_sensitive_data("C:/Users/<USER>/work/a.py")` and `scrub_sensitive_data("d:/MCP server/src/a.py", base_dir="d:\\MCP server")`.
  3. Expected: All three redact cleanly to `[WORKSPACE]/a.py` / `[REDACTED_PATH]/work/a.py`.
  4. Actual: Outputs `[REDACTED_PATH]\AppData\Local\Temp\box\a.py`, `C:[REDACTED_PATH]/work/a.py`, and unredacted `d:/MCP server/src/a.py`.
- **Screenshots / evidence:** No screenshot: headless security layer; captured output from [`./evidence/R2-probe-b2-parser-dup.txt`](./evidence/R2-probe-b2-parser-dup.txt):
  ```text
  scrub order: [REDACTED_PATH]\AppData\Local\Temp\box\a.py
  scrub forward slash: C:[REDACTED_PATH]/work/a.py
  scrub base_dir slash diff: d:/MCP server/src/a.py
  ```
- **Recommended fix (NOT applied):** Normalize and match `base_dir` (both `/` and `\` variants case-insensitively on Windows) **BEFORE** generic user-directory regexes; update the Windows home regex to `[a-zA-Z]:[/\\][Uu]sers[/\\][^/\s\\]+`; reuse `BLOCKED_ENV_SUBSTRINGS`/`BLOCKED_ENV_EXACT` in `runner.py:50`; and pass `base_dir` to `runner.py:92`.
  ```python
  # BEFORE (src/bugarena/sandbox/security.py:127-131)
  scrubbed = re.sub(r"[a-zA-Z]:\\[Uu]sers\\[^\/\s\\]+", "[REDACTED_PATH]", scrubbed)
  scrubbed = re.sub(r"/(?:home|Users)/[^/\s]+", "[REDACTED_PATH]", scrubbed)
  if base_dir:
      scrubbed = scrubbed.replace(str(base_dir), "[WORKSPACE]")

  # AFTER
  if base_dir:
      b = str(base_dir)
      for variant in {b, b.replace("\\", "/"), b.replace("/", "\\")}:
          scrubbed = scrubbed.replace(variant, "[WORKSPACE]")
  scrubbed = re.sub(r"[a-zA-Z]:[/\\][Uu]sers[/\\][^/\s\\]+", "[REDACTED_PATH]", scrubbed)
  scrubbed = re.sub(r"/(?:home|Users)/[^/\s]+", "[REDACTED_PATH]", scrubbed)
  ```
  - *Risks/Side effects:* Test expectations asserting Windows backslash output must normalize slashes if `/` is matched.
  - *Suggested regression tests:* Verify `base_dir` wins before user-path redaction and both `C:/Users/...` and `C:\Users\...` scrub completely without leaving `C:` prefixes.
- Related bugs: BUG-004, BUG-018

---

### BUG-031 — `generate_bug_report` Broken `_REPRO_REGISTRY` Lookup Fails on Normal Repos and Leaks Tests Across Repos via `"."`
- Severity: High   Confidence: Confirmed
- Category: logic
- Location: `src/bugarena/server.py:331-336`
- Found by: code-reviewer, python-reviewer, silent-failure-hunter, security-reviewer, comment-analyzer, type-design-analyzer   Verified by: code-architect, Round 2 Dynamic Probe
- **What the bug is:** `generate_bug_report` searches `_REPRO_REGISTRY.values()` using `if r.test_file_path.startswith(repo_path) or repo_path in r.test_file_path:` (`server.py:334`). However, `bug_reproduce` stores `r.test_file_path` strictly as a *relative* POSIX path (`"tests/repro/test_issue_xxxxxx.py"` at `server.py:118`), completely lacking `repo_path`!
- **What the bug does:** Two severe failures occur simultaneously:
  1. For normal absolute/named `repo_path` values (e.g., `/tmp/repoA` or `d:\project`), `"repoA" in "tests/repro/test_issue_123456.py"` is `False`, so `generate_bug_report` **never** includes Section 2 (`Failing Reproduction Test (Red Baseline)`).
  2. When a caller passes `repo_path="."`, `"." in "tests/repro/test_issue_123456.py"` evaluates to `True` (matching `.py`!), pulling a reproduction test belonging to an **entirely different repository** into the new bug report!
- **How to reproduce:**
  1. Call `bug_reproduce` on `repoA` (generates `tests/repro/test_issue_xxxxxx.py`).
  2. Call `generate_bug_report(repo_path=str(repoA), ...)` -> Section 2 missing (`False`).
  3. Call `generate_bug_report(repo_path=".", ...)` in another directory -> embeds `repoA`'s confidential test code (`True`).
- **Screenshots / evidence:** No screenshot: headless MCP server; captured output from [`./evidence/R2-probe-e-server-dispatcher.txt`](./evidence/R2-probe-e-server-dispatcher.txt):
  ```text
  BUG-031 generate_bug_report includes Section 2 Repro Test?: False
  BUG-031b repo='.' pulls repoA repro test code?: True
  ```
- **Recommended fix (NOT applied):** Record `resolved_repo_path: str` inside `ReproTestSpec` (or store `(resolved_repo_path, test_rel_path)` keys in `_REPRO_REGISTRY`), iterate in reverse-recency order matching `spec.repo_path == str(Path(repo_path).resolve())`, and allow an explicit optional `repro_test_file` parameter on `generate_bug_report`.
  ```python
  # BEFORE (src/bugarena/server.py:333-336)
  for r in _REPRO_REGISTRY.values():
      if r.test_file_path.startswith(repo_path) or repo_path in r.test_file_path:
          repro_spec = r
          break

  # AFTER
  resolved_repo = str(Path(repo_path).resolve())
  for (rec_repo, rec_path), r in reversed(list(_REPRO_REGISTRY.items())):
      if rec_repo == resolved_repo:
          repro_spec = r
          break
  ```
  - *Risks/Side effects:* Changing `_REPRO_REGISTRY` key structure requires updating its lookups at `server.py:183` and `425`.
  - *Suggested regression tests:* Test `bug_reproduce` on `repoA` followed by `generate_bug_report(repoA)` includes Section 2, and `generate_bug_report(".")` does NOT leak `repoA`'s test.
- Related bugs: BUG-021, BUG-030, BUG-033

---

### BUG-032 — `agent_fix_tournament` Crashes on `explanation: None` and Overwrites Duplicate `candidate_id`s Mixing Diffs & Personas
- Severity: High   Confidence: Confirmed
- Category: logic
- Location: `src/bugarena/server.py:156-199`; `src/bugarena/reporting/markdown_formatter.py:124`
- Found by: type-design-analyzer, code-reviewer, pr-test-analyzer   Verified by: code-architect, Round 2 Dynamic Probe
- **What the bug is:** In `agent_fix_tournament`, `explanation=item.get("explanation", "")` (`server.py:172`) passes `None` when a JSON caller explicitly sets `"explanation": null`, raising an unhandled Pydantic `ValidationError` (`BUG-023`) instead of returning a clean structured `{"error": ...}` response or defaulting to `""`. Worse, duplicate `candidate_id` values across candidates are not rejected (`server.py:156-193`); both register, and `markdown_formatter.py:124` builds `cand_map = {c.candidate_id: c for c in tournament.candidates}`, silently overwriting Candidate 1's persona/diff with Candidate 2's!
- **What the bug does:** Duplicate IDs corrupt generated leaderboards and reports — attribution pairs Candidate 1's winning diff/score with Candidate 2's persona and explanation — while explicit `null` explanations crash the MCP tool instead of returning a JSON error dict.
- **How to reproduce:**
  1. Call `agent_fix_tournament` with `{"candidate_id":"c1", "diff": valid_diff, "explanation": None}`.
  2. Call `agent_fix_tournament` with two entries sharing `"candidate_id": "dup_1"` (Candidate 1 `surgical_minimalist` sets `x = 1`, Candidate 2 `architectural_fixer` sets `x = 99`), evaluate, and call `generate_fix_report`.
  3. Expected: Clean JSON error on invalid schema and rejection of duplicate `candidate_id` values.
  4. Actual: First call crashes `ValidationError`; second produces leaderboard length 2 whose report mixes Candidate 1's `x = 1` diff with `architectural_fixer`!
- **Screenshots / evidence:** No screenshot: headless MCP server; captured output from [`./evidence/R2-probe-e-server-dispatcher.txt`](./evidence/R2-probe-e-server-dispatcher.txt) and [`./evidence/R2-probe-b2-parser-dup.txt`](./evidence/R2-probe-b2-parser-dup.txt):
  ```text
  null explanation CRASHED: ValidationError 1 validation error for CandidatePatch
  dup_1 leaderboard len: 2 champion_diff has '99' (second)?: False report has 'architectural_fixer'?: True
  ```
- **Recommended fix (NOT applied):** Default `explanation = str(item.get("explanation") or "")`, validate `isinstance(item["diff"], str)`, and track `seen_ids: set[str]` in `agent_fix_tournament` returning an error if `cand.candidate_id in seen_ids` (also wrap `TournamentRecord`/`ValidationError` cleanly).
  ```python
  # BEFORE (src/bugarena/server.py:172-176)
  explanation=item.get("explanation", ""),
  candidate_id=item.get("candidate_id"),
  ...
  candidates.append(cand)

  # AFTER
  explanation=item.get("explanation") or "",
  ...
  if cand.candidate_id in seen_ids:
      return {"error": f"Duplicate candidate_id '{cand.candidate_id}' is not allowed."}
  seen_ids.add(cand.candidate_id)
  candidates.append(cand)
  ```
  - *Risks/Side effects:* Callers submitting duplicate candidate IDs must supply unique identifiers (or omit `candidate_id` to auto-generate UUIDs).
  - *Suggested regression tests:* Verify `explanation: None` succeeds cleanly or returns error JSON, and duplicate `candidate_id` returns `{"error": ...}`.
- Related bugs: BUG-020, BUG-023

---

### BUG-035 — `MultiModelDispatcher` Regex Captures Closing Fences/Prose and Hardcodes Fixed Timeout
- Severity: High   Confidence: Confirmed
- Category: logic
- Location: `src/bugarena/tournament/providers/dispatcher.py:13-16,74-91,150-151`
- Found by: code-reviewer, python-reviewer, security-reviewer   Verified by: code-architect, Round 2 Dynamic Probe
- **What the bug is:** `DIFF_BLOCK_REGEX` (`line 14`) uses `[\s\S]+?` terminated by ```` ``` ````, so when an LLM outputs a `diff --git` header before `--- a/`, the match succeeds against `DIFF_BLOCK_REGEX` or falls through to greedy `RAW_DIFF_REGEX` (`line 16`, `@@[\s\S]+`), capturing the closing ```` ``` ```` fence and all trailing conversational LLM prose directly inside the extracted diff! (Additionally, `CRLF` responses break the `\n` literal regex, and `TournamentRunner` (`runner.py:38`) instantiates `MultiModelDispatcher()` with hardcoded `timeout_seconds=60.0` ignoring `run_tournament(..., timeout_seconds=...)`.)
- **What the bug does:** Valid LLM responses prefixed by `diff --git a/... b/...` inside Markdown fences extract trailing ```` ``` ```` + prose into the diff, causing hunk corruption (`BUG-009`), syntax errors, or evaluation disqualification; meanwhile hung HTTP sockets outlive short `run_tournament` timeouts.
- **How to reproduce:**
  1. Call `extract_diff_and_explanation("Here is fix:\n```diff\ndiff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n```\nTrailing prose.")`.
  2. Expected: Returns `"--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y"` cleanly without ```` ``` ```` or `"Trailing prose."`.
  3. Actual: `DIFF_BLOCK_REGEX` fails because `diff --git` precedes `---`, `RAW_DIFF_REGEX` matches greedily, returning `...\n```\nTrailing prose.`.
- **Screenshots / evidence:** No screenshot: headless dispatcher; captured output from [`./evidence/R2-probe-e-server-dispatcher.txt`](./evidence/R2-probe-e-server-dispatcher.txt):
  ```text
  extract_diff git-header captures closing ``` or prose?: True diff= '--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n```\nTrailing prose.'
  ```
- **Recommended fix (NOT applied):** Allow optional `diff --git ...` / `index ...` lines inside `DIFF_BLOCK_REGEX`, normalize `\r\n`, stop `RAW_DIFF_REGEX` before closing ```` ``` ```` or non-diff prose lines, and propagate `timeout_seconds` into `MultiModelDispatcher`.
  ```python
  # BEFORE (src/bugarena/tournament/providers/dispatcher.py:13-16)
  DIFF_BLOCK_REGEX = re.compile(
      r"```(?:diff)?\n(--- (?:a/)?\S+\n\+\+\+ (?:b/)?\S+\n[\s\S]+?)```", re.MULTILINE
  )
  RAW_DIFF_REGEX = re.compile(r"(--- (?:a/)?\S+\n\+\+\+ (?:b/)?\S+\n@@[\s\S]+)", re.MULTILINE)

  # AFTER
  DIFF_BLOCK_REGEX = re.compile(
      r"```(?:diff|patch)?\r?\n(?:diff --git [^\n]+\r?\n(?:index [^\n]+\r?\n)?)?"
      r"(--- (?:a/)?\S+\r?\n\+\+\+ (?:b/)?\S+\r?\n[\s\S]+?)```",
      re.MULTILINE,
  )
  ```
  - *Risks/Side effects:* Multiple fenced `diff` blocks in one LLM reply still need concatenation or selecting the primary diff block.
  - *Suggested regression tests:* Verify `extract_diff_and_explanation` strips `diff --git` metadata and stops cleanly before closing ```` ``` ```` and trailing text.
- Related bugs: BUG-016, BUG-038, BUG-042

---

### BUG-037 — Blocking Synchronous MCP Handlers, Sequential Per-Candidate Copies & Subprocesses, and Unbounded Diff/Candidate Payloads
- Severity: High   Confidence: Confirmed
- Category: performance
- Location: `src/bugarena/server.py:92-452`; `src/bugarena/evaluation/test_runner.py:41-111`; `src/bugarena/sandbox/manager.py:52-57`
- Found by: performance-optimizer, security-reviewer   Verified by: code-architect
- **What the bug is:** All 7 `@mcp.tool()` endpoints in `server.py` are synchronous blocking functions executing inside the `MCPServer` async event loop without `asyncio.to_thread(...)`. Furthermore, `PatchEvaluator.evaluate_candidates` (`test_runner.py:41-111`) evaluates candidates strictly sequentially, copying the entire repository and launching 2 separate sequential `pytest` subprocesses (`timeout_seconds=30.0` each) per candidate with no total workflow timeout, while `agent_fix_tournament` (`line 145`) and `evaluate_patches` (`line 203`) impose zero count/byte-size limits on `candidate_patches_raw`, `diff`, or `repro_code` (only `bugarena_autonomous_repair` caps candidates at `20` and `error_log` at `64KB`).
- **What the bug does:** Evaluating 20 candidates across a medium repository stalls the entire MCP server event loop for up to ~20 minutes (`20 * 2 * 30s`), blocks heartbeats/cancellations/concurrent requests, and risks OOM or disk exhaustion from unbounded candidate payloads or large repo copies.
- **How to reproduce:**
  1. Inspect `server.py:63-452` (`def bug_detect`, `def evaluate_patches`, `def bugarena_autonomous_repair` — all synchronous `def` running blocking `shutil.copytree` + `subprocess.Popen`) and `test_runner.py:41-111` (`for cand in candidates:` serial loop with no `max_workers` or total deadline).
  2. Call `agent_fix_tournament` with 500 large candidate diffs -> accepted cleanly without cap.
  3. Expected: Async tool handlers or worker offloading, bounded payload/candidate counts, and bounded parallel evaluation with a total deadline.
  4. Actual: Event loop blocks synchronously per candidate and direct tool calls are unbounded.
- **Screenshots / evidence:** No screenshot: headless MCP server; confirmed across `src/bugarena/server.py:92-452` and `src/bugarena/evaluation/test_runner.py:41-111`.
- **Recommended fix (NOT applied):** Make slow MCP tools `async def` calling `await asyncio.to_thread(...)`, parallelize `PatchEvaluator.evaluate_candidates` via bounded `ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 2))` with an overall wall-clock budget, and enforce candidate-count (`<=20`) and diff-size limits consistently across `agent_fix_tournament` and `evaluate_patches`.
  ```python
  # BEFORE (src/bugarena/evaluation/test_runner.py:41)
  for cand in candidates:
      with manager.create_sandbox() as sandbox_path:
          ...

  # AFTER
  with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, max(1, len(candidates)))) as pool:
      evaluations = list(pool.map(_evaluate_single_candidate, candidates))
  ```
  - *Risks/Side effects:* Concurrent temp sandboxes increase peak disk/CPU usage by `max_workers`x (`manager.py` exclude improvements in `BUG-017` mitigate disk growth).
  - *Suggested regression tests:* Verify `agent_fix_tournament` rejects >20 candidates / oversized diffs and parallel candidate evaluation completes safely.
- Related bugs: BUG-017, BUG-021, BUG-033

---

### BUG-038 — `TournamentRunner` Silently Collapses Timeouts/Rejections into Empty Candidate Lists and Ignores Explicit `personas=[]`
- Severity: High   Confidence: Confirmed
- Category: error-handling
- Location: `src/bugarena/tournament/runner.py:30-39,53-84`; `src/bugarena/tournament/personas/base.py:34`; `src/bugarena/reporting/markdown_formatter.py:129,144-172`
- Found by: silent-failure-hunter, python-reviewer, type-design-analyzer   Verified by: code-architect, Round 2 Dynamic Probe
- **What the bug is:** Four silent-failure defects in `TournamentRunner` & persona lookup:
  1. `runner.py:30-37`: `list(personas or [...])` checks truthiness instead of `is not None`, so explicitly passing `personas=[]` silently executes 3 default personas!
  2. `runner.py:67-72`: When all personas time out (`TimeoutError`), fail patch validation (`PatchValidationError`), or encounter API errors (`"", "Missing ... API_KEY"`), `generate_single` logs a warning and returns `None`; `run_tournament` returns `(tournament_id, [])` with zero error metadata explaining why no candidates survived. *(Note: `asyncio.wait_for` timeouts raise builtin `TimeoutError` in Python 3.11+.)*
  3. `runner.py:68`: Logs `logger.warning("Persona %s generation rejected: %s", ...)` cleanly, though empty diffs return `Invalid diff header: diff content is empty` instead of surfacing provider error strings like `"Missing GEMINI_API_KEY"`.
  4. `personas/base.py:34`: `get_persona_prompt(persona)` silently falls back to `SURGICAL_MINIMALIST` for unrecognized persona keys instead of raising `KeyError`/`ValueError`.
- **What the bug does:** Callers cannot distinguish an API auth failure, rate-limit HTTP error, timeout, or LLM invalid-diff error from "no fixes found", wasting developer time debugging empty tournaments, while passing `personas=[]` surprises callers by running 3 agents anyway.
- **How to reproduce:**
  1. Call `TournamentRunner(personas=[])` and check `runner.personas`.
  2. Run `await runner.run_tournament(bug_spec, repro_spec, timeout_seconds=0.05)` against a generator sleeping `1.0s`.
  3. Expected: `personas=[]` stays empty (or validates non-empty explicitly); all-timeout tournament raises or returns structured per-persona failure diagnostics.
  4. Actual: `runner.personas` silently resets to 3 personas, and timed-out tournament returns `(tournament_id, [])` with no failure state.
- **Screenshots / evidence:** No screenshot: headless tournament runner; captured output from [`./evidence/R2-probe-f-eval-runner-flags.txt`](./evidence/R2-probe-f-eval-runner-flags.txt):
  ```text
  personas=[] silently became: ['surgical_minimalist', 'defensive_guardian', 'architectural_fixer']
  timeout -> cands: [] no failure status raised!
  ```
- **Recommended fix (NOT applied):** Use `if personas is None:` (`BUG-022`), record a structured per-persona status/rejection list alongside valid candidates (surfacing dispatcher error `explanation` whenever `raw_diff == ""`), and raise `KeyError` for unknown personas in `get_persona_prompt`.
  ```python
  # BEFORE (src/bugarena/tournament/runner.py:30-31 & 61-69)
  self.personas = list(personas or [...])
  ...
  raw_diff, explanation = await asyncio.wait_for(...)
  return parse_and_validate_patch(raw_diff=raw_diff, ...)

  # AFTER
  self.personas = list(PersonaType) if personas is None else list(personas)
  # If not raw_diff.strip(): record dispatcher error reason `explanation` explicitly rather than generic "diff content is empty".
  ```
  - *Risks/Side effects:* Changing `run_tournament` return shape breaks callers unpacking `(t_id, candidates)` — attach failures on an optional field or `TournamentResult` / method parameter to keep backwards compatibility if needed.
  - *Suggested regression tests:* Verify `TournamentRunner(personas=[]).personas == []` and verify provider error strings (`Missing ... KEY`) are surfaced cleanly instead of discarded.
- Related bugs: BUG-016, BUG-022, BUG-035

---

### BUG-039 — Critical Test-Suite Gaps and Tautological False-Confidence Assertions
- Severity: High   Confidence: Confirmed
- Category: test-gap
- Location: `tests/unit/test_security.py:21-26,64-82,117`; `tests/unit/test_llm_providers.py:77-86,97-100`; `tests/unit/test_evaluation_and_scoring.py`; `tests/unit/test_reporting_and_server.py`; `tests/unit/test_personas_and_diffs.py`
- Found by: pr-test-analyzer   Verified by: code-architect
- **What the bug is:** All 43 existing tests pass in baseline while leaving critical runtime & security paths untested or masked by weak assertions:
  1. `test_security.py:117` asserts `assert 'import os\nos.system("whoami")' not in test_code or r'\"\"\"' in test_code`, a tautology that passes even if RCE injection succeeds cleanly as long as `r'\"\"\"'` appears anywhere in `test_code`.
  2. Zero unit tests exercise `PatchEvaluator` runtime execution (`test_evaluation_and_scoring.py` only tests pure math helpers `scorer.py` & `ast_metrics.py`), allowing `BUG-013`, `BUG-027`, `BUG-028`, and `--version` option injection (`BUG-018`) to pass completely undetected.
  3. Zero HTTP transport mock tests exercise `MultiModelDispatcher._call_gemini`, `_call_openai`, `_call_deepseek`, `_call_groq`, or `_call_ollama` (`test_llm_providers.py:97-100` only checks missing-key fallback on `_call_anthropic`), masking `BUG-016`.
  4. Zero tests cover `EphemeralSandboxManager.apply_patch` multi-file/`-U0`/SQL `--`/CRLF/traversal cases, `load_env_file`, `bug_detect` `.env` exclusion, `agent_fix_tournament` duplicate IDs/`null` fields, `generate_fix_report` `json`/`diff` formats & `FixReport` fields (`BUG-014`), or MCP stdio transport startup.
- **What the bug does:** Produces false regression confidence (`43 passed in 20.61s`) while 14 Critical and 22 High defects ship undetected across security boundaries, patching, scoring, and reporting.
- **How to reproduce:**
  1. Read `tests/unit/test_security.py:117` and inspect coverage across `tests/unit/*.py` + run `.venv\Scripts\pytest.exe -q --tb=short`.
  2. Expected: Every security boundary and core module has negative/edge-case tests failing on regressions.
  3. Actual: All 43 happy-path/partial tests pass (`exit code 0`).
- **Screenshots / evidence:** No screenshot: test suite inspection + Phase 0/Round 6 `pytest` output in [`./evidence/phase0_baseline.txt`](./evidence/phase0_baseline.txt) and [`./evidence/R6-final-git-proof.txt`](./evidence/R6-final-git-proof.txt):
  ```text
  43 passed in 20.61s
  pytest exit_code: 0
  ```
- **Recommended fix (NOT applied):** Replace the `or` tautology at `test_security.py:117` with strict AST validation verifying only intended test nodes exist, add `httpx.MockTransport` tests for all 6 dispatcher providers, and add negative regression suites for `PatchEvaluator`, `apply_patch`, `patch_parser`, `load_env_file`, and `server.py` JSON/diff/duplicate/error paths.
  ```python
  # BEFORE (tests/unit/test_security.py:117)
  assert 'import os\nos.system("whoami")' not in test_code or r'\"\"\"' in test_code

  # AFTER
  tree = ast.parse(test_code)
  assert not any(
      (isinstance(n, ast.Import) and any(a.name == "os" for a in n.names))
      or (isinstance(n, ast.ImportFrom) and n.module == "os")
      for n in ast.walk(tree)
  )
  assert "whoami" not in test_code or ast.get_docstring(tree) is not None
  ```
  - *Risks/Side effects:* Test execution time will increase slightly (~1-3s for offline mocked provider + evaluator tests).
  - *Suggested regression tests:* Add one dedicated test module per bug category noted above (`test_patch_evaluator.py`, `test_config.py`, `test_security_edge_cases.py`).
- Related bugs: BUG-001..BUG-043 (validation blind spot across the suite)

---

### BUG-042 — Unified Diff Normalization Drift: `.strip()` Deletes Trailing Blank Context Lines and Parser Double-Strips `"b/"`
- Severity: High   Confidence: Confirmed
- Category: data-integrity
- Location: `src/bugarena/tournament/patch_parser.py:32,40-41`; `src/bugarena/tournament/providers/dispatcher.py:81,87`; `src/bugarena/sandbox/manager.py:82-83`
- Found by: architect, code-architect   Verified by: architect, code-architect, Round 5 Dynamic Probe
- **What the bug is:** Two diff-normalization bugs span diff extraction, parsing, and application:
  1. `dispatcher.py:81,87` (`match.group(1).strip()` / `raw_match.group(1).strip()`) and `patch_parser.py:32` (`raw_diff.strip()`) strip all leading/trailing whitespace instead of stripping only outer blank lines cleanly (`\n`/`\r`). When a unified diff ends on an unchanged blank context line (`" "` + `"\n"`), `.strip()` deletes that trailing `" "` context line from the hunk while the `@@ -1,3 +1,3 @@` header keeps `old_count=3`. Applying that hunk in `manager.py` replaces 3 original lines with 2 lines, **silently deleting trailing blank lines** (or shifting `offset` on multi-hunk diffs)! Trailing spaces on a final `+`/` ` line are also stripped.
  2. `patch_parser.py:15` (`DIFF_HEADER_PATTERN`) already strips `"b/"` via `(?:b/)?(?P<new_file>\S+)`, then `patch_parser.py:41` runs `target.removeprefix("b/")` a **second** time, whereas `EphemeralSandboxManager.apply_patch` (`manager.py:83`) strips `"b/"` only **once**.
- **What the bug does:** Trailing blank context lines (PEP 8 / EOF / multi-line spacing) get silently truncated during parsing/evaluation, and legitimate repositories with a directory named `b/` (`b/mod.py`, formatted as `+++ b/b/mod.py`) have `patch_parser` record `'mod.py'` while `apply_patch` edits `'b/mod.py'` — causing false protected-path rejections whenever `mod.py` is protected!
- **How to reproduce:**
  1. Parse a diff ending with `" \n"` (`@@ -1,3 +1,3 @@\n-a = 1\n+a = 2\n b = 2\n \n`) via `parse_and_validate_patch`, then apply it via `apply_patch` to `"a = 1\nb = 2\n\n"`.
  2. Parse `--- a/b/mod.py\n+++ b/b/mod.py\n...` with `protected_paths=["mod.py"]` vs `["src/protected.py"]` and apply via `apply_patch`.
  3. Expected: Trailing blank `' '` line survives (`['a = 2\n', 'b = 2\n', '\n']`); `b/mod.py` resolves identically to `'b/mod.py'` across parser and applier.
  4. Actual: Trailing `' '` context line is deleted (`['a = 2\n', 'b = 2\n']`); parser reduces `+++ b/b/mod.py` to `'mod.py'` and falsely rejects edits when `mod.py` is protected while `apply_patch` writes `repo/b/mod.py`.
- **Screenshots / evidence:** No screenshot: headless diff parser/applier; captured output from [`./evidence/R5-gap-closure.txt`](./evidence/R5-gap-closure.txt):
  ```text
  === 1. BUG-042a / BUG-008: double removeprefix('b/') ===
  DIFF_HEADER_PATTERN group('new_file')='b/mod.py' -> patch_parser line 41 removeprefix('b/')='mod.py'
  protected_paths=['mod.py'] falsely rejected b/mod.py? PatchValidationError: Patch modifies protected test file: 'mod.py'
  apply_patch wrote b/mod.py='x = 2\n', mod.py untouched='y = 10\n'

  === 2. Trailing blank context line stripped by .strip() ===
  input lines=['--- a/m.py', '+++ b/m.py', '@@ -1,3 +1,3 @@', '-a = 1', '+a = 2', ' b = 2', ' ']
  parsed lines=['--- a/m.py', '+++ b/m.py', '@@ -1,3 +1,3 @@', '-a = 1', '+a = 2', ' b = 2']
  after applying stripped diff, m.py lines=['a = 2\n', 'b = 2\n'] (trailing blank line deleted!)
  ```
- **Recommended fix (NOT applied):** Preserve significant single-space lines by trimming only leading/trailing empty newlines (`.strip("\r\n")` rather than `.strip()`), and strip `"a/"` / `"b/"` consistently once (or capture `(?:^a/|b/)` strictly without repeating `.removeprefix("b/")` after regex group capture).
  ```python
  # BEFORE (src/bugarena/tournament/patch_parser.py:15,32,40-41 & dispatcher.py:81,87)
  r"^--- (?:a/)?(?P<old_file>\S+)\n\+\+\+ (?:b/)?(?P<new_file>\S+)"
  clean_diff = raw_diff.strip()
  target = m.group("new_file").removeprefix("b/")

  # AFTER
  clean_diff = raw_diff.strip("\r\n")
  target = m.group("new_file")  # pattern already strips one optional 'b/' cleanly
  ```
  - *Risks/Side effects:* Bare diffs lacking trailing newlines behave identically, while diffs ending in trailing space lines keep exact line counts.
  - *Suggested regression tests:* Add diff roundtrip tests for trailing `' '` blank context lines and paths inside a `b/` folder (`+++ b/b/mod.py`).
- Related bugs: BUG-008, BUG-009, BUG-035

---

> **Severity Tier: Medium (7 Bugs — `BUG-030`, `BUG-033`, `BUG-034`, `BUG-036`, `BUG-040`, `BUG-041`, `BUG-043`)**

### BUG-030 — `bug_reproduce` `failure_output` Drops `stdout` and Surfaces Only `stderr` Warnings
- Severity: Medium   Confidence: Confirmed
- Category: error-handling
- Location: `src/bugarena/server.py:132`
- Found by: silent-failure-hunter, python-reviewer   Verified by: code-architect, Round 2 Dynamic Probe
- **What the bug is:** `bug_reproduce` sets `"failure_output": spec.initial_outcome.stderr if spec.initial_outcome else ""` (`server.py:132`), completely discarding `spec.initial_outcome.stdout`. However, `pytest` writes test failure tracebacks, `AssertionError`s, and captured output to `stdout`, while `stderr` contains only deprecation warnings (`PytestDeprecationWarning`) or remains empty.
- **What the bug does:** MCP callers inspecting `failure_output` see only pytest deprecation noise (`pytest-asyncio` warning) or `""` instead of the actual failing assertion or exception, preventing users or agents from confirming the reproduction test failed for the right reason.
- **How to reproduce:**
  1. Call `bug_reproduce` on a repo with a valid failing assertion (`AssertionError`).
  2. Inspect `res["failure_output"]`.
  3. Expected: Includes `AssertionError` / pytest traceback from `stdout` alongside any `stderr`.
  4. Actual: Returns only `PytestDeprecationWarning` from `stderr`, omitting the failure traceback.
- **Screenshots / evidence:** No screenshot: headless MCP server; captured output from [`./evidence/R2-probe-e-server-dispatcher.txt`](./evidence/R2-probe-e-server-dispatcher.txt):
  ```text
  BUG-030 bug_reproduce failure_output empty?: '... PytestDeprecationWarning: The configuration option "asyncio_default_fixture_loop_scope" is unset...' status: REPRODUCED_RED
  ```
- **Recommended fix (NOT applied):** Combine `stdout` and `stderr` cleanly into `failure_output`.
  ```python
  # BEFORE (src/bugarena/server.py:132)
  "failure_output": spec.initial_outcome.stderr if spec.initial_outcome else "",

  # AFTER
  "failure_output": "\n".join(
      part for part in (
          spec.initial_outcome.stdout.strip() if spec.initial_outcome else "",
          spec.initial_outcome.stderr.strip() if spec.initial_outcome else "",
      ) if part
  ),
  ```
  - *Risks/Side effects:* Increases response string length slightly when verbose pytest output appears.
  - *Suggested regression tests:* Assert `"AssertionError"` or the expected exception message appears in `bug_reproduce(...)["failure_output"]`.
- Related bugs: BUG-010, BUG-015, BUG-024

---

### BUG-033 — `generate_fix_report` `format="diff"` Always Writes `.md` Files, JSON Schema Drifts, and Silent 64KB/20 Truncation Occurs
- Severity: Medium   Confidence: Confirmed
- Category: data-integrity
- Location: `src/bugarena/server.py:75,248-312,375-377,441-452`
- Found by: type-design-analyzer, performance-optimizer, silent-failure-hunter, code-reviewer   Verified by: code-architect, Round 2 Dynamic Probe
- **What the bug is:** Three response & side-effect inconsistencies across `server.py`:
  1. `generate_fix_report` (`lines 274-303`) unconditionally writes `reports/bug_report_<t_id>.md` on disk **even when `format="diff"` or `format="json"`** is passed (`format="diff"` writes Markdown instead of `.patch` or skipping disk writes!). Meanwhile `format="json"` returns `"evaluations"` / `"champion_diff"` / `"report"` rather than matching `"markdown"`/`evaluate_patches` (`"leaderboard"`).
  2. `bug_detect` (`line 75`) and `bugarena_autonomous_repair` (`lines 375-377`) silently slice `error_log[:65536]` from the **head** (dropping the **tail**, which is where Python prints the root crash frame and final exception line!) and silently truncate `candidate_patches_raw[:20]` with zero warning.
  3. `generate_fix_report` checks no allowlist on `format` (`"yaml"` silently returns Markdown).
- **What the bug does:** Requesting `format="diff"` unexpectedly pollutes the workspace with `.md` files; callers passing >64KB logs silently lose the crashing exception frame at the bottom of the trace; and submitting 25 candidates silently ignores 5 candidates without notification.
- **How to reproduce:**
  1. Call `generate_fix_report(t_id, format="diff")`.
  2. Pass a 70KB `error_log` whose Python traceback sits at the end to `bug_detect`.
  3. Expected: `format="diff"` returns diff (or saves `.patch` only if requested); oversized traces keep the tail crash frames or return a bounded warning.
  4. Actual: `format="diff"` creates `<repo>/reports/bug_report_tourn_*.md` on disk, and tail tracebacks past 64KB are silently sliced off.
- **Screenshots / evidence:** No screenshot: headless MCP server; captured output from [`./evidence/R2-probe-e-server-dispatcher.txt`](./evidence/R2-probe-e-server-dispatcher.txt):
  ```text
  BUG-033 format='diff' wrote .md file to disk?: True file: ...\repoA\reports\bug_report_tourn_a37c12bf.md
  ```
- **Recommended fix (NOT applied):** Only write Markdown/JSON/patch files when `format == "markdown"` or `output_file` is explicitly supplied (matching format extension), keep the **tail** `error_log[-65536:]` instead of head truncation, and return explicit validation errors (or warnings) when `len(candidate_patches_raw) > 20` or `format` is invalid.
  ```python
  # BEFORE (src/bugarena/server.py:75 & 275-279)
  bounded_error_log = error_log[:65536] if len(error_log) > 65536 else error_log
  out_path = output_file
  if not out_path:
      out_path = str(Path(tournament.repo_path) / "reports" / f"bug_report_{tournament.tournament_id}.md")
  saved_path = save_markdown_report(report_md, out_path)

  # AFTER
  bounded_error_log = error_log[-65536:] if len(error_log) > 65536 else error_log
  saved_path = None
  if format == "markdown" or output_file:
      ...
  ```
  - *Risks/Side effects:* Workflows calling `generate_fix_report(t_id, format="diff")` expecting a side-effect `.md` report would need `format="markdown"` or explicit `output_file`.
  - *Suggested regression tests:* Verify `format="diff"` does not write `.md` when `output_file=""`, and verify `bug_detect` extracts trace frames from the end of a >70KB error log.
- Related bugs: BUG-003, BUG-014, BUG-037

---

### BUG-034 — `locate_faulty_ast_slice` Returns Inverted Empty Range `(1, 0)` and Cross-Matches Same-Named Methods Across Classes
- Severity: Medium   Confidence: Confirmed
- Category: logic
- Location: `src/bugarena/discovery/ast_analyzer.py:57-101`
- Found by: code-reviewer, python-reviewer, type-design-analyzer, silent-failure-hunter   Verified by: code-architect, Round 2 Dynamic Probe
- **What the bug is:** Two AST slicing bugs in `locate_faulty_ast_slice`:
  1. When `file_content` is empty (`lines = []`, `len(lines) == 0`), fallback lines `92-93` compute `start = max(1, min(target_line - 5, 0)) = 1` and `end = min(0, ...) = 0`, returning an invalid inverted `line_range=(1, 0)`.
  2. Inside `FaultVisitor._check_func` (`lines 65-68`), `if self.target_func and node.name == self.target_func:` unconditionally overwrites `name_matched_node` / `name_matched_class` across **every** class/nested scope. When `target_line` falls outside function definitions (e.g., top-level `def run():` call or module line), `visitor.matched_node` is `None`, so line `75` falls back to `visitor.name_matched_node` — attributing a top-level crash or nested scope to `Helper.run` and copying `Helper.run`'s docstring while pairing it with a different line snippet! Even worse, when `visitor.matched_node` IS found cleanly, `line 81-82` (`cls_name = visitor.matched_class or visitor.name_matched_class`) steals `name_matched_class` and `name_matched_docstring` from an unrelated class if `matched_node` was a top-level function lacking a class or docstring!
- **What the bug does:** Top-level functions named `run()` / `process()` get misattributed to an unrelated class `Helper` (with `Helper.run`'s docstring injected into suspect diagnostics), and empty files emit `(1, 0)` ranges that fail line-range invariants (`BUG-023`).
- **How to reproduce:**
  1. Call `locate_faulty_ast_slice("", target_line=1)`.
  2. Call `locate_faulty_ast_slice("def run():\n    return 1\n\nclass Helper:\n    def run(self):\n        '''Helper doc'''\n        return 2\n", target_line=2, function_name="run")`.
  3. Expected: Empty file returns `(0, 0)` or `None`; `target_line=2` (`def run()`) returns `class_name=None, docstring=None`.
  4. Actual: Empty file returns `(1, 0)`; `target_line=2` returns `{'function_name': 'run', 'class_name': 'Helper', 'line_range': (1, 2), 'code_snippet': 'def run():\n    return 1', 'docstring': 'Helper doc'}`.
- **Screenshots / evidence:** No screenshot: headless AST slicer; captured output from [`./evidence/R2-probe-d-eval-discovery.txt`](./evidence/R2-probe-d-eval-discovery.txt):
  ```text
  === BUG-034: ast_analyzer empty & cross-method leak ===
  empty file line_range: (1, 0)
  cross-method leak for top-level run(): {'function_name': 'run', 'class_name': 'Helper', 'line_range': (1, 2), 'code_snippet': 'def run():\n    return 1', 'docstring': 'Helper doc'}
  ```
- **Recommended fix (NOT applied):** Return `None` when `not lines`, read `cls_name`/`doc` exclusively from the chosen `node` (`matched_node` first, else `name_matched_node`) rather than combining `or` across separate visitors, and prefer top-level over nested/method name fallbacks (or store only first match cleanly).
  ```python
  # BEFORE (src/bugarena/discovery/ast_analyzer.py:75-83 & 92-94)
  node = visitor.matched_node or visitor.name_matched_node
  if node:
      ...
      cls_name = visitor.matched_class or visitor.name_matched_class
      doc = visitor.matched_docstring or visitor.name_matched_docstring

  # AFTER
  if not lines:
      return None
  if visitor.matched_node:
      cls_name, doc = visitor.matched_class, visitor.matched_docstring
  else:
      cls_name, doc = visitor.name_matched_class, visitor.name_matched_docstring
  ```
  - *Risks/Side effects:* Empty files inside `BugDiscoveryEngine` fall back cleanly to raw trace line numbers instead of bogus `(1, 0)` ranges.
  - *Suggested regression tests:* Unit tests for empty `""` input and top-level `run()` coexisting with `Helper.run()`.
- Related bugs: BUG-023, BUG-025, BUG-026

---

### BUG-036 — `scripts/check_api_keys.py` Crashes on HTML `check_ollama` Responses, Performs Unconditional Live Paid Calls, and Hardcodes Config Paths
- Severity: Medium   Confidence: Confirmed
- Category: error-handling
- Location: `scripts/check_api_keys.py:20-200`
- Found by: python-reviewer, silent-failure-hunter, security-reviewer, performance-optimizer   Verified by: code-architect, Round 2 Dynamic Probe
- **What the bug is:** `check_ollama()` (`lines 152-166`) parses `resp.json()` inside `try ... except (httpx.HTTPError, OSError):` — failing to catch `ValueError` / `json.JSONDecodeError`! Additionally, non-200 HTTP responses from port 11434 (e.g., `500` proxy error) report `"OFFLINE - Not running"` instead of the HTTP status, `line 199` hardcodes Windows-specific `C:\Users\nisha\.gemini\config\mcp_config.json`, and running the script unconditionally initiates paid live HTTP requests across all configured providers with no `--dry-run` / `--validate-only` flag.
- **What the bug does:** If another local service or reverse proxy returns HTTP 200 HTML/text on port `11434`, `scripts/check_api_keys.py` crashes with `json.JSONDecodeError`; `HTTP 500` errors on Ollama are misdiagnosed as `"OFFLINE"`; and non-Windows/other-user machines see another developer's hardcoded path.
- **How to reproduce:**
  1. Mock `httpx.AsyncClient.get` for `check_ollama()` returning status `200` with `<html><body>Proxy</body></html>` (and status `500`).
  2. Expected: Returns structured `{"provider": "Local Ollama", "status": "ERROR", ...}` cleanly without crashing.
  3. Actual: HTTP `200` HTML raises unhandled `JSONDecodeError`; HTTP `500` returns `"OFFLINE"`.
- **Screenshots / evidence:** No screenshot: CLI utility script; captured output from [`./evidence/R2-probe-c2-pytest-bytes-ollama.txt`](./evidence/R2-probe-c2-pytest-bytes-ollama.txt):
  ```text
  === CHECK BUG-036 check_api_keys.check_ollama HTTP 200 HTML / HTTP 500 ===
  ollama 200 HTML CRASHED: JSONDecodeError Expecting value: line 1 column 1 (char 0)
  ollama 500 -> {'provider': 'Local Ollama', 'status': 'OFFLINE', 'message': 'Not running on localhost:11434.'}
  ```
- **Recommended fix (NOT applied):** Catch `(httpx.HTTPError, OSError, ValueError)` in `check_ollama`, distinguish non-200 HTTP status codes from unreachable sockets, build `Path.home() / ".gemini" / "config" / "mcp_config.json"` dynamically, and support a `--dry-run` / key-presence check flag.
  ```python
  # BEFORE (scripts/check_api_keys.py:157-166)
  if resp.status_code == 200:
      models = [m.get("name") for m in resp.json().get("models", [])]
      return ...
  except (httpx.HTTPError, OSError):
      return {"provider": "Local Ollama", "status": "OFFLINE", ...}

  # AFTER
  if resp.status_code == 200:
      models = [m.get("name") for m in resp.json().get("models", [])]
      return ...
  return {"provider": "Local Ollama", "status": "ERROR", "message": f"HTTP {resp.status_code} from localhost:11434"}
  # except (httpx.HTTPError, OSError, ValueError) as exc: ...
  ```
  - *Risks/Side effects:* Minor CLI flag adjustment if adding `--dry-run` (`default=False` keeps existing live behavior when explicitly requested).
  - *Suggested regression tests:* Mock HTTP 200 non-JSON and HTTP 500 responses on `check_ollama()` cleanly.
- Related bugs: BUG-016, BUG-040

---

### BUG-040 — `README.md` & `.agents/skills/bugarena-repair/SKILL.md` Documentation Contract Drift
- Severity: Medium   Confidence: Confirmed
- Category: build/config
- Location: `README.md:10,41-45,50-76,107-117`; `.agents/skills/bugarena-repair/SKILL.md:27,76,91-110`
- Found by: comment-analyzer, code-reviewer   Verified by: code-architect
- **What the bug is:** Multiple documented contracts conflict directly with implementation:
  1. `README.md:50-60` documents only 6 MCP tools, omitting `generate_bug_report` (implemented in `server.py:316`).
  2. `README.md:10` and `43-44` describe automatic multi-agent LLM generation and `--network=none, jails, isolated subshell/tempfs` container isolation (`BUG-005`, `BUG-022`), neither of which occurs when invoking MCP server tools.
  3. `README.md:68-75` and `SKILL.md:72-76` claim an active Syntax & AST Gate (`BUG-013`), `Q_complexity`, and `Q_mutation` formula, whereas `test_runner.py` hardcodes `delta_cc = 0` and `scorer.py` sets missing `mutation_kill_ratio` to `1.0`.
  4. `README.md:112` hardcodes `"D:/MCP server/.venv/Scripts/python.exe"` instead of portable instructions.
  5. `.agents/skills/bugarena-repair/SKILL.md:106` shows an example unified diff (`"--- a/src/calc.py\n+++ b/src/calc.py\n@@ -3,2 +3,4 @@\n+    if b == 0: return 0.0\n"`) whose `@@` counts (`-3,2 +3,4`) don't match its single-line `+` hunk body (and `agent_fix_tournament` examples/tests rely on matching line offsets cleanly), while `SKILL.md:27` tells users to configure `mcp_config.json` with zero note on API keys vs pre-supplied `candidate_patches_raw`.
- **What the bug does:** Users and AI agents following `README.md` or `SKILL.md` assume container/network isolation that does not exist, overlook `generate_bug_report`, copy non-portable developer paths, and rely on scoring guarantees that are unimplemented.
- **How to reproduce:**
  1. Compare `README.md` (`lines 10, 41-45, 50-76, 107-117`) and `.agents/skills/bugarena-repair/SKILL.md` against `server.py`, `manager.py`, `test_runner.py`, and `scorer.py`.
  2. Expected: Docs match actual exported tools, isolation level, scoring behavior, and valid example diffs.
  3. Actual: Tool counts, isolation claims, AST/mutation gates, and example diffs disagree with code.
- **Screenshots / evidence:** No screenshot: markdown documentation vs Python source; directly verified by comparing `README.md:1-122` and `.agents/skills/bugarena-repair/SKILL.md:1-111` against `src/bugarena/server.py` and `src/bugarena/evaluation/test_runner.py`.
- **Recommended fix (NOT applied):** Update `README.md` to add `generate_bug_report`, replace hardcoded `"D:/MCP server/..."` with placeholders, align scoring/isolation descriptions with actual behavior (or implement the missing gates first), and fix the sample diff in `SKILL.md:106`.
  ```json
  // BEFORE (README.md:112)
  "command": "D:/MCP server/.venv/Scripts/python.exe"

  // AFTER
  "command": "/path/to/repo/.venv/Scripts/python"
  ```
  - *Risks/Side effects:* Pure documentation update; clarifies security posture immediately for operators.
  - *Suggested regression tests:* Add a CI doc check confirming every `@mcp.tool()` registered on `mcp.list_tools()` appears in `README.md` and `SKILL.md`.
- Related bugs: BUG-005, BUG-013, BUG-022, BUG-043

---

### BUG-041 — `validate_safe_path` Accepts `""` and `"."` Targeting Sandbox Root and Raises Unhandled `ValueError` on Embedded NUL Bytes
- Severity: Medium   Confidence: Confirmed
- Category: security
- Location: `src/bugarena/sandbox/security.py:38-60`; `src/bugarena/sandbox/manager.py:92`
- Found by: code-architect   Verified by: architect, Round 3 Dynamic Probe
- **What the bug is:** `validate_safe_path(base_dir, target_path)` resolves `(base_resolved / Path("")).resolve()` and `(base_resolved / Path(".")).resolve()` to `base_resolved` itself; `base_resolved.relative_to(base_resolved)` succeeds cleanly (`Path('.')`), returning the base directory rather than rejecting empty or root-pointing targets! In addition, passing a path containing an embedded NUL byte (`"\x00"`) lets `Path.resolve()` raise an unhandled `ValueError: embedded null byte` rather than `SecurityViolationError`.
- **What the bug does:** Downstream callers expecting `validate_safe_path` to guard file paths (`manager.py:92` when `target_rel="."`, or future callers passing `output_file=""`) receive a directory `Path` equal to the sandbox root (causing raw `IsADirectoryError` / `PermissionError` rather than `SecurityViolationError`), and NUL-byte inputs escape typed security handling.
- **How to reproduce:**
  1. Call `validate_safe_path(tmp_dir, "")`, `validate_safe_path(tmp_dir, ".")`, and `validate_safe_path(tmp_dir, "a.py\x00.txt")`.
  2. Expected: All three raise `SecurityViolationError`.
  3. Actual: `""` and `"."` return `tmp_dir.resolve()` cleanly (`empty==base: True`, `dot==base: True`), while `"\x00"` raises raw `ValueError`.
- **Screenshots / evidence:** No screenshot: headless security helper; captured output from [`./evidence/R3-deep-edge-probes.txt`](./evidence/R3-deep-edge-probes.txt):
  ```text
  === TEST 4: validate_safe_path empty/dot/NUL ===
  empty==base: True dot==base: True
  ```
- **Recommended fix (NOT applied):** Explicitly reject empty strings, `"\x00"` bytes, and `candidate == base_resolved` (unless `allow_root=True` is explicitly requested) by raising `SecurityViolationError`.
  ```python
  # BEFORE (src/bugarena/sandbox/security.py:44-59)
  base_resolved = Path(base_dir).resolve()
  target_p = Path(target_path)
  ...
  candidate.relative_to(base_resolved)

  # AFTER
  if not target_path or not target_path.strip() or "\x00" in target_path:
      raise SecurityViolationError(f"Invalid target path: {target_path!r}")
  ...
  if candidate == base_resolved:
      raise SecurityViolationError(f"Target path resolves to base directory itself: '{target_path}'")
  ```
  - *Risks/Side effects:* Any legitimate caller validating `base_dir` itself would need `allow_root=True`.
  - *Suggested regression tests:* Add unit tests in `test_security.py` asserting `SecurityViolationError` for `""`, `"."`, and `"foo\x00bar"`.
- Related bugs: BUG-003, BUG-008, BUG-009

---

### BUG-043 — Repository Hygiene & Template Gaps: `.gitignore` Omits `.env.*` and `reports/`, Keeps Stale Entries, and `.env.example` / `config.py` Paths Drift
- Severity: Medium   Confidence: Confirmed
- Category: build/config
- Location: `.gitignore:38-40`; `.env.example:2-14`; `.ruff_cache/.gitignore:1-2`; `scripts/check_api_keys.py:199`; `src/bugarena/config.py:21,30-34`
- Found by: Main Auditor   Verified by: architect, Round 5 Dynamic Probe
- **What the bug is:** Repository hygiene & template files have three interacting defects *(tracked under pre-dedup working tag `BUG-045` in Round 5 evidence logs)*:
  1. `.gitignore:38-40` ignores only `.env` (not `.env.*` with `!.env.example`), leaving `.env.local` and `.env.production` (explicitly treated as sensitive secret files by `manager.py:39-40`) **unignored** by Git! It also omits `reports/` (where `server.py:277,349` writes `reports/bug_report_*.md` inside target repos by default), omits `.ruff_cache/` in root `.gitignore` (relying solely on Ruff's self-generated `.ruff_cache/.gitignore`), and retains unused entries `workspace_temp/` and `tests/repro_temp/`.
  2. `.env.example:2` (like `scripts/check_api_keys.py:199`) instructs users to configure keys in `~/.gemini/config/mcp_config.json`, while omitting `config.py:21`'s actual `.env` fallback (`~/.gemini/.env`).
  3. `.env.example:5,8,11,14` leaves blank placeholders (`GEMINI_API_KEY=`, etc.); copying `.env.example` to `.env` with unused keys blank poisons fallback keys due to `config.py:33` (`BUG-019`).
- **What the bug does:** Developers running BugArena tools or keeping multi-environment secret files risk accidentally staging `.env.local`, `.env.production`, or `reports/*.md` into Git commits, while `.env.example` setup instructions fail to document `~/.gemini/.env` and interact destructively with blank `KEY=` placeholders.
- **How to reproduce:**
  1. Run `git check-ignore .env.local`, `git check-ignore .env.production`, `git check-ignore reports/bug_report_x.md`, and `git check-ignore .env.example`.
  2. Compare `.env.example:2` against `src/bugarena/config.py:16-22`.
  3. Expected: `.env.*` (except `!.env.example`) and `reports/` are ignored (`rc=0`); `.env.example` matches `config.py`.
  4. Actual: `.env.local`, `.env.production`, and `reports/bug_report_x.md` all return `rc=1` (NOT ignored by Git).
- **Screenshots / evidence:** No screenshot: repository config audit; captured output from [`./evidence/R5-gitignore-and-lru.txt`](./evidence/R5-gitignore-and-lru.txt) and [`./evidence/R5-gap-closure.txt`](./evidence/R5-gap-closure.txt):
  ```text
  git check-ignore .env                      -> ignored? True
  git check-ignore .env.local                -> ignored? False
  git check-ignore .env.production           -> ignored? False
  git check-ignore reports/x.md              -> ignored? False
  git check-ignore tests/repro/test_x.py     -> ignored? False
  git check-ignore .ruff_cache/x             -> ignored? True
  git check-ignore .env.example              -> rc=1 ignored=False
  ```
- **Recommended fix (NOT applied):** Ignore `.env.*` (preserving `!.env.example`), `reports/`, `tests/repro/`, and `.ruff_cache/` cleanly in `.gitignore`, remove unused `workspace_temp/` / `tests/repro_temp/`, comment out placeholders in `.env.example` (`# GEMINI_API_KEY=`), and document `~/.gemini/.env` accurately alongside MCP config.
  ```gitignore
  # BEFORE (.gitignore:37-40)
  # Project Temporary
  .env
  workspace_temp/
  tests/repro_temp/

  # AFTER
  # Project Temporary & Local Environment
  .env
  .env.*
  !.env.example
  .ruff_cache/
  reports/
  tests/repro/
  ```
  - *Risks/Side effects:* Ignoring `tests/repro/` prevents accidental check-in of generated repro scratch files; legitimate permanent repro regression suites should live under `tests/unit/` or `tests/integration/`.
  - *Suggested regression tests:* CI check running `git check-ignore` on `.env.local`, `.env.production`, `reports/sample.md`, and confirming `!.env.example` remains tracked (`rc=1`).
- Related bugs: BUG-017, BUG-019, BUG-040

---

## 4. Appendix A: Dismissed False Positives & Scoped Down Hypotheses

Five initial static hypotheses from Round 1 were dynamically disproved or narrowed in Rounds 2–5:

1. **`FP-001` — New-File Creation Diffs (`--- /dev/null -> +++ b/new.py`) Fail in `apply_patch`:** Dismissed in Round 3 ([`./evidence/R3-deep-edge-probes.txt`](./evidence/R3-deep-edge-probes.txt)). Applying `--- /dev/null`, `+++ b/new_created.py`, `@@ -0,0 +1,2 @@` cleanly creates the file with exact contents `['def hello():', '    return 42']`. Only **file deletion** (`+++ /dev/null`) triggers `SecurityViolationError` (`BUG-009`).
2. **`FP-002` — Sequential Multi-Hunk Offsets Always Corrupt Single Files:** Dismissed in Round 3 ([`./evidence/R3-deep-edge-probes.txt`](./evidence/R3-deep-edge-probes.txt)). A valid two-hunk diff on the same file shifts offsets accurately (`['line1', 'line4', ..., 'INSERTED', 'line9', 'line10', 'line11']`). Offset corruption occurs specifically on `-U0` inserts (`old_count == 0`), trailing blank context stripping (`BUG-042`), `--` SQL comments, or mismatched context (`BUG-009`).
3. **`FP-003` — `run_sandboxed_command` Crashes with `UnicodeDecodeError` on All Non-ASCII Characters on Windows:** Dismissed in Round 2 ([`./evidence/R2-probe-c-sandbox-runner.txt`](./evidence/R2-probe-c-sandbox-runner.txt), [`./evidence/R2-probe-c2-pytest-bytes-ollama.txt`](./evidence/R2-probe-c2-pytest-bytes-ollama.txt)). On this Python 3.14 Windows host (`preferredencoding == utf-8`), valid UTF-8 characters (`✓ utf8`) pass cleanly (`exit_code=0`). The actual observed failure is silent output loss (`stdout=''`) in `_readerthread` on invalid raw byte sequences (`BUG-015`, downgraded Critical -> High).
4. **`FP-004` — Existing-Test Collection Errors (`exit code 2`) Bypass `PatchEvaluator`'s Zero-Regression Gate via `"no tests ran"`:** Dismissed in Round 2 ([`./evidence/R2-probe-f-eval-runner-flags.txt`](./evidence/R2-probe-f-eval-runner-flags.txt)). On `pytest 9.2.0`, collection errors inside existing `tests/*.py` print `'1 error in 0.95s'` *without* `"no tests ran"`, so `PatchEvaluator` disqualifies them (`regressions=1, score=0.0`). The bypass specifically hits repos with **missing** (`exit 4`) or **empty** (`exit 5`) `tests/` directories — both print `"no tests ran"` — or broken syntax in files unimported by `tests/` (`BUG-013`).
5. **`FP-005` — Double `removeprefix("b/")` Allows Bypassing Protected Paths Inside `b/` Subdirectories:** Dismissed in Round 5 ([`./evidence/R5-gap-closure.txt`](./evidence/R5-gap-closure.txt)). Because `patch_parser.py:48` uses symmetric substring checks (`clean_prot in mod or mod in clean_prot`), `"secret.py" in "b/secret.py"` still matches and blocks `+++ b/b/secret.py`. The verified impact is the **reverse**: false-positive rejection of `b/mod.py` whenever `mod.py` is protected plus parser-vs-sandbox target path divergence (`BUG-042`).

---

## 5. Appendix B: Unverified Suspicions & Environmental Limits

Four sub-claims remain statically inferred / unverified dynamically due to OS platform limits or Read-Only Audit Hard Rule 5:

1. **`UNV-001` — >64KB Pipe Deadlock During `subprocess.TimeoutExpired` Fallback (`src/bugarena/sandbox/runner.py:72-74`):** `proc.communicate()` after `proc.kill()` / `taskkill` uses no secondary timeout and `proc.kill()` does not terminate POSIX process-group children (`start_new_session` / `os.killpg`). High-volume >64KB pipe fill plus orphaned grandchild pipe inheritance on POSIX was not triggered dynamically on this Windows host.
2. **`UNV-002` — Host File Copy via Symlink Dereference in `EphemeralSandboxManager.create_sandbox` (`src/bugarena/sandbox/manager.py:52-57`):** Statically confirmed because `shutil.copytree` defaults to `symlinks=False` (`follow_symlinks=True`), dereferencing symlinks when copying into the temp sandbox. Runtime creation of symlinks failed on this Windows host without Administrator/Developer Mode privileges (`OSError [WinError 1314]` in [`./evidence/R3-deep-edge-probes.txt`](./evidence/R3-deep-edge-probes.txt)).
3. **`UNV-003` — Live External Provider API Behavior & Quota/Payload Handling (`src/bugarena/tournament/providers/dispatcher.py:186-348`):** Per Hard Rule 5 (zero live paid external API calls during read-only audit), live Gemini, OpenAI, DeepSeek, Groq, and Anthropic HTTP calls were skipped and verified strictly via `httpx.MockTransport` (`BUG-016`). Live compatibility of default model IDs (`"qwen/qwen3.8-27b"`, `"gemma-4-26b-a4b-it"`, `"o3-mini"`, `"deepseek-reasoner"`) was not re-probed against vendor APIs during this audit.
4. **`UNV-004` — `OrderedDict RuntimeError` Under Tight Concurrent `evaluate_patches` + `_store_tournament` Execution (`src/bugarena/server.py:212`):** The unlocked `_TOURNAMENT_REGISTRY.get(tournament_id)` read in `evaluate_patches` is confirmed statically, while an 8-thread stress check in [`./evidence/R5-gap-closure.txt`](./evidence/R5-gap-closure.txt) completed cleanly under CPython GIL timing without triggering a `RuntimeError`.

---

## 6. Appendix C: Systemic Patterns & Recommended Remediation Order

### Five Systemic Root-Cause Clusters

1. **Cluster A — Unvalidated Code & Flag Injection (`BUG-001`, `BUG-002`, `BUG-018`, `BUG-024`):** Caller and LLM inputs flow directly into executable test strings (`test_generator.py`), raw `repro_code` execution (`evaluate_patches`), and bare `pytest` CLI arguments lacking `--`.
2. **Cluster B — Absent Containment & Path Trust Boundary Leaks (`BUG-003`, `BUG-004`, `BUG-005`, `BUG-017`, `BUG-029`, `BUG-041`):** Documentation claims container/network isolation while running host subprocesses; `output_file`, `.env` reads, read-only cleanup, symlinks, NUL/root paths, and Windows/Unix path scrubbing repeatedly break confinement.
3. **Cluster C — Ad-Hoc Parsing of Structured Formats (`BUG-008`, `BUG-009`, `BUG-019`, `BUG-026`, `BUG-035`, `BUG-042`):** Hand-rolled string splitting and naive regexes handle unified diffs, Python tracebacks, and `.env` files instead of strict parsers (`git apply`/hunk state machines, line-anchored frame/chain parsers, standard `python-dotenv` semantics).
4. **Cluster D — Fail-Open & Silent Error Swallowing (`BUG-010`, `BUG-011`, `BUG-012`, `BUG-013`, `BUG-015`, `BUG-027`, `BUG-028`, `BUG-038`):** Timeouts, empty test suites, `ImportError`s, empty suspect lists, missing `tests/` folders, syntax errors, and `apply_patch` security exceptions silently produce passing or generic outcomes instead of failing fast.
5. **Cluster E — Cross-Layer Contract Drift (`BUG-006`, `BUG-007`, `BUG-014`, `BUG-016`, `BUG-020`, `BUG-021`, `BUG-022`, `BUG-023`, `BUG-030`..`BUG-033`, `BUG-036`, `BUG-037`, `BUG-039`, `BUG-040`, `BUG-043`):** Missing `httpx`/`__init__.py`, broken `FixReport` kwargs, disconnected `TournamentRunner`, mismatched `dispatcher` routing, broken `_REPRO_REGISTRY` matching, FIFO eviction, test blind spots, and drifted docs/`README`/`.gitignore`.

### Suggested Fix Execution Sequence

1. **Phase 1 — Contain Security & RCE Immediately:** Lock down `output_file` with `validate_safe_path` (`BUG-003`, `BUG-041`), block `.env` / non-source reads in `bug_detect` (`BUG-004`), insert `--` and hyphen guards on `pytest` (`BUG-018`), AST-whitelist `call_expr`/`expected_behavior` and require verified Red baselines for `repro_code` (`BUG-001`, `BUG-002`), and add OS/container execution or update docs honestly (`BUG-005`).
2. **Phase 2 — Fix Packaging, Config, and Hygiene:** Add `httpx` to `pyproject.toml` (`BUG-006`), add `personas/__init__.py` + `__all__` exports (`BUG-007`), fix `load_env_file` precedence/encoding/empty-key behavior (`BUG-019`), and harden `.gitignore` / `.env.example` (`BUG-043`).
3. **Phase 3 — Restore Sandbox, Diff & Evaluation Correctness:** Replace custom `_apply_hunks` + `DIFF_HEADER_PATTERN` with strict context-verified diff handling and canonical path normalization (`BUG-008`, `BUG-009`, `BUG-042`), fix `validate_red_baseline` to require `exit_code == 1` & no timeout (`BUG-010`), remove swallowed `ImportError` & fix `root_dir` (`BUG-011`, `BUG-024`), fail fast on empty `suspects` (`BUG-012`), wire AST syntax checks + `calculate_cyclomatic_delta` + real regression counts + honest `Q_mutation` (`BUG-013`, `BUG-027`, `BUG-028`), fix `_readerthread` UTF-8 handling (`BUG-015`), and fix Windows read-only cleanup + exclusions (`BUG-017`).
4. **Phase 4 — Align Server Registries, Dispatcher, Reporting, and Async Boundaries:** Fix `FixReport` schema & `TournamentRecord.report_file_path` (`BUG-014`), lock `evaluate_patches` + implement true LRU (`BUG-021`), enforce model immutability/`extra="forbid"`/`StrEnum` (`BUG-023`), fix `_REPRO_REGISTRY` repo scoping, `failure_output` stdout, duplicate IDs/`null`, `format="diff"` side effects, and tail truncation (`BUG-030`..`BUG-033`), fix dispatcher model/Ollama/`None`/regex bugs and wire/align `TournamentRunner` (`BUG-016`, `BUG-020`, `BUG-022`, `BUG-035`, `BUG-038`), offload blocking tools (`BUG-037`), and fix `check_ollama` (`BUG-036`).
5. **Phase 5 — Tests & Documentation:** Replace tautological tests and add full negative/mocked coverage (`BUG-039`), then sync `README.md` and `SKILL.md` (`BUG-040`).
