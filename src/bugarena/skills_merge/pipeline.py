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

_DANGEROUS_CALLS = frozenset({
    "eval", "exec", "compile", "__import__", "system", "popen", "Popen", "run",
    "getattr", "setattr", "vars", "globals", "rmtree", "unlink", "remove", "write_text", "write_bytes",
    "replace", "rename", "move", "copy", "copy2", "copyfile", "copytree",
    "execv", "execve", "execvp", "execl", "execlp", "spawnl", "spawnvp", "posix_spawn",
    "create_subprocess_exec", "create_subprocess_shell",
})
_DANGEROUS_MODULES = frozenset({
    "subprocess", "ctypes", "cffi", "pyautogui", "pynput", "pty",
    "importlib", "runpy", "pickle", "marshal", "urllib", "http", "socket",
    "httpx", "requests", "aiohttp", "websockets",
    "builtins", "sys", "ftplib", "smtplib", "xmlrpc", "webbrowser",
})
_VALID_PKG_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAX_ZIP_BYTES = 10 * 1024 * 1024


def _intake_to_quarantine(skill_source: str | Path, q_dir: Path) -> Path:
    src_str = str(skill_source).strip()
    if not src_str or src_str.startswith("-"):
        raise ValueError(f"Invalid skill_source {skill_source!r}")
    local = Path(src_str)
    if local.is_dir():
        dest = q_dir / local.name
        shutil.copytree(
            local,
            dest,
            symlinks=True,
            ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".env*"),
        )
        return dest
    if local.is_file() and local.suffix.lower() == ".zip":
        dest = q_dir / local.stem
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(local, "r") as zf:
            total_bytes = 0
            for member in zf.infolist():
                target = validate_safe_path(dest, member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    total_bytes += max(0, int(member.file_size))
                    if member.file_size > _MAX_ZIP_BYTES or total_bytes > _MAX_ZIP_BYTES:
                        raise ValueError(f"Zip skill archive exceeds {_MAX_ZIP_BYTES} byte cap")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(member))
        return dest
    from urllib.parse import urlparse

    parsed = urlparse(src_str)
    if parsed.scheme in ("http", "git", "ssh", "file", "ext") or src_str.startswith("git@"):
        raise ValueError(f"Only https:// git remotes are permitted for skill intake, got {skill_source!r}")
    if parsed.scheme == "https" and parsed.netloc:
        dest = q_dir / "cloned_skill"
        env = sanitize_env(dict(os.environ), allowlist_only=True)
        res = subprocess.run(
            ["git", "-c", "protocol.ext.allow=never", "clone", "--depth", "1", "--", src_str, str(dest)],
            env=env,
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
    for p in sorted(skill_dir.rglob("*")):
        rel = p.relative_to(skill_dir).as_posix()
        if p.is_symlink():
            hazards.append({"file": rel, "hazard": "symlink", "detail": "Symlink entry not permitted in untrusted skill"})
        elif p.suffix.lower() in (".sh", ".ps1", ".bat", ".cmd", ".pth"):
            hazards.append({"file": rel, "hazard": "non_python_script", "detail": f"Executable/hook file {p.suffix}"})
    pyproj = skill_dir / "pyproject.toml"
    if pyproj.is_file():
        try:
            pdata = tomllib.loads(pyproj.read_text(encoding="utf-8", errors="replace"))
            if isinstance(pdata, dict) and "build-system" in pdata:
                hazards.append({"file": "pyproject.toml", "hazard": "build_hook", "detail": "Custom [build-system] section"})
        except tomllib.TOMLDecodeError as exc:
            hazards.append({"file": "pyproject.toml", "hazard": "invalid_toml", "detail": str(exc)})
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
                if cname == "open":
                    mode_val = ""
                    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                        mode_val = node.args[1].value
                    for kw in node.keywords:
                        if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            mode_val = kw.value.value
                    if any(ch in mode_val for ch in ("w", "a", "x", "+")):
                        hazards.append({"file": rel, "hazard": "dangerous_call", "detail": f"write-mode open({mode_val!r})"})
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
        try:
            data = tomllib.loads(pyproj.read_text(encoding="utf-8", errors="replace"))
            deps.extend(str(d) for d in data.get("project", {}).get("dependencies", []))
        except tomllib.TOMLDecodeError:
            pass
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
            conflicts.append(f"Missing required dependency '{raw_dep}' in BugArena runtime")
    return conflicts


def _sandbox_smoke_test(skill_dir: Path, tools: list[str]) -> tuple[bool, str]:
    """Run read-only smoke test inside a sanitized child Python process across discovered tool modules."""
    py_mods = sorted(skill_dir.rglob("*.py"))
    entry = skill_dir / "skill.py"
    candidates = [entry] if entry.is_file() else [p for p in py_mods if p.name != "__init__.py"]
    if not candidates:
        return True, "No Python tool entrypoint; manifest-only smoke passed."
    probe = (
        "import importlib.util, json, sys\n"
        "loaded = []\n"
        "for path in sys.argv[1:]:\n"
        "  spec = importlib.util.spec_from_file_location('q_skill', path)\n"
        "  mod = importlib.util.module_from_spec(spec)\n"
        "  spec.loader.exec_module(mod)\n"
        "  tools = getattr(mod, 'TOOLS', {})\n"
        "  out = {k: (v() if callable(v) else None) for k, v in tools.items()}\n"
        "  loaded.extend(out.keys())\n"
        "print(json.dumps(loaded))\n"
    )
    env = sanitize_env(dict(os.environ), allowlist_only=True)
    try:
        res = subprocess.run(
            [sys.executable, "-c", probe, *(str(c.relative_to(skill_dir)) for c in candidates)],
            cwd=str(skill_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "Smoke test timed out after 10.0s"
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
    pkg_name = name or f"bugarena-{re.sub(r'[^A-Za-z0-9._-]', '_', raw_name) or 'skill'}"
    if not _VALID_PKG_NAME_RE.match(pkg_name) or ".." in pkg_name:
        raise ValueError(f"Invalid merged package name {pkg_name!r}")
    out_root = Path(output_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    out_dir = validate_safe_path(out_root, pkg_name)

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

        if not dry_run and not approved:
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
        shutil.copytree(q_skill, snap_dir, symlinks=True)

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
