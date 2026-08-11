"""Red-team suite for the AST-based SQL safety gate.

Every test here asserts that a known bypass pattern is rejected.  If the
implementation ignores parser output, returns a constant, or skips SQL Safety,
these tests fail.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_core.sql_safety import SQLSafetyChecker  # noqa: E402


class SQLSafetyRedTeamTest(unittest.TestCase):
    """Attack patterns that must be blocked by the SQL safety gate."""

    def setUp(self) -> None:
        self.checker = SQLSafetyChecker(("sales",), max_limit=1000)

    def _assert_blocked(
        self, sql: str, required: tuple[str, ...], params: dict | None = None
    ) -> None:
        result = self.checker.check(sql, required, params, required_time_parameters=("start_date",))
        self.assertFalse(result.allowed, f"Expected block for: {sql}\nGot: {result.reasons}")

    # Category 1: multi-statement injection ----------------------------------
    def test_blocks_semicolon_separated_write(self) -> None:
        self._assert_blocked(
            "select amount from sales.orders where order_date >= :start_date limit :limit; "
            "delete from sales.orders",
            ("start_date", "limit"),
            {"start_date": "2026-01-01", "limit": 10},
        )

    # Category 2: line comment hiding additional predicates -------------------
    def test_blocks_line_comment_bypass(self) -> None:
        self._assert_blocked(
            "select amount from sales.orders -- pretend predicate\n"
            "where order_date >= :start_date limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-01-01", "limit": 10},
        )

    # Category 3: block comment hiding table reference ------------------------
    def test_blocks_block_comment_bypass(self) -> None:
        self._assert_blocked(
            "select amount from sales.orders /* hidden */ where order_date >= :start_date limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-01-01", "limit": 10},
        )

    # Category 4: UNION injection --------------------------------------------
    def test_blocks_union_injection(self) -> None:
        self._assert_blocked(
            "select amount from sales.orders where order_date >= :start_date "
            "union select password_hash from sales.users limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-01-01", "limit": 10},
        )

    # Category 5: SELECT-star with DISTINCT disguise --------------------------
    def test_blocks_select_star_distinct_disguise(self) -> None:
        self._assert_blocked(
            "select distinct * from sales.orders where order_date >= :start_date limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-01-01", "limit": 10},
        )

    # Category 6: SELECT-star with qualified alias ----------------------------
    def test_blocks_qualified_star(self) -> None:
        self._assert_blocked(
            "select o.* from sales.orders o where order_date >= :start_date limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-01-01", "limit": 10},
        )

    # Category 7: non-allowlisted schema --------------------------------------
    def test_blocks_cross_schema_reference(self) -> None:
        self._assert_blocked(
            "select amount from finance.payments where paid_at >= :start_date limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-01-01", "limit": 10},
        )

    # Category 8: unqualified table reference ---------------------------------
    def test_blocks_unqualified_table(self) -> None:
        self._assert_blocked(
            "select amount from orders where order_date >= :start_date limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-01-01", "limit": 10},
        )

    # Category 9: string concatenation / unbound parameter --------------------
    def test_blocks_unbound_user_input(self) -> None:
        self._assert_blocked(
            "select amount from sales.orders where order_date >= '2026-01-01' limit :limit",
            ("limit",),
            {"limit": 10},
        )

    # Category 10: LIMIT bypass via oversized value ---------------------------
    def test_blocks_oversized_limit(self) -> None:
        self._assert_blocked(
            "select amount from sales.orders where order_date >= :start_date limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-01-01", "limit": 100_000},
        )

    # Category 11: LIMIT bypass via negative literal --------------------------
    def test_blocks_negative_literal_limit(self) -> None:
        self._assert_blocked(
            "select amount from sales.orders where order_date >= :start_date limit -1",
            ("start_date",),
            {"start_date": "2026-01-01"},
        )

    # Category 12: nested subquery too deep -----------------------------------
    def test_blocks_deeply_nested_subquery(self) -> None:
        self._assert_blocked(
            "select a from ("
            "  select b from ("
            "    select c from ("
            "      select d from sales.orders"
            "    ) t3"
            "  ) t2"
            ") t1 "
            "where order_date >= :start_date limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-01-01", "limit": 10},
        )

    # Category 13: DDL hidden after SELECT ------------------------------------
    def test_blocks_write_statement_root(self) -> None:
        self._assert_blocked(
            "delete from sales.orders where order_date >= :start_date limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-01-01", "limit": 10},
        )

    # Category 14: missing explicit LIMIT -------------------------------------
    def test_blocks_missing_limit(self) -> None:
        self._assert_blocked(
            "select amount from sales.orders where order_date >= :start_date",
            ("start_date",),
            {"start_date": "2026-01-01"},
        )


if __name__ == "__main__":
    unittest.main()
