"""Automated bug reproduction test case.
Bug description: locate_faulty_ast_slice returns inverted line_range=(1, 0) on empty files
Target function: locate_faulty_ast_slice in src/bugarena/discovery/ast_analyzer.py
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from src.bugarena.discovery.ast_analyzer import *
except ImportError:
    pass
try:
    from src.bugarena.discovery.ast_analyzer import locate_faulty_ast_slice
except ImportError:
    pass


def test_reproduction_locate_faulty_ast_slice():
    """Reproduce defect: locate_faulty_ast_slice returns inverted line_range=(1, 0) on empty files"""
    assert (lambda s: s is not None and s['line_range'][0] <= s['line_range'][1])(locate_faulty_ast_slice('', 5)) == True
