"""Automated bug reproduction test case.
Bug description: bug_reproduce returns stderr only as failure_output, omitting pytest stdout failure tracebacks, and evaluate_patches keeps stale repro_spec
Target function: bug_reproduce in src/bugarena/server.py
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from src.bugarena.server import *
except ImportError:
    pass
try:
    from src.bugarena.server import bug_reproduce
except ImportError:
    pass


def test_reproduction_bug_reproduce():
    """Reproduce defect: bug_reproduce returns stderr only as failure_output, omitting pytest stdout failure tracebacks, and evaluate_patches keeps stale repro_spec"""
    assert (lambda td: ((td / 'src').mkdir(), (td / 'src' / 'c.py').write_text('def f():\n return 1/0\n'), ('ZeroDivisionError' in bug_reproduce(str(td), 'src/c.py', 'div zero', 'f', 'f()', 'f() == 0')['failure_output']), __import__('shutil').rmtree(td, ignore_errors=True))[2])(Path(__import__('tempfile').mkdtemp())) == True
