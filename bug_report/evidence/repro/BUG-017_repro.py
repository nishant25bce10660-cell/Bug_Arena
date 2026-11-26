"""Automated bug reproduction test case.
Bug description: generate_bug_report never links _REPRO_REGISTRY entries because it compares relative test_file_path to absolute repo_path
Target function: generate_bug_report in src/bugarena/server.py
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
    from src.bugarena.server import generate_bug_report
except ImportError:
    pass


def test_reproduction_generate_bug_report():
    """Reproduce defect: generate_bug_report never links _REPRO_REGISTRY entries because it compares relative test_file_path to absolute repo_path"""
    assert (lambda td: ((td / 'src').mkdir(), (td / 'src' / 'c.py').write_text('def f():\n return 1/0\n'), bug_reproduce(str(td), 'src/c.py', 'div zero', 'f', 'f()', 'f() == 0'), 'Failing Reproduction Test' in generate_bug_report(str(td), 'File "src/c.py", line 2, in f\nZeroDivisionError: division by zero', output_file=str(td / 'b.md'))['report_markdown'], __import__('shutil').rmtree(td, ignore_errors=True))[3])(Path(__import__('tempfile').mkdtemp())) == True
