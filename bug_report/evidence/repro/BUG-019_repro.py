"""Automated bug reproduction test case.
Bug description: scrub_sensitive_data breaks [WORKSPACE] replacement on Windows user temp paths and validate_safe_path accepts '.'
Target function: scrub_sensitive_data in src/bugarena/sandbox/security.py
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from src.bugarena.sandbox.security import *
except ImportError:
    pass
try:
    from src.bugarena.sandbox.security import scrub_sensitive_data
except ImportError:
    pass


def test_reproduction_scrub_sensitive_data():
    """Reproduce defect: scrub_sensitive_data breaks [WORKSPACE] replacement on Windows user temp paths and validate_safe_path accepts '.'"""
    assert ('[WORKSPACE]' in scrub_sensitive_data('Error at C:\\Users\\alice\\AppData\\Local\\Temp\\sb\\a.py', base_dir='C:\\Users\\alice\\AppData\\Local\\Temp\\sb')) == True
