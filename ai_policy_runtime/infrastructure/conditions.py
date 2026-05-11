from __future__ import annotations

import ast
import re
from typing import Any


class ConditionError(ValueError):
    pass


def evaluate_condition(expression: str | None, context: dict[str, Any]) -> bool:
    if not expression:
        return True
    normalized = _normalize(expression)
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise ConditionError(f"Invalid condition expression: {expression}") from exc
    return bool(_eval_node(tree.body, context))


def _normalize(expression: str) -> str:
    expression = re.sub(r"\btrue\b", "True", expression, flags=re.IGNORECASE)
    expression = re.sub(r"\bfalse\b", "False", expression, flags=re.IGNORECASE)
    return expression


def _eval_node(node: ast.AST, context: dict[str, Any]) -> Any:
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(value, context) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not bool(_eval_node(node.operand, context))
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, context)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, context)
            if not _compare(left, op, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Name):
        if node.id in context:
            return context[node.id]
        raise ConditionError(f"Unknown condition identifier: {node.id}")
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_eval_node(item, context) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(item, context) for item in node.elts)
    raise ConditionError(f"Unsupported condition expression: {ast.dump(node)}")


def _compare(left: Any, op: ast.cmpop, right: Any) -> bool:
    if isinstance(op, ast.Eq):
        return left == right
    if isinstance(op, ast.NotEq):
        return left != right
    if isinstance(op, ast.Gt):
        return left > right
    if isinstance(op, ast.GtE):
        return left >= right
    if isinstance(op, ast.Lt):
        return left < right
    if isinstance(op, ast.LtE):
        return left <= right
    if isinstance(op, ast.In):
        return left in right
    if isinstance(op, ast.NotIn):
        return left not in right
    raise ConditionError(f"Unsupported comparison operator: {type(op).__name__}")
