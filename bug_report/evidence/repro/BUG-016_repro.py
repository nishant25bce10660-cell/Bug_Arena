"""Automated bug reproduction test case.
Bug description: generate_fix_report drops champion_patch/eval in FixReport and writes Markdown instead of JSON when format='json'
Target function: generate_fix_report in src/bugarena/server.py
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
    from src.bugarena.server import generate_fix_report
except ImportError:
    pass


def test_reproduction_generate_fix_report():
    """Reproduce defect: generate_fix_report drops champion_patch/eval in FixReport and writes Markdown instead of JSON when format='json'"""
    assert (lambda td: (__import__('src.bugarena.server', fromlist=['_store_tournament'])._store_tournament('t_b16', TournamentRecord(tournament_id='t_b16', repo_path=str(td), candidates=[CandidatePatch(candidate_id='c1', persona=PersonaType.SURGICAL_MINIMALIST, diff='--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n', explanation='x', lines_added=1, lines_deleted=1)], evaluations=[__import__('bugarena.models.tournament', fromlist=['PatchEvaluation']).PatchEvaluation(candidate_id='c1', repro_passed=True, regressions_count=0, total_regressions_checked=1, diff_churn=2, cyclomatic_delta=0, score=99.4)], champion_candidate_id='c1')), (lambda r: (r['report']['champion_patch'] is not None and r['report']['champion_eval'] is not None and Path(r['report_file_path']).read_text(encoding='utf-8').lstrip().startswith('{')))(generate_fix_report('t_b16', format='json', output_file=str(td / 'out.json'))), __import__('shutil').rmtree(td, ignore_errors=True))[1])(Path(__import__('tempfile').mkdtemp())) == True
