"""safe_expr tests — the open-vocabulary verifier organ must EVALUATE legitimate compositional forms and
FAIL CLOSED on anything unsafe (no code execution from a proposer's string, ever)."""
from __future__ import annotations

import math
import unittest

from aac.safe_expr import compile_expr, UnsafeExpression


class Evaluates(unittest.TestCase):
    def test_composed_form(self):
        f = compile_expr("tanh(2*x2*x5) * step(x8 - 0.3)", 12)
        row = [0.0] * 12
        row[2], row[5], row[8] = 1.0, 1.0, 1.0
        self.assertAlmostEqual(f(row), math.tanh(2.0), places=6)     # step(0.7)=1
        row[8] = 0.0
        self.assertEqual(f(row), 0.0)                                # step(-0.3)=0

    def test_arithmetic_and_funcs(self):
        f = compile_expr("abs(x0 - x1) + max(x2, 0)", 3)
        self.assertEqual(f([1.0, 4.0, -2.0]), 3.0)

    def test_ifexp_and_compare(self):
        f = compile_expr("x0 if x1 > 0 else -x0", 2)
        self.assertEqual(f([5.0, 1.0]), 5.0)
        self.assertEqual(f([5.0, -1.0]), -5.0)

    def test_divzero_failsafe_to_zero(self):
        f = compile_expr("x0 / x1", 2)
        self.assertEqual(f([1.0, 0.0]), 0.0)


class FailsClosed(unittest.TestCase):
    def test_import_rejected(self):
        with self.assertRaises(UnsafeExpression):
            compile_expr("__import__('os')", 2)

    def test_attribute_access_rejected(self):
        with self.assertRaises(UnsafeExpression):
            compile_expr("x0.__class__", 2)

    def test_unknown_call_rejected(self):
        with self.assertRaises(UnsafeExpression):
            compile_expr("eval('1')", 2)

    def test_unknown_name_rejected(self):
        with self.assertRaises(UnsafeExpression):
            compile_expr("secret + x0", 2)

    def test_out_of_range_feature_rejected(self):
        with self.assertRaises(UnsafeExpression):
            compile_expr("x99", 3)

    def test_no_builtins_reachable(self):
        # even if a name slipped through, builtins are stripped at eval time
        with self.assertRaises(UnsafeExpression):
            compile_expr("open('/etc/passwd')", 2)

    def test_overlong_rejected(self):
        with self.assertRaises(UnsafeExpression):
            compile_expr("x0+" * 100 + "x0", 2)


if __name__ == "__main__":
    unittest.main()
