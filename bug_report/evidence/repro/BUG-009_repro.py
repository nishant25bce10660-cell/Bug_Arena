"""Automated bug reproduction test case.
Bug description: calculate_cyclomatic_delta crashes with uncaught SyntaxError when radon parses malformed Python code
Target function: calculate_cyclomatic_delta in src/bugarena/evaluation/ast_metrics.py
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from src.bugarena.evaluation.ast_metrics import *
except ImportError:
    pass
try:
    from src.bugarena.evaluation.ast_metrics import calculate_cyclomatic_delta
except ImportError:
    pass


def test_reproduction_calculate_cyclomatic_delta():
    """Reproduce defect: calculate_cyclomatic_delta crashes with uncaught SyntaxError when radon parses malformed Python code"""
    assert isinstance(calculate_cyclomatic_delta('def f():\n    return 1\n', 'def broken(:\n'), int) == True
