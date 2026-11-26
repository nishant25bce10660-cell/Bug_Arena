"""Automated bug reproduction test case.
Bug description: load_env_file fails to strip inline '#' comments and mishandles explicit dotenv_path scope
Target function: load_env_file in src/bugarena/config.py
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from src.bugarena.config import *
except ImportError:
    pass
try:
    from src.bugarena.config import load_env_file
except ImportError:
    pass


def test_reproduction_load_env_file():
    """Reproduce defect: load_env_file fails to strip inline '#' comments and mishandles explicit dotenv_path scope"""
    assert (lambda td: ((td / '.env').write_text('BA_PROBE_CFG_KEY=hello # comment\n', encoding='utf-8'), load_env_file(td / '.env'), os.environ.pop('BA_PROBE_CFG_KEY', None), __import__('shutil').rmtree(td, ignore_errors=True))[2])(Path(__import__('tempfile').mkdtemp())) == 'hello'
