"""Automated bug reproduction test case.
Bug description: EphemeralSandboxManager._apply_hunks inserts blank lines for empty diff lines, miscomputes append hunk @@ -N,0 offset, and ignores context lines
Target function: EphemeralSandboxManager in src/bugarena/sandbox/manager.py
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from src.bugarena.sandbox.manager import *
except ImportError:
    pass
try:
    from src.bugarena.sandbox.manager import EphemeralSandboxManager
except ImportError:
    pass


def test_reproduction_EphemeralSandboxManager():
    """Reproduce defect: EphemeralSandboxManager._apply_hunks inserts blank lines for empty diff lines, miscomputes append hunk @@ -N,0 offset, and ignores context lines"""
    assert EphemeralSandboxManager('.')._apply_hunks(['line1', 'line2'], [('@@ -2,0 +3,1 @@', ['+line3', ''])]) == ['line1', 'line2', 'line3']
