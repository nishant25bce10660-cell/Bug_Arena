"""Automated bug reproduction test case.
Bug description: generate_reproduction_test_code crashes with IndexError when expected_behavior uses capitalized Raises prefix
Target function: generate_reproduction_test_code in src/bugarena/synthesizer/test_generator.py
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from src.bugarena.synthesizer.test_generator import *
except ImportError:
    pass
try:
    from src.bugarena.synthesizer.test_generator import generate_reproduction_test_code
except ImportError:
    pass


def test_reproduction_generate_reproduction_test_code():
    """Reproduce defect: generate_reproduction_test_code crashes with IndexError when expected_behavior uses capitalized Raises prefix"""
    assert ('with pytest.' 'raises(ValueError):' in generate_reproduction_test_code(SuspectLocation(file_path='a.py', function_name='f', line_range=(1, 1), confidence=0.9, bug_type='Err', reasoning='r', code_snippet=''), 'desc', 'f()', 'R' 'aises ValueError')) == True
