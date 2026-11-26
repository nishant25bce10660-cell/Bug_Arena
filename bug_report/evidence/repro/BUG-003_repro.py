"""Automated bug reproduction test case.
Bug description: validate_red_baseline marks non-buggy src-layout repo as REPRODUCED_RED due to ImportError/NameError instead of ReproductionFalsePositiveError
Target function: validate_red_baseline in src/bugarena/synthesizer/red_validator.py
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from src.bugarena.synthesizer.red_validator import *
except ImportError:
    pass
try:
    from src.bugarena.synthesizer.red_validator import validate_red_baseline
except ImportError:
    pass


def test_reproduction_validate_red_baseline():
    """Reproduce defect: validate_red_baseline marks non-buggy src-layout repo as REPRODUCED_RED due to ImportError/NameError instead of ReproductionFalsePositiveError"""
    with pytest.raises(ReproductionFalsePositiveError):
        (lambda td: ((td / 'src' / 'pkg').mkdir(parents=True), (td / 'src' / 'pkg' / '__init__.py').write_text('', encoding='utf-8'), (td / 'src' / 'pkg' / 'helper.py').write_text('VAL = 42\n', encoding='utf-8'), (td / 'src' / 'pkg' / 'mod.py').write_text('from pkg.helper import VAL\ndef get_val():\n    return VAL\n', encoding='utf-8'), validate_red_baseline(td, 'tests/repro/test_issue_1.py', __import__('bugarena.synthesizer.test_generator', fromlist=['generate_reproduction_test_code']).generate_reproduction_test_code(__import__('bugarena.models.bug', fromlist=['SuspectLocation']).SuspectLocation(file_path='src/pkg/mod.py', function_name='get_val', line_range=(2, 3), confidence=0.9, bug_type='E', reasoning='r', code_snippet=''), 'get_val returns 42', 'get_val()', 'get_val() == 42')), __import__('shutil').rmtree(td, ignore_errors=True)))(Path(__import__('tempfile').mkdtemp()))
