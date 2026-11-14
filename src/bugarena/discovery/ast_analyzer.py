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
            self.matched_class: str | None = None
            self.matched_function: str | None = None
            self.matched_node: ast.AST | None = None
            self.matched_docstring: str | None = None
            self.name_matched_node: ast.AST | None = None
            self.name_matched_class: str | None = None
            self.name_matched_docstring: str | None = None

        def visit_ClassDef(self, node: ast.ClassDef):
            prev_class = self.current_class
            self.current_class = node.name
            end_lineno = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= self.target <= end_lineno:
                self.matched_class = node.name
            self.generic_visit(node)
            self.current_class = prev_class

        def visit_FunctionDef(self, node: ast.FunctionDef):
            self._check_func(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            self._check_func(node)

        def _check_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
            end_lineno = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= self.target <= end_lineno:
                self.matched_function = node.name
                self.matched_node = node
                self.matched_class = self.current_class
                self.matched_docstring = ast.get_docstring(node)

            if self.target_func and node.name == self.target_func:
                self.name_matched_node = node
                self.name_matched_class = self.current_class
                self.name_matched_docstring = ast.get_docstring(node)

            self.generic_visit(node)

    visitor = FaultVisitor(target_line, function_name)
    visitor.visit(tree)

    node = visitor.matched_node or visitor.name_matched_node
    if node:
        start = node.lineno
        end = getattr(node, "end_lineno", start)
        snippet = "\n".join(lines[start - 1 : end])
        func_name = getattr(node, "name", visitor.matched_function or "<unknown>")
        cls_name = visitor.matched_class or visitor.name_matched_class
        doc = visitor.matched_docstring or visitor.name_matched_docstring
        return ASTSliceInfo(
            function_name=func_name,
            class_name=cls_name,
            line_range=(start, end),
            code_snippet=snippet,
            docstring=doc,
        )

    # If line is outside functions (e.g. top-level module code)
    start = max(1, min(target_line - 5, len(lines)))
    end = min(len(lines), max(1, target_line + 5))
    snippet = "\n".join(lines[start - 1 : end]) if lines else ""
    return ASTSliceInfo(
        function_name="<module>",
        class_name=None,
        line_range=(start, end),
        code_snippet=snippet,
        docstring=None,
    )
