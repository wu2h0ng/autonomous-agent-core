"""safe_expr — pure-stdlib safe evaluator for open-vocabulary structure proposals (5e-2 verifier organ).

The LLM-proposes / CWM-verifies frontier route needs to turn an LLM's arbitrary FUNCTIONAL-FORM proposal
(a string like 'tanh(2*x2*x5) * step(x8-0.3)') into a numeric feature over a data row, SAFELY: no imports,
no attribute access, no arbitrary calls, no names except the whitelisted feature vars and math funcs. Parse
with ast, whitelist the node types, evaluate against a row. A malformed / unsafe / unknown-symbol proposal
raises UnsafeExpression (fail-closed) — the proposer's output NEVER executes arbitrary code (governance:
the LLM proposes, a bounded evaluator disposes)."""
from __future__ import annotations

import ast
import math

MATH = {
    "tanh": math.tanh, "abs": abs, "min": min, "max": max, "sign": lambda x: (x > 0) - (x < 0),
    "step": lambda x: 1.0 if x > 0 else 0.0, "relu": lambda x: x if x > 0 else 0.0,
    "sqrt": lambda x: math.sqrt(abs(x)), "exp": lambda x: math.exp(max(-30.0, min(30.0, x))),
    "log1p": lambda x: math.log1p(abs(x)),
}
_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd,
    ast.Compare, ast.Gt, ast.Lt, ast.GtE, ast.LtE, ast.IfExp,
)


class UnsafeExpression(ValueError):
    """The proposed expression uses a construct/symbol outside the whitelist (fail-closed)."""


def _check(node, n_features):
    if not isinstance(node, _ALLOWED_NODES):
        raise UnsafeExpression(f"disallowed node {type(node).__name__}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in MATH:
            raise UnsafeExpression(f"disallowed call {getattr(node.func, 'id', '?')}")
        if node.keywords:
            raise UnsafeExpression("keyword args not allowed")
    if isinstance(node, ast.Name):
        if node.id in MATH:
            return
        if not (node.id.startswith("x") and node.id[1:].isdigit() and int(node.id[1:]) < n_features):
            raise UnsafeExpression(f"unknown name {node.id}")
    for child in ast.iter_child_nodes(node):
        _check(child, n_features)


def compile_expr(expr: str, n_features: int):
    """Parse+validate an open-vocabulary expression. Returns a feature function row->float, or raises
    UnsafeExpression. Depth/length bounded to keep proposals cheap and the space finite-per-proposal."""
    if len(expr) > 200:
        raise UnsafeExpression("expression too long")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise UnsafeExpression(f"syntax error: {e}") from e
    _check(tree, n_features)
    code = compile(tree, "<expr>", "eval")

    def feat(row):
        env = {name: fn for name, fn in MATH.items()}
        env.update({f"x{i}": row[i] for i in range(len(row))})
        try:
            v = eval(code, {"__builtins__": {}}, env)   # sandboxed: no builtins, whitelisted names only
        except (ZeroDivisionError, ValueError, OverflowError):
            return 0.0
        return float(v) if isinstance(v, (int, float, bool)) else 0.0

    return feat
