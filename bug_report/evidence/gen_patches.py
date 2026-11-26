"""Generate exact unified diffs via difflib and verify locally in EphemeralSandboxManager."""

import ast
import difflib
import json
import sys
from pathlib import Path

from bugarena.sandbox.manager import EphemeralSandboxManager
from bugarena.sandbox.runner import run_sandboxed_command
from bugarena.tournament.patch_parser import parse_and_validate_patch
from bugarena.models.agent import PersonaType


def make_diff(rel_path: str, old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            n=1,
        )
    )
    return diff.rstrip("\n")


def read_src(rel_path: str) -> str:
    return Path(rel_path).read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str) -> str:
    assert old in text, f"Target not found:\n{old}"
    return text.replace(old, new, 1)


def build_all() -> dict[str, dict]:
    specs = {}

    # BUG-005: manager.py apply_patch
    mgr_src = read_src("src/bugarena/sandbox/manager.py")
    p5_surg = replace_once(
        mgr_src,
        '''            if line.startswith(("--- a/", "--- ")):
                # Next line should be +++ b/path
                target_rel = None
                if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                    target_rel = lines[i + 1][4:].strip()
                    target_rel = target_rel.removeprefix("b/")
                    i += 2''',
        '''            if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                # Next line should be +++ b/path
                target_rel = None
                if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                    target_rel = lines[i + 1][4:].split("\\t", 1)[0].strip()
                    target_rel = target_rel.removeprefix("b/")
                    i += 2''',
    )
    p5_surg = replace_once(
        p5_surg,
        '''                while i < len(lines) and not (
                    lines[i].startswith("--- a/") or lines[i].startswith("--- ")
                ):''',
        '''                while i < len(lines) and not (
                    lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")
                ):''',
    )
    p5_surg = replace_once(
        p5_surg,
        '''                            and not lines[i].startswith("--- ")''',
        '''                            and not (lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "))''',
    )

    p5_def = replace_once(
        mgr_src,
        '''            if line.startswith(("--- a/", "--- ")):
                # Next line should be +++ b/path
                target_rel = None
                if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                    target_rel = lines[i + 1][4:].strip()
                    target_rel = target_rel.removeprefix("b/")
                    i += 2
                else:
                    i += 1
                    continue

                if not target_rel:
                    continue''',
        '''            if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                old_rel = line[4:].split("\\t", 1)[0].strip().removeprefix("a/")
                target_rel = lines[i + 1][4:].split("\\t", 1)[0].strip().removeprefix("b/")
                i += 2
                if target_rel == "/dev/null":
                    if old_rel and old_rel != "/dev/null":
                        del_path = validate_safe_path(sandbox_path, old_rel)
                        if del_path.is_file():
                            del_path.unlink()
                    continue
                if not target_rel:
                    continue''',
    )
    p5_def = replace_once(
        p5_def,
        '''                while i < len(lines) and not (
                    lines[i].startswith("--- a/") or lines[i].startswith("--- ")
                ):''',
        '''                while i < len(lines) and not (
                    lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")
                ):''',
    )
    p5_def = replace_once(
        p5_def,
        '''                            and not lines[i].startswith("--- ")''',
        '''                            and not (lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "))''',
    )

    p5_arch = replace_once(
        mgr_src,
        "    def apply_patch(self, sandbox_path: Path, patch_diff: str) -> None:",
        """    @staticmethod
    def _is_file_header(lines: list[str], idx: int) -> bool:
        return idx + 1 < len(lines) and lines[idx].startswith("--- ") and lines[idx + 1].startswith("+++ ")

    @staticmethod
    def _parse_header_path(raw: str, prefix: str) -> str:
        return raw[4:].split("\\t", 1)[0].strip().removeprefix(prefix)

    def apply_patch(self, sandbox_path: Path, patch_diff: str) -> None:""",
    )
    p5_arch = replace_once(
        p5_arch,
        '''            if line.startswith(("--- a/", "--- ")):
                # Next line should be +++ b/path
                target_rel = None
                if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                    target_rel = lines[i + 1][4:].strip()
                    target_rel = target_rel.removeprefix("b/")
                    i += 2
                else:
                    i += 1
                    continue

                if not target_rel:
                    continue''',
        '''            if self._is_file_header(lines, i):
                old_rel = self._parse_header_path(line, "a/")
                target_rel = self._parse_header_path(lines[i + 1], "b/")
                i += 2
                if target_rel == "/dev/null":
                    if old_rel and old_rel != "/dev/null":
                        validate_safe_path(sandbox_path, old_rel).unlink(missing_ok=True)
                    continue
                if not target_rel:
                    continue''',
    )
    p5_arch = replace_once(
        p5_arch,
        '''                while i < len(lines) and not (
                    lines[i].startswith("--- a/") or lines[i].startswith("--- ")
                ):''',
        "                while i < len(lines) and not self._is_file_header(lines, i):",
    )
    p5_arch = replace_once(
        p5_arch,
        '''                            and not lines[i].startswith("--- ")''',
        "                            and not self._is_file_header(lines, i)",
    )

    p5_cont = replace_once(
        mgr_src,
        '''            if line.startswith(("--- a/", "--- ")):
                # Next line should be +++ b/path
                target_rel = None
                if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                    target_rel = lines[i + 1][4:].strip()
                    target_rel = target_rel.removeprefix("b/")
                    i += 2
                else:
                    i += 1
                    continue''',
        '''            if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                old_rel = line[4:].split("\\t", 1)[0].strip().removeprefix("a/")
                target_rel = lines[i + 1][4:].split("\\t", 1)[0].strip().removeprefix("b/")
                i += 2
                if target_rel == "/dev/null":
                    if old_rel and old_rel != "/dev/null":
                        validate_safe_path(sandbox_path, old_rel).unlink(missing_ok=True)
                    continue''',
    )
    p5_cont = replace_once(
        p5_cont,
        '''                while i < len(lines) and not (
                    lines[i].startswith("--- a/") or lines[i].startswith("--- ")
                ):''',
        '''                while i < len(lines) and not (
                    lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")
                ):''',
    )
    p5_cont = replace_once(
        p5_cont,
        '''                            and not lines[i].startswith("--- ")''',
        '''                            and not (lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "))''',
    )
    specs["BUG-005"] = {
        "file": "src/bugarena/sandbox/manager.py",
        "repro": "bug_report/evidence/repro/BUG-005_repro.py",
        "cands": [
            ("cand_bug005_surgical", "surgical_minimalist", "Require paired +++ line for file headers and strip tab timestamps.", make_diff("src/bugarena/sandbox/manager.py", mgr_src, p5_surg)),
            ("cand_bug005_defensive", "defensive_guardian", "Guard file headers with paired +++, unlink /dev/null deletions safely, and strip timestamps.", make_diff("src/bugarena/sandbox/manager.py", mgr_src, p5_def)),
            ("cand_bug005_architectural", "architectural_fixer", "Extract _is_file_header and _parse_header_path helpers for clean header vs hunk boundaries.", make_diff("src/bugarena/sandbox/manager.py", mgr_src, p5_arch)),
            ("cand_bug005_contract", "contract_enforcer", "Enforce strict two-line diff file-header contract and /dev/null deletion handling.", make_diff("src/bugarena/sandbox/manager.py", mgr_src, p5_cont)),
        ],
    }

    # BUG-007: patch_parser.py CRLF + hunk counting
    pp_src = read_src("src/bugarena/tournament/patch_parser.py")
    p7_surg = replace_once(
        pp_src,
        'r"^--- (?:a/)?(?P<old_file>\\S+)\\n\\+\\+\\+ (?:b/)?(?P<new_file>\\S+)"',
        'r"^--- (?:a/)?(?P<old_file>[^\\t\\r\\n]+?)(?:\\t.*)?\\r?\\n\\+\\+\\+ (?:b/)?(?P<new_file>[^\\t\\r\\n]+?)(?:\\t.*)?$"',
    )
    p7_surg = replace_once(p7_surg, "    clean_diff = raw_diff.strip()", '    clean_diff = raw_diff.replace("\\r\\n", "\\n").strip()')
    p7_surg = replace_once(
        p7_surg,
        '''    for line in clean_diff.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue''',
        '''    in_hunk = False
    for line in clean_diff.splitlines():
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk and line.startswith(("+++", "---")):
            continue''',
    )

    p7_def = replace_once(
        pp_src,
        'r"^--- (?:a/)?(?P<old_file>\\S+)\\n\\+\\+\\+ (?:b/)?(?P<new_file>\\S+)"',
        'r"^--- (?:a/)?(?P<old_file>[^\\t\\r\\n]+?)(?:\\t.*)?\\r?\\n\\+\\+\\+ (?:b/)?(?P<new_file>[^\\t\\r\\n]+?)(?:\\t.*)?$"',
    )
    p7_def = replace_once(p7_def, "    clean_diff = raw_diff.strip()", '    clean_diff = raw_diff.replace("\\r\\n", "\\n").replace("\\r", "\\n").strip()')
    p7_def = replace_once(
        p7_def,
        '''    for line in clean_diff.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue''',
        '''    in_hunk = False
    for line in clean_diff.splitlines():
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk and line.startswith(("--- ", "+++ ", "diff --git ")):
            continue
        if line.startswith("diff --git "):
            in_hunk = False
            continue''',
    )

    p7_arch = replace_once(
        pp_src,
        'r"^--- (?:a/)?(?P<old_file>\\S+)\\n\\+\\+\\+ (?:b/)?(?P<new_file>\\S+)"',
        'r"^--- (?:a/)?(?P<old_file>[^\\t\\r\\n]+?)(?:\\t.*)?\\r?\\n\\+\\+\\+ (?:b/)?(?P<new_file>[^\\t\\r\\n]+?)(?:\\t.*)?$"',
    )
    p7_arch = replace_once(p7_arch, "    clean_diff = raw_diff.strip()", '    clean_diff = raw_diff.replace("\\r\\n", "\\n").strip()')
    p7_arch = replace_once(
        p7_arch,
        '''    for line in clean_diff.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith("+"):
            lines_added += 1
        elif line.startswith("-"):
            lines_deleted += 1''',
        '''    in_hunk = False
    diff_lines = clean_diff.splitlines()
    for idx, line in enumerate(diff_lines):
        if line.startswith("--- ") and idx + 1 < len(diff_lines) and diff_lines[idx + 1].startswith("+++ "):
            in_hunk = False
            continue
        if line.startswith("+++ ") and idx > 0 and diff_lines[idx - 1].startswith("--- "):
            continue
        if line.startswith("@@"):
            in_hunk = True
            continue
        if in_hunk and line.startswith("+"):
            lines_added += 1
        elif in_hunk and line.startswith("-"):
            lines_deleted += 1''',
    )

    p7_cont = replace_once(
        pp_src,
        'r"^--- (?:a/)?(?P<old_file>\\S+)\\n\\+\\+\\+ (?:b/)?(?P<new_file>\\S+)"',
        'r"^--- (?:a/)?(?P<old_file>[^\\t\\r\\n]+?)(?:\\t.*)?\\r?\\n\\+\\+\\+ (?:b/)?(?P<new_file>[^\\t\\r\\n]+?)(?:\\t.*)?$"',
    )
    p7_cont = replace_once(p7_cont, "    clean_diff = raw_diff.strip()", '    clean_diff = raw_diff.replace("\\r\\n", "\\n").strip()')
    p7_cont = replace_once(
        p7_cont,
        '''    for line in clean_diff.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith("+"):
            lines_added += 1
        elif line.startswith("-"):
            lines_deleted += 1''',
        '''    in_hunk = False
    for line in clean_diff.splitlines():
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("+"):
            lines_added += 1
        elif line.startswith("-"):
            lines_deleted += 1''',
    )
    specs["BUG-007"] = {
        "file": "src/bugarena/tournament/patch_parser.py",
        "repro": "bug_report/evidence/repro/BUG-007_repro.py",
        "cands": [
            ("cand_bug007_surgical", "surgical_minimalist", "Normalize CRLF, support spaced/timestamped paths, and only skip header markers outside hunks.", make_diff("src/bugarena/tournament/patch_parser.py", pp_src, p7_surg)),
            ("cand_bug007_defensive", "defensive_guardian", "Normalize CR/CRLF newlines, parse spaced/timestamped paths, and reset hunk state on git headers.", make_diff("src/bugarena/tournament/patch_parser.py", pp_src, p7_def)),
            ("cand_bug007_architectural", "architectural_fixer", "Use paired-header vs hunk state tracking for accurate churn calculation across CRLF diffs.", make_diff("src/bugarena/tournament/patch_parser.py", pp_src, p7_arch)),
            ("cand_bug007_contract", "contract_enforcer", "Enforce strict hunk-state churn counting and normalized line endings.", make_diff("src/bugarena/tournament/patch_parser.py", pp_src, p7_cont)),
        ],
    }

    # BUG-008: test_runner.py AST gate + CC delta + regression count
    tr_src = read_src("src/bugarena/evaluation/test_runner.py")
    p8_surg = replace_once(tr_src, "import sys\n", "import ast\nimport re\nimport sys\n")
    p8_surg = replace_once(p8_surg, "from bugarena.evaluation.scorer import compute_patch_score", "from bugarena.evaluation.ast_metrics import calculate_cyclomatic_delta\nfrom bugarena.evaluation.scorer import compute_patch_score")
    p8_surg = replace_once(
        p8_surg,
        "                if not patch_applied:",
        '''                if patch_applied:
                    for rel_mod in re.findall(r"^\\+\\+\\+ (?:b/)?([^\\t\\r\\n]+)", cand.diff, re.MULTILINE):
                        if rel_mod.endswith(".py") and rel_mod != "/dev/null":
                            try:
                                ast.parse((sandbox_path / rel_mod.removeprefix("b/")).read_text(encoding="utf-8"))
                            except (SyntaxError, OSError):
                                patch_applied = False
                                break

                if not patch_applied:''',
    )
    p8_surg = replace_once(
        p8_surg,
        '''                if reg_outcome.exit_code != 0 and "no tests ran" not in reg_outcome.stdout.lower():
                    # Count failed tests from output
                    regressions = 1

                # 5. Calculate complexity delta
                delta_cc = 0  # Default neutral''',
        '''                if reg_outcome.exit_code != 0 and "no tests ran" not in reg_outcome.stdout.lower():
                    fm = re.search(r"(\\d+)\\s+failed", reg_outcome.stdout)
                    regressions = int(fm.group(1)) if fm else 1
                pm = re.search(r"(\\d+)\\s+passed", reg_outcome.stdout)
                if pm or regressions:
                    total_tests = regressions + (int(pm.group(1)) if pm else 0)

                # 5. Calculate complexity delta
                delta_cc = 0
                for rel_mod in set(re.findall(r"^\\+\\+\\+ (?:b/)?([^\\t\\r\\n]+)", cand.diff, re.MULTILINE)):
                    if rel_mod.endswith(".py") and (self.base_repo_path / rel_mod).is_file() and (sandbox_path / rel_mod).is_file():
                        delta_cc += calculate_cyclomatic_delta(
                            (self.base_repo_path / rel_mod).read_text(encoding="utf-8"),
                            (sandbox_path / rel_mod).read_text(encoding="utf-8"),
                        )''',
    )

    p8_def = replace_once(tr_src, "import sys\n", "import ast\nimport re\nimport sys\n")
    p8_def = replace_once(p8_def, "from bugarena.evaluation.scorer import compute_patch_score", "from bugarena.evaluation.ast_metrics import calculate_cyclomatic_delta\nfrom bugarena.evaluation.scorer import compute_patch_score")
    p8_def = replace_once(
        p8_def,
        "                if not patch_applied:",
        '''                if patch_applied:
                    for rel_mod in re.findall(r"^\\+\\+\\+ (?:b/)?([^\\t\\r\\n]+)", cand.diff, re.MULTILINE):
                        p = sandbox_path / rel_mod.removeprefix("b/")
                        if p.suffix == ".py" and p.is_file():
                            try:
                                ast.parse(p.read_text(encoding="utf-8"))
                            except (SyntaxError, OSError):
                                patch_applied = False
                                break

                if not patch_applied:''',
    )
    p8_def = replace_once(
        p8_def,
        '''                # 4. Run regression suite (excluding the repro test itself)
                reg_outcome = run_sandboxed_command(
                    workspace=sandbox_path,
                    args=[
                        self.python_executable,
                        "-m",
                        "pytest",
                        self.regression_test_dir,
                        f"--ignore={repro_spec.test_file_path}",
                        "-q",
                    ],
                    timeout_seconds=timeout_seconds,
                    env_override={"PYTHONPATH": "."},
                )

                # Check regressions: if test command ran and had failures
                regressions = 0
                total_tests = 1
                if reg_outcome.exit_code != 0 and "no tests ran" not in reg_outcome.stdout.lower():
                    # Count failed tests from output
                    regressions = 1

                # 5. Calculate complexity delta
                delta_cc = 0  # Default neutral''',
        '''                # 4. Run regression suite (excluding the repro test itself)
                regressions = 0
                total_tests = 1
                if (sandbox_path / self.regression_test_dir).exists():
                    reg_outcome = run_sandboxed_command(
                        workspace=sandbox_path,
                        args=[
                            self.python_executable,
                            "-m",
                            "pytest",
                            self.regression_test_dir,
                            f"--ignore={repro_spec.test_file_path}",
                            "-q",
                        ],
                        timeout_seconds=timeout_seconds,
                        env_override={"PYTHONPATH": "."},
                    )
                    if reg_outcome.exit_code != 0 and "no tests ran" not in reg_outcome.stdout.lower():
                        fm = re.search(r"(\\d+)\\s+failed", reg_outcome.stdout)
                        regressions = int(fm.group(1)) if fm else 1
                    pm = re.search(r"(\\d+)\\s+passed", reg_outcome.stdout)
                    if pm or regressions:
                        total_tests = regressions + (int(pm.group(1)) if pm else 0)

                # 5. Calculate complexity delta
                delta_cc = 0
                for rel_mod in set(re.findall(r"^\\+\\+\\+ (?:b/)?([^\\t\\r\\n]+)", cand.diff, re.MULTILINE)):
                    if rel_mod.endswith(".py") and (self.base_repo_path / rel_mod).is_file() and (sandbox_path / rel_mod).is_file():
                        try:
                            delta_cc += calculate_cyclomatic_delta(
                                (self.base_repo_path / rel_mod).read_text(encoding="utf-8"),
                                (sandbox_path / rel_mod).read_text(encoding="utf-8"),
                            )
                        except SyntaxError:
                            patch_applied = False''',
    )

    p8_arch = replace_once(tr_src, "import sys\n", "import ast\nimport re\nimport sys\n")
    p8_arch = replace_once(p8_arch, "from bugarena.evaluation.scorer import compute_patch_score", "from bugarena.evaluation.ast_metrics import calculate_cyclomatic_delta\nfrom bugarena.evaluation.scorer import compute_patch_score")
    p8_arch = replace_once(
        p8_arch,
        "class PatchEvaluator:",
        '''def _patched_python_files(diff: str) -> list[str]:
    return sorted({p.removeprefix("b/") for p in re.findall(r"^\\+\\+\\+ (?:b/)?([^\\t\\r\\n]+)", diff, re.MULTILINE) if p.endswith(".py") and p != "/dev/null"})


def _parse_pytest_counts(stdout: str, exit_code: int) -> tuple[int, int]:
    if "no tests ran" in stdout.lower():
        return 0, 1
    fm = re.search(r"(\\d+)\\s+failed", stdout)
    pm = re.search(r"(\\d+)\\s+passed", stdout)
    reg = int(fm.group(1)) if fm else (1 if exit_code != 0 else 0)
    tot = reg + (int(pm.group(1)) if pm else 0)
    return reg, max(1, tot)


class PatchEvaluator:''',
    )
    p8_arch = replace_once(
        p8_arch,
        "                if not patch_applied:",
        '''                if patch_applied:
                    for rel_mod in _patched_python_files(cand.diff):
                        try:
                            ast.parse((sandbox_path / rel_mod).read_text(encoding="utf-8"))
                        except (SyntaxError, OSError):
                            patch_applied = False
                            break

                if not patch_applied:''',
    )
    p8_arch = replace_once(
        p8_arch,
        '''                # Check regressions: if test command ran and had failures
                regressions = 0
                total_tests = 1
                if reg_outcome.exit_code != 0 and "no tests ran" not in reg_outcome.stdout.lower():
                    # Count failed tests from output
                    regressions = 1

                # 5. Calculate complexity delta
                delta_cc = 0  # Default neutral''',
        '''                regressions, total_tests = _parse_pytest_counts(reg_outcome.stdout, reg_outcome.exit_code)

                # 5. Calculate complexity delta
                delta_cc = sum(
                    calculate_cyclomatic_delta(
                        (self.base_repo_path / m).read_text(encoding="utf-8") if (self.base_repo_path / m).is_file() else "",
                        (sandbox_path / m).read_text(encoding="utf-8"),
                    )
                    for m in _patched_python_files(cand.diff)
                    if (sandbox_path / m).is_file()
                )''',
    )

    p8_cont = replace_once(tr_src, "import sys\n", "import ast\nimport re\nimport sys\n")
    p8_cont = replace_once(p8_cont, "from bugarena.evaluation.scorer import compute_patch_score", "from bugarena.evaluation.ast_metrics import calculate_cyclomatic_delta\nfrom bugarena.evaluation.scorer import compute_patch_score")
    p8_cont = replace_once(
        p8_cont,
        "                if not patch_applied:",
        '''                if patch_applied:
                    for rel_mod in re.findall(r"^\\+\\+\\+ (?:b/)?([^\\t\\r\\n]+)", cand.diff, re.MULTILINE):
                        if rel_mod.endswith(".py") and (sandbox_path / rel_mod).is_file():
                            try:
                                ast.parse((sandbox_path / rel_mod).read_text(encoding="utf-8"))
                            except SyntaxError:
                                patch_applied = False
                                break

                if not patch_applied:''',
    )
    p8_cont = replace_once(
        p8_cont,
        '''                if reg_outcome.exit_code != 0 and "no tests ran" not in reg_outcome.stdout.lower():
                    # Count failed tests from output
                    regressions = 1

                # 5. Calculate complexity delta
                delta_cc = 0  # Default neutral''',
        '''                if reg_outcome.exit_code != 0 and "no tests ran" not in reg_outcome.stdout.lower():
                    fm = re.search(r"(\\d+)\\s+failed", reg_outcome.stdout)
                    pm = re.search(r"(\\d+)\\s+passed", reg_outcome.stdout)
                    regressions = int(fm.group(1)) if fm else 1
                    total_tests = regressions + (int(pm.group(1)) if pm else 0)

                # 5. Calculate complexity delta
                delta_cc = 0
                for rel_mod in set(re.findall(r"^\\+\\+\\+ (?:b/)?([^\\t\\r\\n]+)", cand.diff, re.MULTILINE)):
                    if rel_mod.endswith(".py") and (self.base_repo_path / rel_mod).is_file() and (sandbox_path / rel_mod).is_file():
                        delta_cc += calculate_cyclomatic_delta((self.base_repo_path / rel_mod).read_text(encoding="utf-8"), (sandbox_path / rel_mod).read_text(encoding="utf-8"))''',
    )
    specs["BUG-008"] = {
        "file": "src/bugarena/evaluation/test_runner.py",
        "repro": "bug_report/evidence/repro/BUG-008_repro.py",
        "cands": [
            ("cand_bug008_surgical", "surgical_minimalist", "Enforce ast.parse Syntax gate on patched .py files, calculate CC delta, and parse pytest counts.", make_diff("src/bugarena/evaluation/test_runner.py", tr_src, p8_surg)),
            ("cand_bug008_defensive", "defensive_guardian", "Guard missing regression dir, enforce AST gate with SyntaxError catch, parse test counts, and compute CC delta.", make_diff("src/bugarena/evaluation/test_runner.py", tr_src, p8_def)),
            ("cand_bug008_architectural", "architectural_fixer", "Extract _patched_python_files and _parse_pytest_counts helpers with AST gate and CC delta scoring.", make_diff("src/bugarena/evaluation/test_runner.py", tr_src, p8_arch)),
            ("cand_bug008_contract", "contract_enforcer", "Enforce Syntax/AST gate, real regression count contract, and verified complexity delta scoring.", make_diff("src/bugarena/evaluation/test_runner.py", tr_src, p8_cont)),
        ],
    }

    # BUG-012: tournament/runner.py
    run_src = read_src("src/bugarena/tournament/runner.py")
    p12_surg = replace_once(
        run_src,
        '''        self.personas = list(
            personas
            or [
                PersonaType.SURGICAL_MINIMALIST,
                PersonaType.DEFENSIVE_GUARDIAN,
                PersonaType.ARCHITECTURAL_FIXER,
            ]
        )''',
        '''        default_personas = [
            PersonaType.SURGICAL_MINIMALIST,
            PersonaType.DEFENSIVE_GUARDIAN,
            PersonaType.ARCHITECTURAL_FIXER,
            PersonaType.CONTRACT_ENFORCER,
        ]
        self.personas = list(personas if personas is not None else default_personas)''',
    )
    p12_def = replace_once(
        run_src,
        '''        self.personas = list(
            personas
            or [
                PersonaType.SURGICAL_MINIMALIST,
                PersonaType.DEFENSIVE_GUARDIAN,
                PersonaType.ARCHITECTURAL_FIXER,
            ]
        )''',
        '''        if personas is None:
            self.personas = list(PersonaType)
        else:
            seen: set[PersonaType] = set()
            self.personas = [p for p in personas if not (p in seen or seen.add(p))]''',
    )
    p12_arch = replace_once(
        run_src,
        '''        self.personas = list(
            personas
            or [
                PersonaType.SURGICAL_MINIMALIST,
                PersonaType.DEFENSIVE_GUARDIAN,
                PersonaType.ARCHITECTURAL_FIXER,
            ]
        )''',
        "        self.personas = list(PersonaType) if personas is None else list(personas)",
    )
    p12_cont = replace_once(
        run_src,
        '''        self.personas = list(
            personas
            or [
                PersonaType.SURGICAL_MINIMALIST,
                PersonaType.DEFENSIVE_GUARDIAN,
                PersonaType.ARCHITECTURAL_FIXER,
            ]
        )''',
        '''        self.personas = (
            [PersonaType.SURGICAL_MINIMALIST, PersonaType.DEFENSIVE_GUARDIAN, PersonaType.ARCHITECTURAL_FIXER, PersonaType.CONTRACT_ENFORCER]
            if personas is None
            else [PersonaType(p) for p in personas]
        )''',
    )
    specs["BUG-012"] = {
        "file": "src/bugarena/tournament/runner.py",
        "repro": "bug_report/evidence/repro/BUG-012_repro.py",
        "cands": [
            ("cand_bug012_surgical", "surgical_minimalist", "Add CONTRACT_ENFORCER to default personas and use 'is not None' check.", make_diff("src/bugarena/tournament/runner.py", run_src, p12_surg)),
            ("cand_bug012_defensive", "defensive_guardian", "Default to all PersonaType members when None and deduplicate explicit persona sequences.", make_diff("src/bugarena/tournament/runner.py", run_src, p12_def)),
            ("cand_bug012_architectural", "architectural_fixer", "Derive default roster directly from PersonaType enum while preserving empty sequences.", make_diff("src/bugarena/tournament/runner.py", run_src, p12_arch)),
            ("cand_bug012_contract", "contract_enforcer", "Enforce 4-persona default roster and PersonaType validation for caller-supplied lists.", make_diff("src/bugarena/tournament/runner.py", run_src, p12_cont)),
        ],
    }

    # BUG-014: log_parser.py
    lp_src = read_src("src/bugarena/discovery/log_parser.py")
    p14_surg = replace_once(
        lp_src,
        r"""    r'File\s+["\'](?P<file>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>\w+))?',""",
        r"""    r'File\s+["\'](?P<file>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>[^\r\n]+))?',""",
    )
    p14_surg = replace_once(
        p14_surg,
        r'    r"^(?P<type>[a-zA-Z_]\w*(?:Error|Exception|Warning|Fault|Interrupt)?):\s*(?P<msg>.*)$",',
        r'    r"^(?P<type>[a-zA-Z_]\w*(?:Error|Exception|Warning|Fault|Interrupt)):\s*(?P<msg>.*)$",',
    )
    p14_surg = replace_once(
        p14_surg,
        '''    for line in reversed(lines):
        line_clean = line.strip()
        if not line_clean:
            continue
        exc_match = EXCEPTION_PATTERN.match(line_clean)
        if exc_match or ":" in line_clean and not line_clean.startswith("File "):
            error_message = line_clean
            break''',
        '''    last_frame_idx = max((idx for idx, ln in enumerate(lines) if FRAME_PATTERN.search(ln)), default=-1)
    for line in lines[last_frame_idx + 1:]:
        line_clean = line.strip()
        if EXCEPTION_PATTERN.match(line_clean):
            error_message = line_clean
            break''',
    )
    p14_def = replace_once(
        lp_src,
        r"""    r'File\s+["\'](?P<file>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>\w+))?',""",
        r"""    r'File\s+["\'](?P<file>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func><[^>]+>|[\w.]+))?',""",
    )
    p14_def = replace_once(
        p14_def,
        r'    r"^(?P<type>[a-zA-Z_]\w*(?:Error|Exception|Warning|Fault|Interrupt)?):\s*(?P<msg>.*)$",',
        r'    r"^(?P<type>[a-zA-Z_]\w*(?:Error|Exception|Warning|Fault|Interrupt|Exit)):\s*(?P<msg>.*)$",',
    )
    p14_def = replace_once(
        p14_def,
        '''    for line in reversed(lines):
        line_clean = line.strip()
        if not line_clean:
            continue
        exc_match = EXCEPTION_PATTERN.match(line_clean)
        if exc_match or ":" in line_clean and not line_clean.startswith("File "):
            error_message = line_clean
            break''',
        '''    for line in reversed(lines):
        line_clean = line.strip()
        if line_clean and EXCEPTION_PATTERN.match(line_clean):
            error_message = line_clean
            break''',
    )
    p14_arch = replace_once(
        lp_src,
        r"""    r'File\s+["\'](?P<file>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>\w+))?',""",
        r"""    r'File\s+["\'](?P<file>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>\S+))?',""",
    )
    p14_arch = replace_once(
        p14_arch,
        r'    r"^(?P<type>[a-zA-Z_]\w*(?:Error|Exception|Warning|Fault|Interrupt)?):\s*(?P<msg>.*)$",',
        r'    r"^(?P<type>[a-zA-Z_]\w*(?:Error|Exception|Warning|Fault|Interrupt|Exit)):\s*(?P<msg>.*)$",',
    )
    p14_arch = replace_once(
        p14_arch,
        '''    error_message = "UnknownError"
    for line in reversed(lines):
        line_clean = line.strip()
        if not line_clean:
            continue
        exc_match = EXCEPTION_PATTERN.match(line_clean)
        if exc_match or ":" in line_clean and not line_clean.startswith("File "):
            error_message = line_clean
            break''',
        '''    error_message = _extract_exception_line(lines)''',
    )
    p14_arch = replace_once(
        p14_arch,
        "def parse_python_traceback(error_log: str) -> list[FaultTrace]:",
        '''def _extract_exception_line(lines: list[str]) -> str:
    for line in reversed(lines):
        clean = line.strip()
        if clean and EXCEPTION_PATTERN.match(clean):
            return clean
    return "UnknownError"


def parse_python_traceback(error_log: str) -> list[FaultTrace]:''',
    )
    p14_cont = replace_once(
        lp_src,
        r"""    r'File\s+["\'](?P<file>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>\w+))?',""",
        r"""    r'File\s+["\'](?P<file>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func><\w+>|[\w.]+))?',""",
    )
    p14_cont = replace_once(
        p14_cont,
        r'    r"^(?P<type>[a-zA-Z_]\w*(?:Error|Exception|Warning|Fault|Interrupt)?):\s*(?P<msg>.*)$",',
        r'    r"^(?P<type>[a-zA-Z_]\w*(?:Error|Exception|Warning|Fault|Interrupt|Exit)):\s*(?P<msg>.*)$",',
    )
    p14_cont = replace_once(
        p14_cont,
        '''    for line in reversed(lines):
        line_clean = line.strip()
        if not line_clean:
            continue
        exc_match = EXCEPTION_PATTERN.match(line_clean)
        if exc_match or ":" in line_clean and not line_clean.startswith("File "):
            error_message = line_clean
            break''',
        '''    for line in reversed(lines):
        line_clean = line.strip()
        if line_clean and EXCEPTION_PATTERN.match(line_clean):
            error_message = line_clean
            break''',
    )
    specs["BUG-014"] = {
        "file": "src/bugarena/discovery/log_parser.py",
        "repro": "bug_report/evidence/repro/BUG-014_repro.py",
        "cands": [
            ("cand_bug014_surgical", "surgical_minimalist", "Capture angle-bracket/dotted function scopes and match exception line after last frame.", make_diff("src/bugarena/discovery/log_parser.py", lp_src, p14_surg)),
            ("cand_bug014_defensive", "defensive_guardian", "Require explicit exception class suffix and support <lambda>/<listcomp> scopes.", make_diff("src/bugarena/discovery/log_parser.py", lp_src, p14_def)),
            ("cand_bug014_architectural", "architectural_fixer", "Extract _extract_exception_line helper with strict exception class regex and full scope capture.", make_diff("src/bugarena/discovery/log_parser.py", lp_src, p14_arch)),
            ("cand_bug014_contract", "contract_enforcer", "Enforce strict Python scope identifier/angle-bracket and ExceptionType regex contracts.", make_diff("src/bugarena/discovery/log_parser.py", lp_src, p14_cont)),
        ],
    }

    # BUG-015: ast_analyzer.py empty file inverted line_range
    aa_src = read_src("src/bugarena/discovery/ast_analyzer.py")
    p15_surg = replace_once(
        aa_src,
        '''    start = max(1, min(target_line - 5, len(lines)))
    end = min(len(lines), max(1, target_line + 5))''',
        '''    if not lines:
        return ASTSliceInfo(function_name="<module>", class_name=None, line_range=(1, 1), code_snippet="", docstring=None)
    start = max(1, min(target_line - 5, len(lines)))
    end = min(len(lines), max(1, target_line + 5))''',
    )
    p15_def = replace_once(
        aa_src,
        '''    start = max(1, min(target_line - 5, len(lines)))
    end = min(len(lines), max(1, target_line + 5))''',
        '''    if not lines:
        return ASTSliceInfo(function_name="<module>", class_name=None, line_range=(0, 0), code_snippet="", docstring=None)
    clamped = max(1, min(target_line, len(lines)))
    start = max(1, clamped - 5)
    end = min(len(lines), clamped + 5)''',
    )
    p15_arch = replace_once(
        aa_src,
        '''    # If line is outside functions (e.g. top-level module code)
    start = max(1, min(target_line - 5, len(lines)))
    end = min(len(lines), max(1, target_line + 5))
    snippet = "\\n".join(lines[start - 1 : end]) if lines else ""''',
        '''    # If line is outside functions (e.g. top-level module code)
    if not lines:
        start, end = 0, 0
        snippet = ""
    else:
        clamped = max(1, min(target_line, len(lines)))
        start = max(1, clamped - 5)
        end = min(len(lines), clamped + 5)
        snippet = "\\n".join(lines[start - 1 : end])''',
    )
    p15_cont = replace_once(
        aa_src,
        '''    start = max(1, min(target_line - 5, len(lines)))
    end = min(len(lines), max(1, target_line + 5))''',
        '''    if not lines:
        return ASTSliceInfo(function_name="<module>", class_name=None, line_range=(1, 1), code_snippet="", docstring=None)
    start = max(1, min(target_line - 5, len(lines)))
    end = max(start, min(len(lines), max(1, target_line + 5)))''',
    )
    specs["BUG-015"] = {
        "file": "src/bugarena/discovery/ast_analyzer.py",
        "repro": "bug_report/evidence/repro/BUG-015_repro.py",
        "cands": [
            ("cand_bug015_surgical", "surgical_minimalist", "Return valid (1, 1) line_range early when file has no lines.", make_diff("src/bugarena/discovery/ast_analyzer.py", aa_src, p15_surg)),
            ("cand_bug015_defensive", "defensive_guardian", "Return (0, 0) for empty files and clamp target_line to valid file bounds.", make_diff("src/bugarena/discovery/ast_analyzer.py", aa_src, p15_def)),
            ("cand_bug015_architectural", "architectural_fixer", "Separate empty-file boundary handling from clamped module context slicing.", make_diff("src/bugarena/discovery/ast_analyzer.py", aa_src, p15_arch)),
            ("cand_bug015_contract", "contract_enforcer", "Enforce invariant start <= end in line_range across empty and non-empty files.", make_diff("src/bugarena/discovery/ast_analyzer.py", aa_src, p15_cont)),
        ],
    }

    # BUG-016, BUG-017, BUG-018: server.py
    srv_src = read_src("src/bugarena/server.py")
    # BUG-016
    p16_surg = replace_once(
        srv_src,
        '''    # Save to disk as an .md file
    out_path = output_file
    if not out_path:
        out_path = str(Path(tournament.repo_path) / "reports" / f"bug_report_{tournament.tournament_id}.md")

    saved_path = save_markdown_report(report_md, out_path)

    fix_report = FixReport(
        tournament_id=tournament.tournament_id,
        champion_candidate_id=tournament.champion_candidate_id,
        summary_markdown=report_md,
        git_patch_diff=champion_patch or "",
        report_file_path=str(saved_path),
    )''',
        '''    import json as _json
    champ_obj = next((c for c in tournament.candidates if c.candidate_id == tournament.champion_candidate_id), None)
    champ_eval = next((e for e in tournament.evaluations if e.candidate_id == tournament.champion_candidate_id), None)
    out_path = output_file or str(Path(tournament.repo_path) / "reports" / f"bug_report_{tournament.tournament_id}.md")
    if format == "json":
        payload = {"tournament_id": tournament.tournament_id, "champion_candidate_id": tournament.champion_candidate_id, "evaluations": [e.model_dump() for e in tournament.evaluations], "champion_diff": champion_patch}
        saved_path = save_markdown_report(_json.dumps(payload, indent=2), out_path)
    elif format == "diff":
        saved_path = save_markdown_report(champion_patch or "", out_path)
    else:
        saved_path = save_markdown_report(report_md, out_path)

    fix_report = FixReport(
        tournament_id=tournament.tournament_id,
        champion_patch=champ_obj,
        champion_eval=champ_eval,
        summary_markdown=report_md,
        git_patch_diff=champion_patch or "",
        report_file_path=str(saved_path),
    )''',
    )
    p16_def = replace_once(srv_src, "import threading\n", "import json\nimport threading\n")
    p16_def = replace_once(
        p16_def,
        '''    # Save to disk as an .md file
    out_path = output_file
    if not out_path:
        out_path = str(Path(tournament.repo_path) / "reports" / f"bug_report_{tournament.tournament_id}.md")

    saved_path = save_markdown_report(report_md, out_path)

    fix_report = FixReport(
        tournament_id=tournament.tournament_id,
        champion_candidate_id=tournament.champion_candidate_id,
        summary_markdown=report_md,
        git_patch_diff=champion_patch or "",
        report_file_path=str(saved_path),
    )''',
        '''    champ_obj = next((c for c in tournament.candidates if c.candidate_id == tournament.champion_candidate_id), None) if tournament.champion_candidate_id else None
    champ_eval = next((e for e in tournament.evaluations if e.candidate_id == tournament.champion_candidate_id), None) if tournament.champion_candidate_id else None
    ext = {"json": "json", "diff": "patch"}.get(format, "md")
    out_path = output_file or str(Path(tournament.repo_path) / "reports" / f"bug_report_{tournament.tournament_id}.{ext}")
    if format == "json":
        disk_text = json.dumps({"tournament_id": tournament.tournament_id, "champion_candidate_id": tournament.champion_candidate_id, "evaluations": [e.model_dump() for e in tournament.evaluations], "champion_diff": champion_patch}, indent=2)
    elif format == "diff":
        disk_text = champion_patch or ""
    else:
        disk_text = report_md
    saved_path = save_markdown_report(disk_text, out_path)

    fix_report = FixReport(
        tournament_id=tournament.tournament_id,
        champion_patch=champ_obj,
        champion_eval=champ_eval,
        summary_markdown=report_md,
        git_patch_diff=champion_patch or "",
        report_file_path=str(saved_path),
    )''',
    )
    p16_arch = replace_once(srv_src, "import threading\n", "import json\nimport threading\n")
    p16_arch = replace_once(
        p16_arch,
        '''    # Save to disk as an .md file
    out_path = output_file
    if not out_path:
        out_path = str(Path(tournament.repo_path) / "reports" / f"bug_report_{tournament.tournament_id}.md")

    saved_path = save_markdown_report(report_md, out_path)

    fix_report = FixReport(
        tournament_id=tournament.tournament_id,
        champion_candidate_id=tournament.champion_candidate_id,
        summary_markdown=report_md,
        git_patch_diff=champion_patch or "",
        report_file_path=str(saved_path),
    )''',
        '''    champ_obj = next((c for c in tournament.candidates if c.candidate_id == tournament.champion_candidate_id), None)
    champ_eval = next((e for e in tournament.evaluations if e.candidate_id == tournament.champion_candidate_id), None)
    content_by_fmt = {
        "json": json.dumps({"tournament_id": tournament.tournament_id, "champion_candidate_id": tournament.champion_candidate_id, "evaluations": [e.model_dump() for e in tournament.evaluations], "champion_diff": champion_patch}, indent=2),
        "diff": champion_patch or "",
    }
    out_path = output_file or str(Path(tournament.repo_path) / "reports" / f"bug_report_{tournament.tournament_id}.{'json' if format == 'json' else ('diff' if format == 'diff' else 'md')}")
    saved_path = save_markdown_report(content_by_fmt.get(format, report_md), out_path)

    fix_report = FixReport(
        tournament_id=tournament.tournament_id,
        champion_patch=champ_obj,
        champion_eval=champ_eval,
        summary_markdown=report_md,
        git_patch_diff=champion_patch or "",
        report_file_path=str(saved_path),
    )''',
    )
    p16_cont = replace_once(srv_src, "import threading\n", "import json\nimport threading\n")
    p16_cont = replace_once(
        p16_cont,
        '''    # Save to disk as an .md file
    out_path = output_file
    if not out_path:
        out_path = str(Path(tournament.repo_path) / "reports" / f"bug_report_{tournament.tournament_id}.md")

    saved_path = save_markdown_report(report_md, out_path)

    fix_report = FixReport(
        tournament_id=tournament.tournament_id,
        champion_candidate_id=tournament.champion_candidate_id,
        summary_markdown=report_md,
        git_patch_diff=champion_patch or "",
        report_file_path=str(saved_path),
    )''',
        '''    champ_obj = next((c for c in tournament.candidates if c.candidate_id == tournament.champion_candidate_id), None)
    champ_eval = next((e for e in tournament.evaluations if e.candidate_id == tournament.champion_candidate_id), None)
    out_path = output_file or str(Path(tournament.repo_path) / "reports" / f"bug_report_{tournament.tournament_id}.md")
    serialized = json.dumps({"tournament_id": tournament.tournament_id, "champion_candidate_id": tournament.champion_candidate_id, "evaluations": [e.model_dump() for e in tournament.evaluations], "champion_diff": champion_patch}) if format == "json" else (champion_patch or "" if format == "diff" else report_md)
    saved_path = save_markdown_report(serialized, out_path)

    fix_report = FixReport(
        tournament_id=tournament.tournament_id,
        champion_patch=champ_obj,
        champion_eval=champ_eval,
        summary_markdown=report_md,
        git_patch_diff=champion_patch or "",
        report_file_path=str(saved_path),
    )''',
    )
    specs["BUG-016"] = {
        "file": "src/bugarena/server.py",
        "repro": "bug_report/evidence/repro/BUG-016_repro.py",
        "cands": [
            ("cand_bug016_surgical", "surgical_minimalist", "Populate champion_patch/champion_eval on FixReport and serialize disk output per format.", make_diff("src/bugarena/server.py", srv_src, p16_surg)),
            ("cand_bug016_defensive", "defensive_guardian", "Guard optional champion lookup, use format-matched extension, and write format-accurate output.", make_diff("src/bugarena/server.py", srv_src, p16_def)),
            ("cand_bug016_architectural", "architectural_fixer", "Map format serialization cleanly and hydrate FixReport with full champion patch/evaluation objects.", make_diff("src/bugarena/server.py", srv_src, p16_arch)),
            ("cand_bug016_contract", "contract_enforcer", "Enforce FixReport schema fields and format-consistent file output contract.", make_diff("src/bugarena/server.py", srv_src, p16_cont)),
        ],
    }

    # BUG-017: server.py generate_bug_report repro linking
    p17_surg = replace_once(
        srv_src,
        "def _store_repro(test_rel_path: str, spec: ReproTestSpec) -> None:\n    with _REGISTRY_LOCK:\n        _REPRO_REGISTRY[test_rel_path] = spec",
        "def _store_repro(test_rel_path: str, spec: ReproTestSpec, repo_path: str = \"\") -> None:\n    with _REGISTRY_LOCK:\n        _REPRO_REGISTRY[test_rel_path] = spec\n        if repo_path:\n            _REPRO_REPO_MAP[test_rel_path] = str(Path(repo_path).resolve())",
    )
    p17_surg = replace_once(
        p17_surg,
        "_REPRO_REGISTRY: OrderedDict[str, ReproTestSpec] = OrderedDict()",
        "_REPRO_REGISTRY: OrderedDict[str, ReproTestSpec] = OrderedDict()\n_REPRO_REPO_MAP: dict[str, str] = {}",
    )
    p17_surg = replace_once(
        p17_surg,
        "        _store_repro(test_rel_path, spec)",
        "        _store_repro(test_rel_path, spec, repo_path=repo_path)",
    )
    p17_surg = replace_once(
        p17_surg,
        '''    with _REGISTRY_LOCK:
        for r in _REPRO_REGISTRY.values():
            if r.test_file_path.startswith(repo_path) or repo_path in r.test_file_path:
                repro_spec = r
                break''',
        '''    resolved_repo = str(Path(repo_path).resolve())
    with _REGISTRY_LOCK:
        for key, r in reversed(list(_REPRO_REGISTRY.items())):
            if _REPRO_REPO_MAP.get(key) == resolved_repo or r.test_file_path.startswith(repo_path):
                repro_spec = r
                break''',
    )

    p17_def = replace_once(
        srv_src,
        "_REPRO_REGISTRY: OrderedDict[str, ReproTestSpec] = OrderedDict()",
        "_REPRO_REGISTRY: OrderedDict[str, ReproTestSpec] = OrderedDict()\n_REPRO_REPO_MAP: dict[str, str] = {}",
    )
    p17_def = replace_once(
        p17_def,
        '''def _store_repro(test_rel_path: str, spec: ReproTestSpec) -> None:
    with _REGISTRY_LOCK:
        _REPRO_REGISTRY[test_rel_path] = spec
        if len(_REPRO_REGISTRY) > MAX_REGISTRY_SIZE:
            _REPRO_REGISTRY.popitem(last=False)''',
        '''def _store_repro(test_rel_path: str, spec: ReproTestSpec, repo_path: str = "") -> None:
    with _REGISTRY_LOCK:
        _REPRO_REGISTRY[test_rel_path] = spec
        if repo_path:
            _REPRO_REPO_MAP[test_rel_path] = str(Path(repo_path).resolve())
        if len(_REPRO_REGISTRY) > MAX_REGISTRY_SIZE:
            evicted_k, _ = _REPRO_REGISTRY.popitem(last=False)
            _REPRO_REPO_MAP.pop(evicted_k, None)''',
    )
    p17_def = replace_once(p17_def, "        _store_repro(test_rel_path, spec)", "        _store_repro(test_rel_path, spec, repo_path=repo_path)")
    p17_def = replace_once(
        p17_def,
        '''    with _REGISTRY_LOCK:
        for r in _REPRO_REGISTRY.values():
            if r.test_file_path.startswith(repo_path) or repo_path in r.test_file_path:
                repro_spec = r
                break''',
        '''    resolved_repo = str(Path(repo_path).resolve())
    with _REGISTRY_LOCK:
        for key, r in reversed(list(_REPRO_REGISTRY.items())):
            if _REPRO_REPO_MAP.get(key) == resolved_repo or (Path(repo_path) / r.test_file_path).exists():
                repro_spec = r
                break''',
    )

    p17_arch = replace_once(
        srv_src,
        "_REPRO_REGISTRY: OrderedDict[str, ReproTestSpec] = OrderedDict()",
        "_REPRO_REGISTRY: OrderedDict[str, ReproTestSpec] = OrderedDict()\n_REPRO_REPO_INDEX: dict[str, list[str]] = {}",
    )
    p17_arch = replace_once(
        p17_arch,
        "def _store_repro(test_rel_path: str, spec: ReproTestSpec) -> None:\n    with _REGISTRY_LOCK:\n        _REPRO_REGISTRY[test_rel_path] = spec",
        "def _store_repro(test_rel_path: str, spec: ReproTestSpec, repo_path: str | None = None) -> None:\n    with _REGISTRY_LOCK:\n        _REPRO_REGISTRY[test_rel_path] = spec\n        if repo_path:\n            _REPRO_REPO_INDEX.setdefault(str(Path(repo_path).resolve()), []).append(test_rel_path)",
    )
    p17_arch = replace_once(p17_arch, "        _store_repro(test_rel_path, spec)", "        _store_repro(test_rel_path, spec, repo_path=repo_path)")
    p17_arch = replace_once(
        p17_arch,
        '''    with _REGISTRY_LOCK:
        for r in _REPRO_REGISTRY.values():
            if r.test_file_path.startswith(repo_path) or repo_path in r.test_file_path:
                repro_spec = r
                break''',
        '''    resolved_repo = str(Path(repo_path).resolve())
    with _REGISTRY_LOCK:
        for key in reversed(_REPRO_REPO_INDEX.get(resolved_repo, [])):
            if key in _REPRO_REGISTRY:
                repro_spec = _REPRO_REGISTRY[key]
                break''',
    )

    p17_cont = replace_once(
        srv_src,
        "_REPRO_REGISTRY: OrderedDict[str, ReproTestSpec] = OrderedDict()",
        "_REPRO_REGISTRY: OrderedDict[str, ReproTestSpec] = OrderedDict()\n_REPRO_REPO_MAP: dict[str, str] = {}",
    )
    p17_cont = replace_once(
        p17_cont,
        "def _store_repro(test_rel_path: str, spec: ReproTestSpec) -> None:\n    with _REGISTRY_LOCK:\n        _REPRO_REGISTRY[test_rel_path] = spec",
        "def _store_repro(test_rel_path: str, spec: ReproTestSpec, repo_path: str = \"\") -> None:\n    with _REGISTRY_LOCK:\n        _REPRO_REGISTRY[test_rel_path] = spec\n        if repo_path:\n            _REPRO_REPO_MAP[test_rel_path] = Path(repo_path).resolve().as_posix()",
    )
    p17_cont = replace_once(p17_cont, "        _store_repro(test_rel_path, spec)", "        _store_repro(test_rel_path, spec, repo_path=repo_path)")
    p17_cont = replace_once(
        p17_cont,
        '''    with _REGISTRY_LOCK:
        for r in _REPRO_REGISTRY.values():
            if r.test_file_path.startswith(repo_path) or repo_path in r.test_file_path:
                repro_spec = r
                break''',
        '''    repo_posix = Path(repo_path).resolve().as_posix()
    with _REGISTRY_LOCK:
        for key, r in reversed(list(_REPRO_REGISTRY.items())):
            if _REPRO_REPO_MAP.get(key) == repo_posix:
                repro_spec = r
                break''',
    )
    specs["BUG-017"] = {
        "file": "src/bugarena/server.py",
        "repro": "bug_report/evidence/repro/BUG-017_repro.py",
        "cands": [
            ("cand_bug017_surgical", "surgical_minimalist", "Track resolved repo_path per stored repro spec and match against resolved repo_path.", make_diff("src/bugarena/server.py", srv_src, p17_surg)),
            ("cand_bug017_defensive", "defensive_guardian", "Track repo_path mapping with bounded eviction cleanup and fallback filesystem check.", make_diff("src/bugarena/server.py", srv_src, p17_def)),
            ("cand_bug017_architectural", "architectural_fixer", "Index repro test paths by resolved repository path for O(1) lookup.", make_diff("src/bugarena/server.py", srv_src, p17_arch)),
            ("cand_bug017_contract", "contract_enforcer", "Enforce canonical POSIX resolved repo_path association in repro registry.", make_diff("src/bugarena/server.py", srv_src, p17_cont)),
        ],
    }

    # BUG-018: server.py failure_output + evaluate_patches lock & repro_spec
    p18_surg = replace_once(
        srv_src,
        '            "failure_output": spec.initial_outcome.stderr if spec.initial_outcome else "",',
        '            "failure_output": ((spec.initial_outcome.stdout + "\\n" + spec.initial_outcome.stderr).strip() if spec.initial_outcome else ""),',
    )
    p18_surg = replace_once(
        p18_surg,
        '    tournament = _TOURNAMENT_REGISTRY.get(tournament_id)',
        '    with _REGISTRY_LOCK:\n        tournament = _TOURNAMENT_REGISTRY.get(tournament_id)',
    )
    p18_surg = replace_once(
        p18_surg,
        '        repro_spec=tournament.repro_spec or repro_spec,',
        '        repro_spec=repro_spec,',
    )

    p18_def = replace_once(
        srv_src,
        '            "failure_output": spec.initial_outcome.stderr if spec.initial_outcome else "",',
        '            "failure_output": "\\n".join(p for p in (spec.initial_outcome.stdout.strip(), spec.initial_outcome.stderr.strip()) if p) if spec.initial_outcome else "",',
    )
    p18_def = replace_once(
        p18_def,
        '    tournament = _TOURNAMENT_REGISTRY.get(tournament_id)',
        '    with _REGISTRY_LOCK:\n        tournament = _TOURNAMENT_REGISTRY.get(tournament_id)',
    )
    p18_def = replace_once(
        p18_def,
        '        repro_spec=tournament.repro_spec or repro_spec,',
        '        repro_spec=repro_spec if repro_code else (tournament.repro_spec or repro_spec),',
    )

    p18_arch = replace_once(
        srv_src,
        "def bug_reproduce(",
        '''def _combine_outcome_output(outcome: Any) -> str:
    if not outcome:
        return ""
    return "\\n".join(part for part in (outcome.stdout.strip(), outcome.stderr.strip()) if part)


def bug_reproduce(''',
    )
    p18_arch = replace_once(
        p18_arch,
        '            "failure_output": spec.initial_outcome.stderr if spec.initial_outcome else "",',
        '            "failure_output": _combine_outcome_output(spec.initial_outcome),',
    )
    p18_arch = replace_once(
        p18_arch,
        '    tournament = _TOURNAMENT_REGISTRY.get(tournament_id)',
        '    with _REGISTRY_LOCK:\n        tournament = _TOURNAMENT_REGISTRY.get(tournament_id)',
    )
    p18_arch = replace_once(
        p18_arch,
        '        repro_spec=tournament.repro_spec or repro_spec,',
        '        repro_spec=repro_spec,',
    )

    p18_cont = replace_once(
        srv_src,
        '            "failure_output": spec.initial_outcome.stderr if spec.initial_outcome else "",',
        '            "failure_output": (f"{spec.initial_outcome.stdout}\\n{spec.initial_outcome.stderr}".strip() if spec.initial_outcome else ""),',
    )
    p18_cont = replace_once(
        p18_cont,
        '    tournament = _TOURNAMENT_REGISTRY.get(tournament_id)',
        '    with _REGISTRY_LOCK:\n        tournament = _TOURNAMENT_REGISTRY.get(tournament_id)',
    )
    p18_cont = replace_once(
        p18_cont,
        '        repro_spec=tournament.repro_spec or repro_spec,',
        '        repro_spec=repro_spec,',
    )
    specs["BUG-018"] = {
        "file": "src/bugarena/server.py",
        "repro": "bug_report/evidence/repro/BUG-018_repro.py",
        "cands": [
            ("cand_bug018_surgical", "surgical_minimalist", "Combine stdout+stderr in failure_output, lock tournament lookup, and store active repro_spec.", make_diff("src/bugarena/server.py", srv_src, p18_surg)),
            ("cand_bug018_defensive", "defensive_guardian", "Safely join non-empty stdout/stderr, synchronize registry read, and prefer supplied repro_code.", make_diff("src/bugarena/server.py", srv_src, p18_def)),
            ("cand_bug018_architectural", "architectural_fixer", "Extract _combine_outcome_output helper, lock registry read, and sync evaluated repro_spec.", make_diff("src/bugarena/server.py", srv_src, p18_arch)),
            ("cand_bug018_contract", "contract_enforcer", "Enforce full stdout+stderr diagnostic contract and thread-safe registry access.", make_diff("src/bugarena/server.py", srv_src, p18_cont)),
        ],
    }

    # BUG-019: security.py Windows [WORKSPACE] scrubbing + validate_safe_path '.'
    sec_src = read_src("src/bugarena/sandbox/security.py")
    p19_surg = replace_once(
        sec_src,
        '''    # Redact absolute paths exposing host user or environment
    scrubbed = re.sub(r"[a-zA-Z]:\\\\[Uu]sers\\\\[^\\/\\s\\\\]+", "[REDACTED_PATH]", scrubbed)
    scrubbed = re.sub(r"/(?:home|Users)/[^/\\s]+", "[REDACTED_PATH]", scrubbed)
    if base_dir:
        scrubbed = scrubbed.replace(str(base_dir), "[WORKSPACE]")''',
        '''    if base_dir:
        scrubbed = scrubbed.replace(str(base_dir), "[WORKSPACE]")
    # Redact absolute paths exposing host user or environment
    scrubbed = re.sub(r"[a-zA-Z]:\\\\[Uu]sers\\\\[^\\/\\s\\\\]+", "[REDACTED_PATH]", scrubbed)
    scrubbed = re.sub(r"/(?:home|Users)/[^/\\s]+", "[REDACTED_PATH]", scrubbed)''',
    )
    p19_def = replace_once(
        sec_src,
        '''    try:
        candidate.relative_to(base_resolved)
    except ValueError as e:
        raise SecurityViolationError(
            f"Path traversal detected: '{target_path}' escapes base directory '{base_resolved}'"
        ) from e''',
        '''    try:
        rel = candidate.relative_to(base_resolved)
    except ValueError as e:
        raise SecurityViolationError(
            f"Path traversal detected: '{target_path}' escapes base directory '{base_resolved}'"
        ) from e
    if str(rel) == ".":
        raise SecurityViolationError(f"Target path '{target_path}' resolves to workspace root directory.")''',
    )
    p19_def = replace_once(
        p19_def,
        '''    # Redact absolute paths exposing host user or environment
    scrubbed = re.sub(r"[a-zA-Z]:\\\\[Uu]sers\\\\[^\\/\\s\\\\]+", "[REDACTED_PATH]", scrubbed)
    scrubbed = re.sub(r"/(?:home|Users)/[^/\\s]+", "[REDACTED_PATH]", scrubbed)
    if base_dir:
        scrubbed = scrubbed.replace(str(base_dir), "[WORKSPACE]")''',
        '''    if base_dir:
        base_str = str(base_dir)
        scrubbed = scrubbed.replace(base_str, "[WORKSPACE]").replace(base_str.replace("\\\\", "/"), "[WORKSPACE]")
    # Redact absolute paths exposing host user or environment
    scrubbed = re.sub(r"[a-zA-Z]:\\\\[Uu]sers\\\\[^\\/\\s\\\\]+", "[REDACTED_PATH]", scrubbed)
    scrubbed = re.sub(r"/(?:home|Users)/[^/\\s]+", "[REDACTED_PATH]", scrubbed)''',
    )
    p19_arch = replace_once(
        sec_src,
        '''    # Redact absolute paths exposing host user or environment
    scrubbed = re.sub(r"[a-zA-Z]:\\\\[Uu]sers\\\\[^\\/\\s\\\\]+", "[REDACTED_PATH]", scrubbed)
    scrubbed = re.sub(r"/(?:home|Users)/[^/\\s]+", "[REDACTED_PATH]", scrubbed)
    if base_dir:
        scrubbed = scrubbed.replace(str(base_dir), "[WORKSPACE]")''',
        '''    if base_dir:
        for variant in {str(base_dir), str(Path(base_dir).resolve()), str(base_dir).replace("\\\\", "/")}:
            if variant:
                scrubbed = scrubbed.replace(variant, "[WORKSPACE]")
    # Redact absolute paths exposing host user or environment
    scrubbed = re.sub(r"[a-zA-Z]:\\\\[Uu]sers\\\\[^\\/\\s\\\\]+", "[REDACTED_PATH]", scrubbed)
    scrubbed = re.sub(r"/(?:home|Users)/[^/\\s]+", "[REDACTED_PATH]", scrubbed)''',
    )
    p19_cont = replace_once(
        sec_src,
        '''    # Redact absolute paths exposing host user or environment
    scrubbed = re.sub(r"[a-zA-Z]:\\\\[Uu]sers\\\\[^\\/\\s\\\\]+", "[REDACTED_PATH]", scrubbed)
    scrubbed = re.sub(r"/(?:home|Users)/[^/\\s]+", "[REDACTED_PATH]", scrubbed)
    if base_dir:
        scrubbed = scrubbed.replace(str(base_dir), "[WORKSPACE]")''',
        '''    if base_dir:
        scrubbed = scrubbed.replace(str(base_dir), "[WORKSPACE]")
    # Redact absolute paths exposing host user or environment
    scrubbed = re.sub(r"[a-zA-Z]:\\\\[Uu]sers\\\\[^\\/\\s\\\\]+", "[REDACTED_PATH]", scrubbed)
    scrubbed = re.sub(r"/(?:home|Users)/[^/\\s]+", "[REDACTED_PATH]", scrubbed)''',
    )
    specs["BUG-019"] = {
        "file": "src/bugarena/sandbox/security.py",
        "repro": "bug_report/evidence/repro/BUG-019_repro.py",
        "cands": [
            ("cand_bug019_surgical", "surgical_minimalist", "Replace base_dir with [WORKSPACE] before applying generic user-directory redaction regex.", make_diff("src/bugarena/sandbox/security.py", sec_src, p19_surg)),
            ("cand_bug019_defensive", "defensive_guardian", "Replace base_dir variants before user-path redaction and block workspace root '.' targets.", make_diff("src/bugarena/sandbox/security.py", sec_src, p19_def)),
            ("cand_bug019_architectural", "architectural_fixer", "Normalize and scrub all base_dir path variants prior to generic home/user redaction.", make_diff("src/bugarena/sandbox/security.py", sec_src, p19_arch)),
            ("cand_bug019_contract", "contract_enforcer", "Enforce workspace-first redaction ordering so specific base_dir always maps to [WORKSPACE].", make_diff("src/bugarena/sandbox/security.py", sec_src, p19_cont)),
        ],
    }

    # BUG-020: markdown_formatter.py
    mf_src = read_src("src/bugarena/reporting/markdown_formatter.py")
    p20_surg = replace_once(
        mf_src,
        '                f"| `{s.file_path}` | `{s.function_name}` | {line_str} | `{s.bug_type}` | {conf_pct} | {s.reasoning} |"',
        '                f"| `{s.file_path}` | `{s.function_name}` | {line_str} | `{s.bug_type}` | {conf_pct} | {s.reasoning.replace(\'|\', \'\\\\|\').replace(chr(10), \' \')} |"',
    )
    p20_surg = replace_once(
        p20_surg,
        '        lines.append(\n            f"| {idx} | `{ev.candidate_id}` | {persona_str} | {repro_str} | {ev.regressions_count} | {ev.diff_churn} | {ev.cyclomatic_delta} | **{ev.score:.1f}** | `{status_str}` |"\n        )',
        '        reason_note = f" ({ev.disqualification_reason})" if ev.disqualified and ev.disqualification_reason else ""\n        lines.append(\n            f"| {idx} | `{ev.candidate_id}` | {persona_str} | {repro_str} | {ev.regressions_count} | {ev.diff_churn} | {ev.cyclomatic_delta} | **{ev.score:.1f}** | `{status_str}`{reason_note} |"\n        )',
    )
    p20_def = replace_once(
        mf_src,
        "def format_bug_diagnostic_markdown(",
        '''def _md_cell(val: str) -> str:
    return (val or "").replace("|", "\\\\|").replace("\\r", " ").replace("\\n", " ")


def format_bug_diagnostic_markdown(''',
    )
    p20_def = replace_once(
        p20_def,
        '                f"| `{s.file_path}` | `{s.function_name}` | {line_str} | `{s.bug_type}` | {conf_pct} | {s.reasoning} |"',
        '                f"| `{_md_cell(s.file_path)}` | `{_md_cell(s.function_name)}` | {line_str} | `{_md_cell(s.bug_type)}` | {conf_pct} | {_md_cell(s.reasoning)} |"',
    )
    p20_def = replace_once(
        p20_def,
        '    lines.append("")\n\n    # Section 4: Champion Section',
        '''    for ev in sorted_evals:
        if ev.disqualified and ev.disqualification_reason:
            lines.append(f"- Disqualified `{ev.candidate_id}`: {_md_cell(ev.disqualification_reason)}")
    lines.append("")

    # Section 4: Champion Section''',
    )
    p20_arch = replace_once(
        mf_src,
        "def format_bug_diagnostic_markdown(",
        '''def _escape_md_cell(text: str) -> str:
    return text.replace("|", "\\\\|").replace("\\n", " ").strip()


def format_bug_diagnostic_markdown(''',
    )
    p20_arch = replace_once(
        p20_arch,
        '                f"| `{s.file_path}` | `{s.function_name}` | {line_str} | `{s.bug_type}` | {conf_pct} | {s.reasoning} |"',
        '                f"| `{_escape_md_cell(s.file_path)}` | `{_escape_md_cell(s.function_name)}` | {line_str} | `{_escape_md_cell(s.bug_type)}` | {conf_pct} | {_escape_md_cell(s.reasoning)} |"',
    )
    p20_arch = replace_once(
        p20_arch,
        '        lines.append(\n            f"| {idx} | `{ev.candidate_id}` | {persona_str} | {repro_str} | {ev.regressions_count} | {ev.diff_churn} | {ev.cyclomatic_delta} | **{ev.score:.1f}** | `{status_str}` |"\n        )',
        '        status_cell = f"`{status_str}`: {_escape_md_cell(ev.disqualification_reason)}" if ev.disqualified and ev.disqualification_reason else f"`{status_str}`"\n        lines.append(\n            f"| {idx} | `{ev.candidate_id}` | {persona_str} | {repro_str} | {ev.regressions_count} | {ev.diff_churn} | {ev.cyclomatic_delta} | **{ev.score:.1f}** | {status_cell} |"\n        )',
    )
    p20_cont = replace_once(
        mf_src,
        '                f"| `{s.file_path}` | `{s.function_name}` | {line_str} | `{s.bug_type}` | {conf_pct} | {s.reasoning} |"',
        '                f"| `{s.file_path}` | `{s.function_name}` | {line_str} | `{s.bug_type}` | {conf_pct} | {s.reasoning.replace(\'|\', \'\\\\|\').replace(chr(10), \' \')} |"',
    )
    p20_cont = replace_once(
        p20_cont,
        '    lines.append("")\n\n    # Section 4: Champion Section',
        '''    disq = [ev for ev in sorted_evals if ev.disqualified and ev.disqualification_reason]
    if disq:
        lines.append("### Disqualification Reasons")
        for ev in disq:
            lines.append(f"- `{ev.candidate_id}`: {ev.disqualification_reason}")
    lines.append("")

    # Section 4: Champion Section''',
    )
    specs["BUG-020"] = {
        "file": "src/bugarena/reporting/markdown_formatter.py",
        "repro": "bug_report/evidence/repro/BUG-020_repro.py",
        "cands": [
            ("cand_bug020_surgical", "surgical_minimalist", "Escape table cells and append disqualification_reason to status column.", make_diff("src/bugarena/reporting/markdown_formatter.py", mf_src, p20_surg)),
            ("cand_bug020_defensive", "defensive_guardian", "Add _md_cell sanitizer and list disqualification_reason items below leaderboard.", make_diff("src/bugarena/reporting/markdown_formatter.py", mf_src, p20_def)),
            ("cand_bug020_architectural", "architectural_fixer", "Introduce _escape_md_cell helper and surface disqualification reasons cleanly.", make_diff("src/bugarena/reporting/markdown_formatter.py", mf_src, p20_arch)),
            ("cand_bug020_contract", "contract_enforcer", "Enforce table escaping and emit explicit Disqualification Reasons section.", make_diff("src/bugarena/reporting/markdown_formatter.py", mf_src, p20_cont)),
        ],
    }

    # BUG-021: config.py
    cfg_src = read_src("src/bugarena/config.py")
    p21_surg = replace_once(
        cfg_src,
        '''    if dotenv_path:
        candidates.append(Path(dotenv_path).resolve())

    # Candidate 1: BugArena project root directory (d:/MCP server/.env)
    candidates.append(Path(__file__).resolve().parent.parent.parent / ".env")
    # Candidate 2: Current working directory
    candidates.append(Path.cwd() / ".env")
    # Candidate 3: User home .gemini/.env
    candidates.append(Path.home() / ".gemini" / ".env")''',
        '''    if dotenv_path:
        candidates = [Path(dotenv_path).resolve()]
    else:
        candidates.extend([
            Path(__file__).resolve().parent.parent.parent / ".env",
            Path.cwd() / ".env",
            Path.home() / ".gemini" / ".env",
        ])''',
    )
    p21_surg = replace_once(
        p21_surg,
        '''                    key, val = clean_line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\\"")''',
        '''                    key, val = clean_line.split("=", 1)
                    key = key.strip().removeprefix("export ").strip()
                    val = val.strip()
                    if val and val[0] in ("'", '"') and len(val) >= 2 and val[-1] == val[0]:
                        val = val[1:-1]
                    elif " #" in val:
                        val = val.split(" #", 1)[0].strip()''',
    )

    p21_def = replace_once(
        cfg_src,
        '''    candidates: list[Path] = []
    if dotenv_path:
        candidates.append(Path(dotenv_path).resolve())

    # Candidate 1: BugArena project root directory (d:/MCP server/.env)
    candidates.append(Path(__file__).resolve().parent.parent.parent / ".env")
    # Candidate 2: Current working directory
    candidates.append(Path.cwd() / ".env")
    # Candidate 3: User home .gemini/.env
    candidates.append(Path.home() / ".gemini" / ".env")''',
        '''    if dotenv_path is not None:
        candidates: list[Path] = [Path(dotenv_path).resolve()]
    else:
        candidates = [
            Path(__file__).resolve().parent.parent.parent / ".env",
            Path.cwd() / ".env",
            Path.home() / ".gemini" / ".env",
        ]''',
    )
    p21_def = replace_once(
        p21_def,
        '''                    key, val = clean_line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\\"")''',
        '''                    key, val = clean_line.split("=", 1)
                    key = key.strip()
                    if key.startswith("export "):
                        key = key[7:].strip()
                    val = val.strip()
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                        val = val[1:-1]
                    else:
                        val = val.split(" #", 1)[0].strip()''',
    )

    p21_arch = replace_once(
        cfg_src,
        "def load_env_file(dotenv_path: Path | str | None = None) -> None:",
        '''def _parse_env_assignment(clean_line: str) -> tuple[str, str]:
    key, raw_val = clean_line.split("=", 1)
    key = key.strip().removeprefix("export ").strip()
    val = raw_val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        return key, val[1:-1]
    return key, val.split(" #", 1)[0].strip()


def load_env_file(dotenv_path: Path | str | None = None) -> None:''',
    )
    p21_arch = replace_once(
        p21_arch,
        '''    candidates: list[Path] = []
    if dotenv_path:
        candidates.append(Path(dotenv_path).resolve())

    # Candidate 1: BugArena project root directory (d:/MCP server/.env)
    candidates.append(Path(__file__).resolve().parent.parent.parent / ".env")
    # Candidate 2: Current working directory
    candidates.append(Path.cwd() / ".env")
    # Candidate 3: User home .gemini/.env
    candidates.append(Path.home() / ".gemini" / ".env")''',
        '''    candidates: list[Path] = (
        [Path(dotenv_path).resolve()]
        if dotenv_path is not None
        else [
            Path(__file__).resolve().parent.parent.parent / ".env",
            Path.cwd() / ".env",
            Path.home() / ".gemini" / ".env",
        ]
    )''',
    )
    p21_arch = replace_once(
        p21_arch,
        '''                    key, val = clean_line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\\"")''',
        "                    key, val = _parse_env_assignment(clean_line)",
    )

    p21_cont = replace_once(
        cfg_src,
        '''    candidates: list[Path] = []
    if dotenv_path:
        candidates.append(Path(dotenv_path).resolve())

    # Candidate 1: BugArena project root directory (d:/MCP server/.env)
    candidates.append(Path(__file__).resolve().parent.parent.parent / ".env")
    # Candidate 2: Current working directory
    candidates.append(Path.cwd() / ".env")
    # Candidate 3: User home .gemini/.env
    candidates.append(Path.home() / ".gemini" / ".env")''',
        '''    candidates: list[Path] = [Path(dotenv_path).resolve()] if dotenv_path is not None else [
        Path(__file__).resolve().parent.parent.parent / ".env",
        Path.cwd() / ".env",
        Path.home() / ".gemini" / ".env",
    ]''',
    )
    p21_cont = replace_once(
        p21_cont,
        '''                    key, val = clean_line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\\"")''',
        '''                    key, val = clean_line.split("=", 1)
                    key = key.strip().removeprefix("export ").strip()
                    val = val.strip()
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                        val = val[1:-1]
                    else:
                        val = val.split("#", 1)[0].strip()''',
    )
    specs["BUG-021"] = {
        "file": "src/bugarena/config.py",
        "repro": "bug_report/evidence/repro/BUG-021_repro.py",
        "cands": [
            ("cand_bug021_surgical", "surgical_minimalist", "Respect explicit dotenv_path scope, strip matching quotes, export prefix, and inline comments.", make_diff("src/bugarena/config.py", cfg_src, p21_surg)),
            ("cand_bug021_defensive", "defensive_guardian", "Isolate explicit dotenv_path and safely parse quoted values, export keyword, and comments.", make_diff("src/bugarena/config.py", cfg_src, p21_def)),
            ("cand_bug021_architectural", "architectural_fixer", "Extract _parse_env_assignment helper and separate explicit vs fallback dotenv search.", make_diff("src/bugarena/config.py", cfg_src, p21_arch)),
            ("cand_bug021_contract", "contract_enforcer", "Enforce dotenv_path isolation, symmetric quote stripping, and comment removal contract.", make_diff("src/bugarena/config.py", cfg_src, p21_cont)),
        ],
    }

    return specs


if __name__ == "__main__":
    specs = build_all()
    mgr = EphemeralSandboxManager(".")
    out_json = {}
    for bug_id, info in specs.items():
        out_json[bug_id] = []
        for cid, persona, expl, diff in info["cands"]:
            parse_and_validate_patch(diff, PersonaType(persona), expl, candidate_id=cid)
            with mgr.create_sandbox() as sb:
                mgr.apply_patch(sb, diff)
                patched_file = sb / info["file"]
                ast.parse(patched_file.read_text(encoding="utf-8"))
                rel = "tests/repro/test_verify.py"
                t = sb / rel
                t.parent.mkdir(parents=True, exist_ok=True)
                t.write_text(Path(info["repro"]).read_text(encoding="utf-8"), encoding="utf-8")
                res = run_sandboxed_command(sb, [sys.executable, "-m", "pytest", rel, "-q"], timeout_seconds=30.0, env_override={"PYTHONPATH": "."})
                print(f"{bug_id} {cid}: exit={res.exit_code}")
                if res.exit_code != 0:
                    print("  FAIL:", res.stdout[:300], res.stderr[:200])
            out_json[bug_id].append({"candidate_id": cid, "persona": persona, "explanation": expl, "diff": diff})
    Path("bug_report/evidence/generated_patches.json").write_text(json.dumps(out_json, indent=2), encoding="utf-8")
    print("DONE")
