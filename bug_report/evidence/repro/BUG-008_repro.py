"""Automated bug reproduction test case.
Bug description: PatchEvaluator fails to disqualify patches introducing SyntaxError into untested Python modules and hardcodes cyclomatic_delta=0
Target function: PatchEvaluator in src/bugarena/evaluation/test_runner.py
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from src.bugarena.evaluation.test_runner import *
except ImportError:
    pass
try:
    from src.bugarena.evaluation.test_runner import PatchEvaluator
except ImportError:
    pass


def test_reproduction_PatchEvaluator():
    """Reproduce defect: PatchEvaluator fails to disqualify patches introducing SyntaxError into untested Python modules and hardcodes cyclomatic_delta=0"""
    assert (lambda td: ((td / 'src').mkdir(), (td / 'tests').mkdir(), (td / 'src' / 'calc.py').write_text('def add(a,b):\n return a-b\n'), (td / 'src' / 'other.py').write_text('def ok():\n return 1\n'), (td / 'tests' / 'test_ok.py').write_text('def test_ok():\n assert True\n'), PatchEvaluator(td).evaluate_candidates([CandidatePatch(candidate_id='c1', persona='surgical_minimalist', diff='--- a/src/calc.py\n+++ b/src/calc.py\n@@ -1,2 +1,2 @@\n def add(a,b):\n- return a-b\n+ return a+b\n--- a/src/other.py\n+++ b/src/other.py\n@@ -1,2 +1,2 @@\n-def ok():\n+def broken(:\n  return 1\n', explanation='x', lines_added=2, lines_deleted=2)], ReproTestSpec(test_file_path='tests/repro/test_r.py', test_code='from src.calc import add\ndef test_r():\n assert add(1,2)==3\n', red_baseline_verified=True))[0][0].disqualified, __import__('shutil').rmtree(td, ignore_errors=True))[5])(Path(__import__('tempfile').mkdtemp())) == True
