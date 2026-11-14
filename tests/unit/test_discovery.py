from bugarena.discovery.ast_analyzer import locate_faulty_ast_slice
from bugarena.discovery.engine import BugDiscoveryEngine
from bugarena.discovery.log_parser import parse_python_traceback
from bugarena.models.bug import BugSpec

SAMPLE_TRACEBACK = """
Traceback (most recent call last):
  File "src/math/calculator.py", line 42, in compute_ratio
    result = self.divide(x, y)
             ^^^^^^^^^^^^^^^^^
  File "src/math/calculator.py", line 18, in divide
    return a / b
           ~~^~~
ZeroDivisionError: division by zero
"""

SAMPLE_PYTHON_CODE = """
class Calculator:
    \"\"\"A simple calculator service.\"\"\"
    
    def divide(self, a: float, b: float) -> float:
        \"\"\"Divide a by b.\"\"\"
        return a / b

    def compute_ratio(self, x: float, y: float) -> float:
        return self.divide(x, y)
"""


def test_parse_python_traceback():
    traces = parse_python_traceback(SAMPLE_TRACEBACK)
    assert len(traces) == 2

    # Last frame is the root crash frame
    crash_frame = traces[-1]
    assert crash_frame.file_path == "src/math/calculator.py"
    assert crash_frame.line_number == 18
    assert crash_frame.function_name == "divide"
    assert crash_frame.error_message == "ZeroDivisionError: division by zero"
    assert "return a / b" in crash_frame.code


def test_locate_faulty_ast_slice():
    slice_info = locate_faulty_ast_slice(SAMPLE_PYTHON_CODE, target_line=7)
    assert slice_info is not None
    assert slice_info["function_name"] == "divide"
    assert slice_info["class_name"] == "Calculator"
    assert slice_info["line_range"] == (5, 7)
    assert "return a / b" in slice_info["code_snippet"]


def test_bug_discovery_engine(tmp_path):
    repo = tmp_path / "myrepo"
    calc_file = repo / "src" / "math" / "calculator.py"
    calc_file.parent.mkdir(parents=True)
    calc_file.write_text(SAMPLE_PYTHON_CODE)

    engine = BugDiscoveryEngine(repo_path=repo)
    bug_spec = engine.discover_from_trace(
        error_log=SAMPLE_TRACEBACK, hint="Ratio computation fails when y is 0"
    )

    assert isinstance(bug_spec, BugSpec)
    assert len(bug_spec.traces) == 2
    assert len(bug_spec.suspects) >= 1

    primary_suspect = bug_spec.suspects[0]
    assert primary_suspect.file_path == "src/math/calculator.py"
    assert primary_suspect.function_name == "divide"
    assert primary_suspect.confidence >= 0.8
    assert primary_suspect.bug_type == "ZeroDivisionError"
