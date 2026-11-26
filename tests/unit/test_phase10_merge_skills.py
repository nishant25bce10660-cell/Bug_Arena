"""Tests for Phase 10: merge_both_skills 4 mandatory security, collision, dependency, and merge scenarios."""

import json
from pathlib import Path

from bugarena.skills_merge import merge_both_skills


def _make_sample_skill(
    root: Path,
    *,
    tool_names: tuple[str, ...] = ("custom_xss_scan",),
    deps: tuple[str, ...] = ("pydantic>=2.0.0",),
    body_extra: str = "",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    dep_lines = ", ".join(f'"{d}"' for d in deps)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{root.name}"\nversion = "0.1.0"\ndependencies = [{dep_lines}]\n',
        encoding="utf-8",
    )
    tool_defs = "\n\n".join(
        f'def {t}(target: str = "") -> dict:\n    return {{"tool": "{t}", "target": target, "findings": []}}\n'
        for t in tool_names
    )
    tools_dict = ", ".join(f'"{t}": {t}' for t in tool_names)
    (root / "skill.py").write_text(
        f'"""Sample third-party skill."""\n\n{body_extra}\n{tool_defs}\nTOOLS = {{{tools_dict}}}\n',
        encoding="utf-8",
    )
    return root


def test_merge_both_skills_clean_skill_keeps_bugarena_primary(tmp_path: Path):
    skill_dir = _make_sample_skill(tmp_path / "clean_scanner", tool_names=("headers_lint",))
    out_root = tmp_path / "merged"

    # Default dry_run=True inspects without emitting runnable package
    dry = merge_both_skills(skill_dir, name="bugarena-clean", dry_run=True, output_root=out_root)
    assert dry["status"] == "DRY_RUN_PASSED"
    assert not (out_root / "bugarena-clean" / "adapter.py").exists()

    # Approved merge writes runnable package with BugArena as primary
    merged = merge_both_skills(
        skill_dir,
        name="bugarena-clean",
        dry_run=False,
        approved=True,
        output_root=out_root,
    )
    assert merged["status"] == "MERGED"
    manifest = json.loads((out_root / "bugarena-clean" / "merged_manifest.json").read_text(encoding="utf-8"))
    assert manifest["primary_mcp"] == "bugarena"
    assert manifest["tools"]["bug_detect"]["origin"] == "bugarena"
    assert manifest["tools"]["headers_lint"]["origin"] == "clean_scanner"
    assert (out_root / "bugarena-clean" / "MERGE_REPORT.md").is_file()
    assert (out_root / "bugarena-clean" / "adapter.py").is_file()


def test_merge_both_skills_namespaces_colliding_tool_bugarena_wins(tmp_path: Path):
    skill_dir = _make_sample_skill(tmp_path / "collider", tool_names=("bug_detect", "extra_probe"))
    out_root = tmp_path / "merged"

    res = merge_both_skills(skill_dir, dry_run=False, approved=True, output_root=out_root)
    assert res["status"] == "MERGED"
    manifest = json.loads(Path(res["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["tools"]["bug_detect"]["origin"] == "bugarena"
    assert "collider__bug_detect" in manifest["tools"]
    assert manifest["tools"]["collider__bug_detect"]["origin"] == "collider"
    assert len(res["collisions"]) == 1


def test_merge_both_skills_blocks_dangerous_code_pending_approval(tmp_path: Path):
    skill_dir = _make_sample_skill(
        tmp_path / "evil_skill",
        tool_names=("sneaky_tool",),
        body_extra='import subprocess\ndef _bad(cmd):\n    return eval("1+1"), subprocess.run(cmd)\n',
    )
    out_root = tmp_path / "merged"

    res = merge_both_skills(skill_dir, dry_run=False, approved=False, output_root=out_root)
    assert res["status"] == "APPROVAL_REQUIRED"
    assert res["security_hazards"]
    assert not (out_root / "bugarena-evil_skill" / "adapter.py").exists()


def test_merge_both_skills_rejects_conflicting_dependency(tmp_path: Path):
    skill_dir = _make_sample_skill(
        tmp_path / "old_dep_skill",
        tool_names=("legacy_scan",),
        deps=("mcp<1.0.0", "pydantic<1.9.0"),
    )
    out_root = tmp_path / "merged"

    res = merge_both_skills(skill_dir, dry_run=False, approved=True, output_root=out_root)
    assert res["status"] == "COMPATIBILITY_FAILED"
    assert res["dependency_conflicts"]
    assert not (out_root / "bugarena-old_dep_skill" / "adapter.py").exists()
