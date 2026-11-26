"""AST complexity and code churn calculation metrics."""

import ast


def compute_churn_score(lines_changed: int) -> float:
    """
    Compute normalized churn penalty score in [0.0, 1.0].
    Penalizes unnecessary churn (50 lines changed = 0.0).
    """
    if lines_changed <= 0:
        return 1.0
    return max(0.0, round(1.0 - (lines_changed / 50.0), 4))


def compute_complexity_score(cyclomatic_delta: int) -> float:
    """
    Compute normalized cyclomatic complexity score in [0.0, 1.0].
    Penalizes increase in cyclomatic complexity (+10 = 0.0).
    """
    if cyclomatic_delta <= 0:
        return 1.0
    return max(0.0, round(1.0 - (cyclomatic_delta / 10.0), 4))


def _count_ast_branches(code: str) -> int:
    """Count branching points in Python code using AST; raise ValueError on SyntaxError."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"SyntaxError in AST branch count: {exc}") from exc

    complexity = 1
    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.If, ast.While, ast.For, ast.AsyncFor, ast.ExceptHandler, ast.With, ast.AsyncWith),
        ):
            complexity += 1
        elif isinstance(node, ast.BoolOp):
            complexity += len(node.values) - 1
        elif isinstance(node, ast.IfExp):
            complexity += 1
    return complexity


def calculate_cyclomatic_delta(original_code: str, patched_code: str) -> int:
    """
    Calculate change in Cyclomatic Complexity between original and patched code.
    Raises ValueError on SyntaxError so broken code cannot appear simplified.
    """
    try:
        from radon.complexity import cc_visit

        orig_cc = sum(block.complexity for block in cc_visit(original_code))
        patch_cc = sum(block.complexity for block in cc_visit(patched_code))
        return patch_cc - orig_cc
    except SyntaxError as exc:
        raise ValueError(f"SyntaxError while computing cyclomatic delta: {exc}") from exc
    except (ImportError, AttributeError):
        return _count_ast_branches(patched_code) - _count_ast_branches(original_code)
