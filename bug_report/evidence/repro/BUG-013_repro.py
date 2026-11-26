"""Automated bug reproduction test case.
Bug description: BugDiscoveryEngine resolves .venv/site-packages frames via unbounded rglob across .venv
Target function: BugDiscoveryEngine in src/bugarena/discovery/engine.py
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from src.bugarena.discovery.engine import *
except ImportError:
    pass
try:
    from src.bugarena.discovery.engine import BugDiscoveryEngine
except ImportError:
    pass


def test_reproduction_BugDiscoveryEngine():
    """Reproduce defect: BugDiscoveryEngine resolves .venv/site-packages frames via unbounded rglob across .venv"""
    assert (lambda td: ((td / '.venv' / 'Lib' / 'site-packages' / 'pkg').mkdir(parents=True), (td / '.venv' / 'Lib' / 'site-packages' / 'pkg' / 'runner.py').write_text('def run():\n pass\n', encoding='utf-8'), len(BugDiscoveryEngine(td).discover_from_trace('Traceback (most recent call last):\n  File "/usr/lib/python3.11/runner.py", line 2, in run\n    pass\nRuntimeError: err\n').suspects), __import__('shutil').rmtree(td, ignore_errors=True))[2])(Path(__import__('tempfile').mkdtemp())) == 0
