"""Automated bug reproduction test case.
Bug description: extract_diff_and_explanation fails on 'diff --git' fenced blocks and leaks closing markdown fence and commentary into diff
Target function: extract_diff_and_explanation in src/bugarena/tournament/providers/dispatcher.py
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from src.bugarena.tournament.providers.dispatcher import *
except ImportError:
    pass
try:
    from src.bugarena.tournament.providers.dispatcher import extract_diff_and_explanation
except ImportError:
    pass


def test_reproduction_extract_diff_and_explanation():
    """Reproduce defect: extract_diff_and_explanation fails on 'diff --git' fenced blocks and leaks closing markdown fence and commentary into diff"""
    assert ('```' not in extract_diff_and_explanation('Before\n```diff\ndiff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n```\nAfter')[0]) == True
