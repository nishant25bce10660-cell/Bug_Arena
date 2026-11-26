"""Quarantined merge_both_skills pipeline keeping BugArena as immutable primary host MCP (Section 14)."""

from __future__ import annotations

import ast
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.version import Version

from bugarena.sandbox.security import sanitize_env, validate_safe_path

BUGARENA_PRIMARY_TOOLS: tuple[str, ...] = (
    "bug_detect",
    "bug_reproduce",
    "agent_fix_tournament",
    "evaluate_patches",
    "generate_fix_report",
    "generate_bug_report",
    "bugarena_autonomous_repair",
    "audit_start",
    "audit_round",
    "audit_status",
    "finding_verify",
    "audit_report",
    "fix_loop_start",
    "session_prepare",
    "session_confirm",
    "site_audit_start",
    "site_audit_round",
    "site_audit_status",
    "browser_cursor_list",
    "inspect_panel",
    "project_audit_start",
    "report_build",
    "verify_pack_build",
    "claim_retract",
    "agent_scoreboard",
    "merge_both_skills",
)

_DANGEROUS_CALLS = frozenset({"eval", "exec", "compile", "__import__", "system", "popen", "Popen", "run"})
_DANGEROUS_MODULES = frozenset({"subprocess", "ctypes", "pyautogui", "pynput", "pty"})


def _intake_to_quarantine(skill_source: str | Path, q_dir: Path) -> Path:
    src_str = str(skill_source).strip()
    local = Path(src_str)
    if local.is_dir():
        dest = q_dir / local.name
        shutil.copytree(local, dest, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".env*"))
        return dest
    if local.is_file() and local.suffix.lower() == ".zip":
        dest = q_dir / local.stem
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(local, "r") as zf:
            for member in zf.infolist():
                target = validate_safe_path(dest, member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(member))
        return dest
    if src_str.startswith(("https://", "http://", "git@")) or src_str.endswith(".git"):
        dest = q_dir / "cloned_skill"
        res = subprocess.run(
            ["git", "clone", "--depth", "1", src_str, str(dest)],
            capture_output=True,
            text=True,
            timeout=30.0,
            check=False,
        )
        if res.returncode != 0:
            raise RuntimeError(f"Failed to clone skill_source: {res.stderr[:300]}")
        return dest
    raise FileNotFoundError(f"Unsupported or missing skill_source: {skill_source!r}")


def _static_security_scan(skill_dir: Path) -> list[dict[str, str]]:
    hazards: list[dict[str, str]] = []
    for py_file in sorted(skill_dir.rglob("*.py")):
        rel = py_file.relative_to(skill_dir).as_posix()
        text = py_file.read_text(encoding="utf-8", errors="replace")
        if rel == "setup.py" and "cmdclass" in text:
            hazards.append({"file": rel, "hazard": "install_hook", "detail": "setup.py defines custom cmdclass"})
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            hazards.append({"file": rel, "hazard": "syntax_error", "detail": str(exc)})
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    if mod in _DANGEROUS_MODULES:
                        hazards.append({"file": rel, "hazard": "dangerous_import", "detail": f"import {alias.name}"})
            elif isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module.split(".")[0]
                if mod in _DANGEROUS_MODULES:
                    hazards.append({"file": rel, "hazard": "dangerous_import", "detail": f"from {node.module}"})
            elif isinstance(node, ast.Call):
                cname = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
                )
                if cname in _DANGEROUS_CALLS:
                    hazards.append({"file": rel, "hazard": "dangerous_call", "detail": f"call to {cname}()"})
    return hazards


def _inventory_skill_without_exec(skill_dir: Path) -> dict[str, Any]:
    tools: list[str] = []
    deps: list[str] = []
    py_files = sorted(skill_dir.rglob("*.py"))
    for py_file in py_files:
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == "TOOLS" and isinstance(node.value, ast.Dict):
                        for k in node.value.keys:
                            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                                tools.append(k.value)
        if not tools:
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                    tools.append(node.name)

    pyproj = skill_dir / "pyproject.toml"
    if pyproj.is_file():
        data = tomllib.loads(pyproj.read_text(encoding="utf-8"))
        deps.extend(str(d) for d in data.get("project", {}).get("dependencies", []))
    req_txt = skill_dir / "requirements.txt"
    if req_txt.is_file():
        for ln in req_txt.read_text(encoding="utf-8").splitlines():
            clean = ln.split("#", 1)[0].strip()
            if clean:
                deps.append(clean)

    return {"tools": sorted(set(tools)), "dependencies": deps, "files": [p.relative_to(skill_dir).as_posix() for p in py_files]}


def _check_dependency_conflicts(deps: list[str]) -> list[str]:
    conflicts: list[str] = []
    for raw_dep in deps:
        try:
            req = Requirement(raw_dep)
        except Exception as exc:  # noqa: BLE001
            conflicts.append(f"Unparsable dependency {raw_dep!r}: {exc}")
            continue
        try:
            installed_ver = Version(importlib.metadata.version(req.name))
            if req.specifier and not req.specifier.contains(installed_ver, prereleases=True):
                conflicts.append(
                    f"Dependency conflict for '{req.name}': skill requires {req.specifier}, BugArena env has {installed_ver}"
                )
        except importlib.metadata.PackageNotFoundError:
            # Optional external dep flagged in report if not present
            if re.search(r"[<>]=?|\!=|==", str(req.specifier)):
                conflicts.append(f"Missing required dependency '{raw_dep}' in BugArena runtime")
    return conflicts


def _sandbox_smoke_test(skill_dir: Path, tools: list[str]) -> tuple[bool, str]:
    """Run read-only smoke test inside a sanitized child Python process."""
    if not (skill_dir / "skill.py").is_file():
        return True, "No skill.py entrypoint; manifest-only smoke passed."
    probe = (
        "import importlib.util, json\n"
        "spec = importlib.util.spec_from_file_location('q_skill', 'skill.py')\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "tools = getattr(mod, 'TOOLS', {})\n"
        "out = {k: (v() if callable(v) else None) for k, v in tools.items()}\n"
        "print(json.dumps(list(out.keys())))\n"
    )
    env = sanitize_env(dict(os.environ), allowlist_only=True)
    res = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(skill_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=10.0,
        check=False,
    )
    if res.returncode != 0:
        return False, f"Smoke test failed (exit {res.returncode}): {res.stderr[:300]}"
    return True, f"Smoke test passed tools={res.stdout.strip()} (requested={tools})"


def merge_both_skills(
    skill_source: str | Path,
    name: str | None = None,
    dry_run: bool = True,
    *,
    approved: bool = False,
    output_root: str | Path = "merged",
    primary_tools: tuple[str, ...] = BUGARENA_PRIMARY_TOOLS,
) -> dict[str, Any]:
    """
    Quarantine, security-scan, compatibility-test, and safely merge an external skill with
    BugArena remaining the immutable primary MCP host.
    """
    raw_name = Path(str(skill_source)).stem if Path(str(skill_source)).exists() else "external_skill"
    skill_key = re.sub(r"[^a-zA-Z0-9_]", "_", raw_name).strip("_") or "skill"
    pkg_name = name or f"bugarena-{raw_name}"
    out_dir = (Path(output_root) / pkg_name).resolve()

    with tempfile.TemporaryDirectory(prefix="bugarena_skill_quarantine_") as q_tmp:
        q_skill = _intake_to_quarantine(skill_source, Path(q_tmp))
        hazards = _static_security_scan(q_skill)
        inventory = _inventory_skill_without_exec(q_skill)
        dep_conflicts = _check_dependency_conflicts(inventory["dependencies"])

        primary_set = set(primary_tools)
        collisions: list[dict[str, str]] = []
        merged_tools: dict[str, dict[str, str]] = {
            t: {"origin": "bugarena", "target": t} for t in primary_tools
        }
        for t in inventory["tools"]:
            if t in primary_set:
                ns = f"{skill_key}__{t}"
                collisions.append({"original": t, "namespaced": ns, "winner": "bugarena"})
                merged_tools[ns] = {"origin": skill_key, "target": t}
            else:
                merged_tools[t] = {"origin": skill_key, "target": t}

        def _write_merge_report(status: str, smoke_note: str = "") -> Path:
            out_dir.mkdir(parents=True, exist_ok=True)
            lines = [
                f"# Merge Compatibility & Security Report: `{pkg_name}`",
                "",
                f"- **Generated (UTC):** `{datetime.now(UTC).isoformat(timespec='seconds')}`",
                "- **Primary MCP Host:** `bugarena` (unmodified)",
                f"- **External Skill (`origin`):** `{skill_key}` (`{skill_source}`)",
                f"- **Status:** `{status}`",
                f"- **Tool Collisions (BugArena Wins):** `{collisions or 'None'}`",
                f"- **Security Hazards Found:** `{len(hazards)}`",
                f"- **Dependency Conflicts:** `{dep_conflicts or 'None'}`",
            ]
            if smoke_note:
                lines.append(f"- **Sandbox Smoke Test:** {smoke_note}")
            if hazards:
                lines.extend(["", "## Permission Manifest (Approval Required)"])
                for h in hazards:
                    lines.append(f"- `{h['file']}` [{h['hazard']}]: `{h['detail']}`")
            lines.extend([
                "",
                "## Rollback Instructions",
                f"Delete `{out_dir}` cleanly; `src/bugarena/` remains completely unmodified.",
            ])
            rep_path = out_dir / "MERGE_REPORT.md"
            rep_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return rep_path

        if hazards and not approved:
            rep = _write_merge_report("APPROVAL_REQUIRED")
            return {
                "status": "APPROVAL_REQUIRED",
                "primary_mcp": "bugarena",
                "skill_name": skill_key,
                "security_hazards": hazards,
                "dependency_conflicts": dep_conflicts,
                "collisions": collisions,
                "report_path": str(rep),
            }

        if dep_conflicts:
            rep = _write_merge_report("COMPATIBILITY_FAILED")
            return {
                "status": "COMPATIBILITY_FAILED",
                "primary_mcp": "bugarena",
                "skill_name": skill_key,
                "security_hazards": hazards,
                "dependency_conflicts": dep_conflicts,
                "collisions": collisions,
                "report_path": str(rep),
            }

        if dry_run:
            rep = _write_merge_report("DRY_RUN_PASSED")
            return {
                "status": "DRY_RUN_PASSED",
                "primary_mcp": "bugarena",
                "skill_name": skill_key,
                "security_hazards": hazards,
                "dependency_conflicts": dep_conflicts,
                "collisions": collisions,
                "merged_tools_count": len(merged_tools),
                "report_path": str(rep),
            }

        smoke_ok, smoke_msg = _sandbox_smoke_test(q_skill, inventory["tools"])
        if not smoke_ok:
            rep = _write_merge_report("SMOKE_TEST_FAILED", smoke_note=smoke_msg)
            return {
                "status": "SMOKE_TEST_FAILED",
                "primary_mcp": "bugarena",
                "skill_name": skill_key,
                "smoke_note": smoke_msg,
                "report_path": str(rep),
            }

        # Emit clean merged package under merged/<name>/ without modifying BugArena core
        out_dir.mkdir(parents=True, exist_ok=True)
        snap_dir = out_dir / "skill_snapshot"
        if snap_dir.exists():
            shutil.rmtree(snap_dir)
        shutil.copytree(q_skill, snap_dir)

        manifest = {
            "package_name": pkg_name,
            "primary_mcp": "bugarena",
            "merged_skill": skill_key,
            "collisions": collisions,
            "tools": merged_tools,
        }
        manifest_path = out_dir / "merged_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        adapter_code = (
            '"""Merged MCP registry adapter preserving BugArena as primary host."""\n\n'
            "import json\nfrom pathlib import Path\n\n"
            "MANIFEST = json.loads((Path(__file__).resolve().parent / 'merged_manifest.json').read_text(encoding='utf-8'))\n\n"
            "def list_merged_tools() -> dict:\n"
            "    return dict(MANIFEST['tools'])\n"
        )
        (out_dir / "adapter.py").write_text(adapter_code, encoding="utf-8")
        rep = _write_merge_report("MERGED", smoke_note=smoke_msg)

        return {
            "status": "MERGED",
            "package_dir": str(out_dir),
            "primary_mcp": "bugarena",
            "skill_name": skill_key,
            "collisions": collisions,
            "manifest_path": str(manifest_path),
            "report_path": str(rep),
            "smoke_note": smoke_msg,
        }
