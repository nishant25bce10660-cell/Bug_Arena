"""Regression test for ECC-024 (BA-001, BA-002): case-insensitive raises, assert, result, backslashes, <lambda>."""

import ast

import pytest

from bugarena.models.bug import SuspectLocation
from bugarena.synthesizer.test_generator import generate_reproduction_test_code


def test_ecc_024_all_branches_and_edge_cases():
    s = SuspectLocation(
        file_path=r"src\math_mod\calc.py",
        function_name="<lambda>",
        line_range=(1, 3),
        confidence=0.9,
        bug_type="ValueError",
        reasoning="bad",
        code_snippet="lambda x: 1/x",
    )

    # 1. Case-insensitive Raises
    c1 = generate_reproduction_test_code(s, r"C:\path\to\user\file", call_expr="fn(0)", expected_behavior="Raises ValueError")
    assert "with pytest.raises(ValueError):" in c1
    ast.parse(c1)

    # 2. Leading 'assert ' stripped cleanly
    c2 = generate_reproduction_test_code(s, "desc", call_expr="fn(1)", expected_behavior="assert fn(1) == 2")
    assert "assert assert" not in c2
    assert "assert fn(1) == 2" in c2
    ast.parse(c2)

    # 3. Non-'==' comparison & 'result' bound before assertion
    c3 = generate_reproduction_test_code(s, "desc", call_expr="fn(1)", expected_behavior="result > 0")
    assert "result = fn(1)" in c3
    assert "assert result > 0" in c3
    ast.parse(c3)

    # 4. Non-identifier module / function name doesn't break generated code
    s_bad = SuspectLocation(
        file_path="src/1-bad-name.py",
        function_name="target",
        line_range=(1, 1),
        confidence=0.9,
        bug_type="Err",
        reasoning="r",
        code_snippet="",
    )
    c4 = generate_reproduction_test_code(s_bad, "desc", call_expr="1 + 1", expected_behavior="1 + 1 == 2")
    ast.parse(c4)

    # 5. Unknown non-empty prose expected_behavior is rejected instead of ignored
    with pytest.raises(ValueError):
        generate_reproduction_test_code(s, "desc", call_expr="fn(1)", expected_behavior="should return positive float")
