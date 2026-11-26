"""Automated bug reproduction test case.
Bug description: format_markdown_report omits disqualification_reason and format_bug_diagnostic_markdown leaves '|' unescaped in tables
Target function: format_markdown_report in src/bugarena/reporting/markdown_formatter.py
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from src.bugarena.reporting.markdown_formatter import *
except ImportError:
    pass
try:
    from src.bugarena.reporting.markdown_formatter import format_markdown_report
except ImportError:
    pass


def test_reproduction_format_markdown_report():
    """Reproduce defect: format_markdown_report omits disqualification_reason and format_bug_diagnostic_markdown leaves '|' unescaped in tables"""
    assert ('Reason line' in format_markdown_report(TournamentRecord(tournament_id='t1', repo_path='.', candidates=[__import__('bugarena.models.agent', fromlist=['CandidatePatch']).CandidatePatch(candidate_id='c1', persona=__import__('bugarena.models.agent', fromlist=['PersonaType']).PersonaType.SURGICAL_MINIMALIST, diff='--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n', explanation='e', lines_added=1, lines_deleted=1)], evaluations=[__import__('bugarena.models.tournament', fromlist=['PatchEvaluation']).PatchEvaluation(candidate_id='c1', repro_passed=False, regressions_count=0, total_regressions_checked=1, diff_churn=2, cyclomatic_delta=0, score=0.0, disqualified=True, disqualification_reason='Reason line')]))) == True
