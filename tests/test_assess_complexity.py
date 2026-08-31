import ast
from pathlib import Path


def test_assess_line_only_orchestrates_decision_phases() -> None:
    tree = ast.parse(Path("paydaysuper/assess.py").read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_assess_line"
    )
    decisions = sum(
        isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.BoolOp, ast.IfExp))
        for node in ast.walk(function)
    )

    assert function.end_lineno is not None
    assert function.end_lineno - function.lineno < 200
    assert decisions <= 20
