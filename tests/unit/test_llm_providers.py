from bugarena.models.agent import PersonaType
from bugarena.models.bug import BugSpec, SuspectLocation
from bugarena.models.repro import ReproTestSpec
from bugarena.tournament.providers.dispatcher import (
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


def test_recommended_models_per_persona():
    assert "claude" in get_recommended_model_for_persona(PersonaType.SURGICAL_MINIMALIST).lower()
    assert "gemini" in get_recommended_model_for_persona(PersonaType.DEFENSIVE_GUARDIAN).lower()
    assert (
        "o3" in get_recommended_model_for_persona(PersonaType.ARCHITECTURAL_FIXER).lower()
        or "gpt" in get_recommended_model_for_persona(PersonaType.ARCHITECTURAL_FIXER).lower()
    )
    assert "deepseek" in get_recommended_model_for_persona(PersonaType.CONTRACT_ENFORCER).lower()
