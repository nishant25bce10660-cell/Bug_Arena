"""Reproduction test generator creating minimal reproducible pytest cases."""

import ast
import re

from bugarena.models.bug import SuspectLocation


def _sanitize_docstring(text: str) -> str:
    """Sanitize docstring content to prevent triple-quote breakout injection attacks."""
    if not text:
        return ""
    clean = text.replace('"""', r'\"\"\"').replace("'''", r"\'\'\'")
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
    clean_func = suspect.function_name if suspect.function_name != "<module>" else "target"
    safe_desc = _sanitize_docstring(bug_description)

    # Derive module import path from relative file_path (e.g., src/math/calc.py -> src.math.calc)
    clean_path = suspect.file_path.replace("\\", "/").removesuffix(".py")
    clean_path = clean_path.removeprefix("./")
    import_path = clean_path.replace("/", ".")

    test_name = f"test_reproduction_{re.sub(r'[^a-zA-Z0-9_]', '_', clean_func)}"
    target_call = call_expr or f"{clean_func}()"

    # Handle expected exception vs value assertion
    assertion_block = ""
    if expected_behavior and "raises " in expected_behavior.lower():
        exc_name = expected_behavior.split("raises ", 1)[1].strip()
        assertion_block = f"    with pytest.raises({exc_name}):\n        {target_call}\n"
    elif expected_behavior and ("==" in expected_behavior or "assert" in expected_behavior):
        assertion_block = f"    assert {expected_behavior}\n"
    else:
        # Default assertion: call succeeds without unexpected error
        assertion_block = f"    result = {target_call}\n    assert result is not None\n"

    code = f'''"""Automated bug reproduction test case.
Bug description: {safe_desc}
Target function: {clean_func} in {suspect.file_path}
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
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
