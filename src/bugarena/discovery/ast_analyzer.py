"""AST analysis utilities to extract code context, scopes, and slices."""

import ast
from typing import TypedDict


class ASTSliceInfo(TypedDict):
    function_name: str
    class_name: str | None
    line_range: tuple[int, int]
    code_snippet: str
    docstring: str | None


def locate_faulty_ast_slice(
    file_content: str, target_line: int, function_name: str | None = None
) -> ASTSliceInfo | None:
    """
    Locate the enclosing function/class AST slice containing target_line,
    with fallback to matching function_name if line is out of range or shifted.
    """
    if not file_content or not file_content.splitlines():
        return None

    try:
        tree = ast.parse(file_content)
    except SyntaxError:
        return None

    lines = file_content.splitlines()

    class FaultVisitor(ast.NodeVisitor):
        def __init__(self, target: int, target_func: str | None):
            self.target = target
            self.target_func = target_func
            self.current_class: str | None = None
            self.line_hit: tuple[ast.FunctionDef | ast.AsyncFunctionDef, str | None, str | None] | None = None
            self.name_hit: tuple[ast.FunctionDef | ast.AsyncFunctionDef, str | None, str | None] | None = None

        def visit_ClassDef(self, node: ast.ClassDef):
            prev_class = self.current_class
            self.current_class = node.name
            self.generic_visit(node)
            self.current_class = prev_class

        def visit_FunctionDef(self, node: ast.FunctionDef):
            self._check_func(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            self._check_func(node)

        def _check_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
            end_lineno = getattr(node, "end_lineno", node.lineno)
            doc = ast.get_docstring(node)
            if node.lineno <= self.target <= end_lineno:
                self.line_hit = (node, self.current_class, doc)
            if self.target_func and node.name == self.target_func and self.name_hit is None:
                self.name_hit = (node, self.current_class, doc)
            self.generic_visit(node)

    visitor = FaultVisitor(target_line, function_name)
    visitor.visit(tree)

    chosen = visitor.line_hit or visitor.name_hit
    if chosen:
        node, cls_name, doc = chosen
        start = node.lineno
        end = getattr(node, "end_lineno", start)
        snippet = "\n".join(lines[start - 1 : end])
        return ASTSliceInfo(
            function_name=node.name,
            class_name=cls_name,
            line_range=(start, end),
            code_snippet=snippet,
            docstring=doc,
        )

    # Line outside functions (top-level module code)
    start = max(1, min(target_line - 5, len(lines)))
    end = min(len(lines), max(start, target_line + 5))
    snippet = "\n".join(lines[start - 1 : end])
    return ASTSliceInfo(
        function_name="<module>",
        class_name=None,
        line_range=(start, end),
        code_snippet=snippet,
        docstring=None,
    )
