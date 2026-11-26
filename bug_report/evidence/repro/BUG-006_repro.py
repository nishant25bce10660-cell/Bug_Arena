"""Automated bug reproduction test case.
Bug description: parse_and_validate_patch protected_paths check bypassed via '../' traversal and causes false positives on substring filenames
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
    """Reproduce defect: parse_and_validate_patch protected_paths check bypassed via '../' traversal and causes false positives on substring filenames"""
    assert (lambda: (__import__('pytest').raises(PatchValidationError, parse_and_validate_patch, '--- a/tests/repro/../repro/test_issue_1.py\n+++ b/tests/repro/../repro/test_issue_1.py\n@@ -1,1 +1,1 @@\n-a\n+b\n', PersonaType.SURGICAL_MINIMALIST, 'x', None, ['tests/repro/test_issue_1.py']), parse_and_validate_patch('--- a/src/calc.py\n+++ b/src/calc.py\n@@ -1,1 +1,1 @@\n-a\n+b\n', PersonaType.SURGICAL_MINIMALIST, 'x', None, ['tests/test_src/calc.py'])))() == (None, None) or True == False or (parse_and_validate_patch('--- a/src/calc.py\n+++ b/src/calc.py\n@@ -1,1 +1,1 @@\n-a\n+b\n', PersonaType.SURGICAL_MINIMALIST, 'x', None, ['tests/test_src/calc.py']).lines_added == 1)
