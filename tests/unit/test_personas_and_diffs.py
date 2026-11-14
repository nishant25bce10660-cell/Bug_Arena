import pytest

from bugarena.models.agent import CandidatePatch, PersonaType
from bugarena.tournament.patch_parser import PatchValidationError, parse_and_validate_patch
from bugarena.tournament.personas.base import get_persona_prompt

SAMPLE_VALID_DIFF = """--- a/src/math/calculator.py
+++ b/src/math/calculator.py
@@ -17,2 +17,4 @@
 def divide(self, a: float, b: float) -> float:
+    if b == 0:
+        raise ValueError("Cannot divide by zero")
     return a / b
"""

SAMPLE_TAMPERING_DIFF = """--- a/tests/repro/test_issue.py
+++ b/tests/repro/test_issue.py
@@ -1,3 +1,3 @@
 def test_reproduction():
-    assert divide(10, 0) == 0.0
+    assert True
"""


def test_persona_prompts():
    surgical = get_persona_prompt(PersonaType.SURGICAL_MINIMALIST)
    assert "minimum number of lines changed" in surgical.lower() or "minimal" in surgical.lower()

    defensive = get_persona_prompt(PersonaType.DEFENSIVE_GUARDIAN)
    assert (
        "preconditions" in defensive.lower()
        or "defensive" in defensive.lower()
        or "guard" in defensive.lower()
    )

    architectural = get_persona_prompt(PersonaType.ARCHITECTURAL_FIXER)
    assert (
        "refactor" in architectural.lower()
        or "architectural" in architectural.lower()
        or "design" in architectural.lower()
    )

    contract = get_persona_prompt(PersonaType.CONTRACT_ENFORCER)
    assert (
        "type" in contract.lower()
        or "contract" in contract.lower()
        or "invariant" in contract.lower()
    )


def test_parse_and_validate_valid_diff():
    patch = parse_and_validate_patch(
        raw_diff=SAMPLE_VALID_DIFF,
        persona=PersonaType.SURGICAL_MINIMALIST,
        explanation="Added zero check guard clause",
        protected_paths=["tests/repro/test_issue.py"],
    )
    assert isinstance(patch, CandidatePatch)
    assert patch.persona == PersonaType.SURGICAL_MINIMALIST
    assert patch.lines_added == 2
    assert patch.lines_deleted == 0
    assert "ValueError" in patch.diff


def test_parse_and_validate_rejects_test_tampering():
    with pytest.raises(PatchValidationError, match="Patch modifies protected test file"):
        parse_and_validate_patch(
            raw_diff=SAMPLE_TAMPERING_DIFF,
            persona=PersonaType.SURGICAL_MINIMALIST,
            explanation="Cheating fix",
            protected_paths=["tests/repro/test_issue.py"],
        )


def test_parse_and_validate_rejects_malformed_diff():
    with pytest.raises(PatchValidationError, match="Invalid diff header"):
        parse_and_validate_patch(
            raw_diff="This is not a git unified diff",
            persona=PersonaType.DEFENSIVE_GUARDIAN,
            explanation="No diff",
        )
