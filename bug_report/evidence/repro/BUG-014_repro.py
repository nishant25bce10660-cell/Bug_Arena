"""Automated bug reproduction test case.
Bug description: parse_python_traceback drops <lambda> scope to <module> and misparses trailing colon lines as exception messages
Target function: parse_python_traceback in src/bugarena/discovery/log_parser.py
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from src.bugarena.discovery.log_parser import *
except ImportError:
    pass
try:
    from src.bugarena.discovery.log_parser import parse_python_traceback
except ImportError:
    pass


def test_reproduction_parse_python_traceback():
    """Reproduce defect: parse_python_traceback drops <lambda> scope to <module> and misparses trailing colon lines as exception messages"""
    assert (lambda ts: len(ts) == 1 and ts[0].function_name == '<lambda>' and ts[0].error_message == 'ZeroDivisionError: division by zero')(parse_python_traceback('Traceback (most recent call last):\n  File "a.py", line 1, in <lambda>\n    f = lambda: 1/0\nZeroDivisionError: division by zero\nNote: see docs')) == True
