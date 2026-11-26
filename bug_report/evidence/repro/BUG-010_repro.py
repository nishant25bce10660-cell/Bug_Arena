"""Automated bug reproduction test case.
Bug description: MultiModelDispatcher.generate_patch misroutes ollama/llama3.1 and ollama/gemma2 to Groq/Gemini cloud providers
Target function: MultiModelDispatcher in src/bugarena/tournament/providers/dispatcher.py
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
    from src.bugarena.tournament.providers.dispatcher import MultiModelDispatcher
except ImportError:
    pass


def test_reproduction_MultiModelDispatcher():
    """Reproduce defect: MultiModelDispatcher.generate_patch misroutes ollama/llama3.1 and ollama/gemma2 to Groq/Gemini cloud providers"""
    assert (lambda d: (setattr(d, '_call_ollama', __import__('unittest.mock').mock.AsyncMock(return_value=('diff', 'ollama_ok'))), setattr(d, '_call_groq', __import__('unittest.mock').mock.AsyncMock(return_value=('', 'wrong_groq'))), setattr(d, '_call_gemini', __import__('unittest.mock').mock.AsyncMock(return_value=('', 'wrong_gemini'))), __import__('asyncio').run(d.generate_patch(PersonaType.SURGICAL_MINIMALIST, BugSpec(bug_id='b', repo_path='.', error_log='e'), ReproTestSpec(test_file_path='t.py', test_code='pass', red_baseline_verified=True), model_override='ollama/llama3.1')))[3])(MultiModelDispatcher()) == ('diff', 'ollama_ok')
