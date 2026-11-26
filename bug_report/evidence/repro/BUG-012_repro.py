"""Automated bug reproduction test case.
Bug description: TournamentRunner omits PersonaType.CONTRACT_ENFORCER from default personas and overrides explicit empty sequence
Target function: TournamentRunner in src/bugarena/tournament/runner.py
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from src.bugarena.tournament.runner import *
except ImportError:
    pass
try:
    from src.bugarena.tournament.runner import TournamentRunner
except ImportError:
    pass


def test_reproduction_TournamentRunner():
    """Reproduce defect: TournamentRunner omits PersonaType.CONTRACT_ENFORCER from default personas and overrides explicit empty sequence"""
    assert (PersonaType.CONTRACT_ENFORCER in TournamentRunner().personas and len(TournamentRunner(personas=[]).personas) == 0) == True
