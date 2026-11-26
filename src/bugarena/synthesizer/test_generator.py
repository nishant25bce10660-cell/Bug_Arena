"""Reproduction test generator creating minimal reproducible pytest cases."""

import ast
import re

from bugarena.models.bug import SuspectLocation

_FORBIDDEN_NAMES = frozenset({
    "__import__",
    "eval",
    "exec",
    "compile",
    "open",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "breakpoint",
    "input",
    "exit",
    "quit",
    "system",
    "popen",
})

_FORBIDDEN_ATTRS = frozenset({
    "system",
    "popen",
    "run",
    "Popen",
    "write_text",
    "write_bytes",
    "unlink",
    "rmdir",
    "mkdir",
    "replace",
    "rename",
})

_ALLOWED_EXPR_NODES = (
    ast.Expression,
    ast.Call,
    ast.Attribute,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Compare,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Subscript,
    ast.Slice,
    ast.Tuple,
    ast.List,
    ast.Dict,
    ast.Set,
    ast.keyword,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Is,
    ast.IsNot,
    ast.In,
    ast.NotIn,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.UAdd,
    ast.USub,
    ast.Invert,
)


_ALLOWED_EXPR_NODE_TYPES = frozenset(_ALLOWED_EXPR_NODES)


def _validate_safe_expression(expr: str, label: str = "expression") -> str:
    """Validate an untrusted expression against a strict Python AST expression allowlist."""
    stripped = expr.strip()
    try:
        tree = ast.parse(stripped, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Unsafe or invalid {label}: {exc}") from exc

    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_EXPR_NODE_TYPES:
            raise ValueError(
                f"Unsafe AST construct {type(node).__name__} disallowed in {label}"
            )
        if isinstance(node, ast.Name) and (
            node.id.startswith("__") or node.id in _FORBIDDEN_NAMES
        ):
            raise ValueError(f"Unsafe identifier {node.id!r} disallowed in {label}")
        if isinstance(node, ast.Attribute) and (
            node.attr.startswith("__") or node.attr in _FORBIDDEN_ATTRS
        ):
            raise ValueError(f"Unsafe attribute {node.attr!r} disallowed in {label}")
    return stripped


def _sanitize_docstring(text: str) -> str:
    """Sanitize docstring content to prevent backslash and triple-quote breakout attacks."""
    if not text:
        return ""
    clean = text.replace("\\", "\\\\")
    clean = clean.replace('"""', r'\"\"\"').replace("'''", r"\'\'\'")
    return clean.replace("\r", "")


def generate_reproduction_test_code(
    suspect: SuspectLocation,
    bug_description: str,
    call_expr: str | None = None,
    expected_behavior: str | None = None,
) -> str:
    """
    Generate an isolated, executable reproduction test script using pytest.
    """
    raw_func = suspect.function_name
    clean_func = raw_func if raw_func.isidentifier() else "target"
    safe_desc = _sanitize_docstring(bug_description)
    safe_file_path = _sanitize_docstring(suspect.file_path)

    # Derive module import path from relative file_path (e.g., src/math/calc.py -> src.math.calc)
    rel_posix = suspect.file_path.replace("\\", "/").removeprefix("./")
    clean_path = rel_posix.removesuffix(".py")
    import_path = clean_path.replace("/", ".")
    is_valid_dotted = bool(import_path) and all(part.isidentifier() for part in import_path.split("."))

    test_name = f"test_reproduction_{re.sub(r'[^a-zA-Z0-9_]', '_', clean_func)}"
    if call_expr is not None and call_expr.strip():
        target_call = _validate_safe_expression(call_expr, "call_expr")
    else:
        target_call = f"{clean_func}()"

    # Handle expected exception vs value/boolean assertion cleanly
    assertion_block = ""
    if expected_behavior and expected_behavior.strip():
        eb_clean = expected_behavior.strip()
        raises_match = re.search(r"\braises\s+([A-Za-z_][A-Za-z0-9_.]*)", eb_clean, re.IGNORECASE)
        if raises_match:
            exc_name = _validate_safe_expression(raises_match.group(1), "expected_behavior")
            assertion_block = f"    with pytest.raises({exc_name}):\n        {target_call}\n"
        elif re.match(r"^\s*raises\b", eb_clean, re.IGNORECASE):
            raise ValueError(f"Missing exception class after 'raises' in expected_behavior: {eb_clean!r}")
        else:
            expr_candidate = re.sub(r"^\s*assert\s+", "", eb_clean, flags=re.IGNORECASE)
            safe_expr = _validate_safe_expression(expr_candidate, "expected_behavior")
            expr_tree = ast.parse(safe_expr, mode="eval")
            uses_result = any(
                isinstance(node, ast.Name) and node.id == "result" for node in ast.walk(expr_tree)
            )
            if uses_result:
                assertion_block = f"    result = {target_call}\n    assert {safe_expr}\n"
            else:
                assertion_block = f"    assert {safe_expr}\n"
    else:
        assertion_block = f"    result = {target_call}\n    assert result is not None\n"

    if is_valid_dotted:
        import_block = f"_target_mod = importlib.import_module({import_path!r})"
    else:
        import_block = (
            "import importlib.util\n"
            f"_mod_path = root_dir / {rel_posix!r}\n"
            "_spec = importlib.util.spec_from_file_location('bugarena_target', _mod_path)\n"
            "if _spec is None or _spec.loader is None:\n"
            "    raise ImportError(f'Cannot load module at {_mod_path}')\n"
            "_target_mod = importlib.util.module_from_spec(_spec)\n"
            "_spec.loader.exec_module(_target_mod)"
        )

    code = f'''"""Automated bug reproduction test case.
Bug description: {safe_desc}
Target function: {clean_func} in {safe_file_path}
"""

import importlib
import sys
from pathlib import Path

import pytest

# Locate repository root cleanly and ensure both root and src/ are in sys.path
_here = Path(__file__).resolve()
root_dir = _here.parent.parent
for _cand in _here.parents:
    if any((_cand / _m).exists() for _m in ("pyproject.toml", "src", ".git")):
        root_dir = _cand
        break
for _p in (root_dir / "src", root_dir):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

{import_block}
globals().update({{_k: _v for _k, _v in vars(_target_mod).items() if not _k.startswith("__")}})


def {test_name}():
    """Reproduce defect: {safe_desc}"""
{assertion_block}
'''

    # Ensure generated code is syntactically valid before returning
    try:
        ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"Generated test code failed syntax validation: {e}") from e

    return code
