from pathlib import Path

from bugarena.server import bugarena_autonomous_repair

BUGGY_CALC_CODE = """
class Calculator:
    def divide(self, a: float, b: float) -> float:
        return a / b

    def add(self, a: float, b: float) -> float:
        return a + b
"""

REGRESSION_TEST_CODE = """
from src.calc import Calculator

def test_add():
    c = Calculator()
    assert c.add(2, 3) == 5.0
"""

SAMPLE_CRASH_LOG = """
Traceback (most recent call last):
  File "src/calc.py", line 4, in divide
    return a / b
ZeroDivisionError: division by zero
"""

# Candidate 1: Surgical Minimalist (Adds clean zero check)
CANDIDATE_SURGICAL = {
    "candidate_id": "cand_surgical_01",
    "persona": "surgical_minimalist",
    "explanation": "Added zero check before division",
    "diff": """--- a/src/calc.py
+++ b/src/calc.py
@@ -3,2 +3,4 @@
     def divide(self, a: float, b: float) -> float:
+        if b == 0:
+            return 0.0
         return a / b
""",
}

# Candidate 2: Flawed patch that breaks 'add' method (introduces regression)
CANDIDATE_REGRESSIVE = {
    "candidate_id": "cand_regressive_02",
    "persona": "architectural_fixer",
    "explanation": "Refactored calculator but broke add method",
    "diff": """--- a/src/calc.py
+++ b/src/calc.py
@@ -3,5 +3,5 @@
     def divide(self, a: float, b: float) -> float:
+        if b == 0:
+            return 0.0
         return a / b
-    def add(self, a: float, b: float) -> float:
-        return a + b
+    def add(self, a: float, b: float) -> float:
+        return a * b
""",
}


def test_end_to_end_autonomous_repair_flow(tmp_path):
    # Setup mock repository with src and tests
    repo = tmp_path / "calc_project"
    src_dir = repo / "src"
    tests_dir = repo / "tests"
    src_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)

    (src_dir / "calc.py").write_text(BUGGY_CALC_CODE)
    (tests_dir / "test_calc.py").write_text(REGRESSION_TEST_CODE)

    # Run composite autonomous repair workflow
    result = bugarena_autonomous_repair(
        repo_path=str(repo),
        error_log=SAMPLE_CRASH_LOG,
        bug_description="divide(10, 0) raises ZeroDivisionError instead of returning 0.0",
        call_expr="Calculator().divide(10, 0)",
        expected_behavior="Calculator().divide(10, 0) == 0.0",
        candidate_patches_raw=[CANDIDATE_SURGICAL, CANDIDATE_REGRESSIVE],
    )

    # 1. Verify tournament was assigned
    assert "tournament_id" in result
    assert result["champion_candidate_id"] == "cand_surgical_01"

    # 2. Check leaderboard details
    leaderboard = result["leaderboard"]
    assert len(leaderboard) == 2

    surg_eval = next(e for e in leaderboard if e["candidate_id"] == "cand_surgical_01")
    regr_eval = next(e for e in leaderboard if e["candidate_id"] == "cand_regressive_02")

    # Surgical passed repro and had zero regressions -> Approved with high score
    assert surg_eval["repro_passed"] is True
    assert surg_eval["regressions_count"] == 0
    assert surg_eval["disqualified"] is False
    assert surg_eval["score"] > 90.0

    # Regressive introduced regression in existing test suite -> Disqualified!
    assert regr_eval["disqualified"] is True
    assert regr_eval["score"] == 0.0

    # 3. Check report markdown
    report = result["report_markdown"]
    assert "Winning Champion Patch" in report
    assert "cand_surgical_01" in report
    assert "git apply" in report
    assert "cand_regressive_02" in report
    assert "DISQUALIFIED" in report

    # 4. Verify that an .md report file was generated and saved to disk
    assert "report_file_path" in result
    report_file = Path(result["report_file_path"])
    assert report_file.is_file()
    saved_md = report_file.read_text(encoding="utf-8")
    assert "divide(10, 0) raises ZeroDivisionError instead of returning 0.0" in saved_md
    assert "cand_surgical_01" in saved_md
    assert "Winning Champion Patch" in saved_md
