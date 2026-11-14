import pytest

from bugarena.models.agent import PersonaType
from bugarena.models.bug import BugSpec, SuspectLocation
from bugarena.models.repro import ReproTestSpec
from bugarena.tournament.providers.dispatcher import (
    MultiModelDispatcher,
    build_repair_prompt,
    extract_diff_and_explanation,
    get_recommended_model_for_persona,
)

SAMPLE_LLM_RESPONSE = """
Here is the fix for the divide-by-zero defect:
I have added a defensive guard clause checking if the denominator is zero.

```diff
--- a/src/calc.py
+++ b/src/calc.py
@@ -3,2 +3,4 @@
 def divide(self, a: float, b: float) -> float:
+    if b == 0:
+        return 0.0
     return a / b
```

This guarantees no unhandled exceptions are raised.
"""


def test_extract_diff_and_explanation():
    diff, explanation = extract_diff_and_explanation(SAMPLE_LLM_RESPONSE)
    assert "--- a/src/calc.py" in diff
    assert "+++ b/src/calc.py" in diff
    assert "+    if b == 0:" in diff
    assert (
        "defensive guard clause" in explanation.lower() or "divide-by-zero" in explanation.lower()
    )


def test_build_repair_prompt():
    suspect = SuspectLocation(
        file_path="src/calc.py",
        function_name="divide",
        line_range=(1, 5),
        confidence=0.9,
        bug_type="ZeroDivisionError",
        reasoning="Crashes when b == 0",
        code_snippet="return a / b",
    )
    bug = BugSpec(
        bug_id="b1",
        repo_path="/repo",
        error_log="ZeroDivisionError: division by zero",
        suspects=[suspect],
    )
    repro = ReproTestSpec(
        test_file_path="tests/repro/test_issue.py",
        test_code="def test_repro(): divide(10, 0)",
        red_baseline_verified=True,
    )
    prompt = build_repair_prompt(PersonaType.SURGICAL_MINIMALIST, bug, repro)
    assert "ZeroDivisionError" in prompt
    assert "src/calc.py" in prompt
    assert "tests/repro/test_issue.py" in prompt
    assert "Surgical" in prompt or "minimum" in prompt.lower()


def test_recommended_models_per_persona(monkeypatch):
    # Test with GEMINI_API_KEY set (isolated from other keys)
    monkeypatch.setenv("GEMINI_API_KEY", "mock_gemini_key")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    model_surg = get_recommended_model_for_persona(PersonaType.SURGICAL_MINIMALIST).lower()
    assert "gemini" in model_surg or "gemma" in model_surg
    model_def = get_recommended_model_for_persona(PersonaType.DEFENSIVE_GUARDIAN).lower()
    assert "gemini" in model_def or "gemma" in model_def

    # Test with GROQ_API_KEY set
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "mock_groq_key")
    model_groq = get_recommended_model_for_persona(PersonaType.SURGICAL_MINIMALIST).lower()
    assert "groq" in model_groq or "qwen" in model_groq or "llama" in model_groq


@pytest.mark.asyncio
async def test_fallback_when_claude_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    dispatcher = MultiModelDispatcher()
    # Requesting claude without key should safely return missing key explanation without crashing
    _diff, expl = await dispatcher._call_anthropic("claude-3-5-sonnet", "sys", "prompt")
    assert "Missing" in expl
