"""Regression test for ECC-040: README.md and SKILL.md stay synced with MCP tools and scoring."""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _server_tool_names() -> list[str]:
    tree = ast.parse((REPO_ROOT / "src" / "bugarena" / "server.py").read_text(encoding="utf-8"))
    tools: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                is_tool = (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr == "tool"
                ) or (isinstance(dec, ast.Attribute) and dec.attr == "tool")
                if is_tool:
                    tools.append(node.name)
    return tools


def test_ecc_040_all_server_tools_documented_and_no_local_paths():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    skill = (REPO_ROOT / ".agents" / "skills" / "bugarena-repair" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    tools = _server_tool_names()
    assert len(tools) >= 13
    for tool_name in tools:
        assert tool_name in readme, f"{tool_name} missing from README.md"
        assert tool_name in skill, f"{tool_name} missing from SKILL.md"

    for doc_name, text in (("README.md", readme), ("SKILL.md", skill)):
        assert "D:/MCP server" not in text, f"Hardcoded path in {doc_name}"
        assert "D:\\MCP server" not in text, f"Hardcoded path in {doc_name}"
        assert "nisha" not in text.lower(), f"Hardcoded user in {doc_name}"
