"""Automated bug reproduction test case.
Bug description: parse_and_validate_patch rejects CRLF diffs and miscounts deleted lines starting with '--'
Target function: parse_and_validate_patch in src/bugarena/tournament/patch_parser.py
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from src.bugarena.tournament.patch_parser import *
except ImportError:
    pass
try:
    from src.bugarena.tournament.patch_parser import parse_and_validate_patch
except ImportError:
    pass


def test_reproduction_parse_and_validate_patch():
    """Reproduce defect: parse_and_validate_patch rejects CRLF diffs and miscounts deleted lines starting with '--'"""
    assert parse_and_validate_patch('--- a/src/calc.py\r\n+++ b/src/calc.py\r\n@@ -1,2 +1,1 @@\r\n--- comment\r\n keep\r\n', PersonaType.SURGICAL_MINIMALIST, 'crlf').lines_deleted == 1
