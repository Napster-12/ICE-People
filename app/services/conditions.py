"""Tiny, safe expression language for routing-rule conditions.

Examples HR Admin can type:
    headcount_type == "New" or is_over_budget
    grade >= 8
    is_executive
    employment_type in ["Contract", "Casual"] and ctc > 500000
An empty condition (or "all") always matches. Only names, literals, comparisons,
and/or/not and lists are allowed: no calls, attributes or indexing.
"""
import ast
import operator

_COMPARE = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
    ast.Gt: operator.gt, ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}
_ALLOWED = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.Compare, ast.Name,
            ast.Load, ast.Constant, ast.List, ast.Tuple) + tuple(_COMPARE)


class ConditionError(ValueError):
    pass


def parse(text):
    text = (text or "").strip()
    if not text or text.lower() == "all":
        return None
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ConditionError(f"Condition isn't valid: {exc.msg}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ConditionError(f"'{type(node).__name__}' isn't allowed in a condition.")
    return tree


def _eval(node, ctx):
    if isinstance(node, ast.Expression):
        return _eval(node.body, ctx)
    if isinstance(node, ast.BoolOp):
        values = (_eval(v, ctx) for v in node.values)
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.UnaryOp):
        return not _eval(node.operand, ctx)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, ctx)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, ctx)
            try:
                if not _COMPARE[type(op)](left, right):
                    return False
            except TypeError:
                return False
            left = right
        return True
    if isinstance(node, ast.Name):
        if node.id in ("True", "False", "None"):
            return {"True": True, "False": False, "None": None}[node.id]
        if node.id not in ctx:
            raise ConditionError(f"Unknown field '{node.id}'.")
        return ctx[node.id]
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(e, ctx) for e in node.elts]
    raise ConditionError("Unsupported expression.")


def evaluate(text, ctx):
    tree = parse(text)
    return True if tree is None else bool(_eval(tree, ctx))


def validate(text, sample_ctx):
    """Raise ConditionError if the condition is malformed or uses unknown fields."""
    evaluate(text, sample_ctx)
