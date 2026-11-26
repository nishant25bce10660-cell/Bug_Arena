"""Regression test for ECC-034 (BA-015): empty files & matching node class/docstring consistency."""

from bugarena.discovery.ast_analyzer import locate_faulty_ast_slice


def test_ecc_034_empty_file_and_node_metadata_consistency():
    # Empty file must NOT return inverted line_range=(1, 0)
    empty_res = locate_faulty_ast_slice("", 1)
    assert empty_res is None or empty_res["line_range"][0] <= empty_res["line_range"][1]

    # Method inside ClassA matches line, while ClassB defines same method name with different docstring:
    # docstring & class_name MUST belong strictly to the chosen node (ClassA.run), never mixed!
    code = (
        "class ClassA:\n"
        "    def run(self):\n"
        '        """Doc A."""\n'
        "        return 1 / 0\n"
        "\n"
        "class ClassB:\n"
        "    def run(self):\n"
        '        """Doc B."""\n'
        "        return 2\n"
    )
    res = locate_faulty_ast_slice(code, target_line=4, function_name="run")
    assert res is not None
    assert res["class_name"] == "ClassA"
    assert res["docstring"] == "Doc A."
