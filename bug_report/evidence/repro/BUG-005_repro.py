"""Automated bug reproduction test case.
Bug description: EphemeralSandboxManager.apply_patch wipes file when deleting a line starting with '-- ' ('--- ' in unified diff)
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
    """Reproduce defect: EphemeralSandboxManager.apply_patch wipes file when deleting a line starting with '-- ' ('--- ' in unified diff)"""
    assert (lambda td: ((td / 'q.sql').write_text('-- old\nSELECT 1;\n', encoding='utf-8'), EphemeralSandboxManager(td).apply_patch(td, '--- a/q.sql\n+++ b/q.sql\n@@ -1,2 +1,1 @@\n--- old\n SELECT 1;\n'), (td / 'q.sql').read_text(encoding='utf-8'), __import__('shutil').rmtree(td, ignore_errors=True))[2])(Path(__import__('tempfile').mkdtemp())) == 'SELECT 1;\n'
