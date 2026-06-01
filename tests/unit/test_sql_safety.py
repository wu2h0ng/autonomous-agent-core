from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_core.sql_safety import SQLSafetyChecker


class SQLSafetyCheckerTest(unittest.TestCase):
    def test_allows_readonly_allowlisted_parameterized_sql(self) -> None:
        checker = SQLSafetyChecker(("sales",))

        result = checker.check(
            """
            select order_date, sum(paid_amount) as gmv
            from sales.orders
            where order_date >= :start_date and order_date < :end_date
            group by order_date
            limit :limit
            """,
            ("start_date", "end_date", "limit"),
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        self.assertTrue(result.allowed)
        self.assertEqual(result.reasons, ())
        self.assertEqual(result.checked_schemas, ("sales",))
        self.assertEqual(result.checked_tables, ("sales.orders",))
        self.assertEqual(result.bound_parameters, ("end_date", "limit", "start_date"))
        self.assertEqual(result.limit_value, 100)

    def test_blocks_write_sql(self) -> None:
        checker = SQLSafetyChecker(("sales",))

        result = checker.check("delete from sales.orders where id = :id limit :limit", ("id",))

        self.assertFalse(result.allowed)
        self.assertIn("Only SELECT statements are allowed.", result.reasons)
        self.assertIn("Write or DDL statements are forbidden.", result.reasons)
        self.assertIn("NO_WRITE_OR_DDL", {issue.code for issue in result.issues})

    def test_blocks_non_allowlisted_schema(self) -> None:
        checker = SQLSafetyChecker(("sales",))

        result = checker.check(
            "select amount from finance.payments where paid_at >= :start_date limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-05-25", "limit": 100},
            required_time_parameters=("start_date",),
        )

        self.assertFalse(result.allowed)
        self.assertIn("SCHEMA_ALLOWLIST", {issue.code for issue in result.issues})

    def test_blocks_unqualified_table_reference(self) -> None:
        checker = SQLSafetyChecker(("sales",))

        result = checker.check(
            "select amount from orders where order_date >= :start_date limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-05-25", "limit": 100},
            required_time_parameters=("start_date",),
        )

        self.assertFalse(result.allowed)
        self.assertIn("SCHEMA_QUALIFIED_TABLE", {issue.code for issue in result.issues})

    def test_blocks_missing_limit(self) -> None:
        checker = SQLSafetyChecker(("sales",))

        result = checker.check(
            "select amount from sales.orders where order_date >= :start_date",
            ("start_date",),
            {"start_date": "2026-05-25"},
            required_time_parameters=("start_date",),
        )

        self.assertFalse(result.allowed)
        self.assertIn("MISSING_LIMIT", {issue.code for issue in result.issues})

    def test_blocks_limit_above_policy(self) -> None:
        checker = SQLSafetyChecker(("sales",), max_limit=500)

        result = checker.check(
            "select amount from sales.orders where order_date >= :start_date limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-05-25", "limit": 1000},
            required_time_parameters=("start_date",),
        )

        self.assertFalse(result.allowed)
        self.assertIn("LIMIT_TOO_HIGH", {issue.code for issue in result.issues})

    def test_blocks_missing_runtime_parameter(self) -> None:
        checker = SQLSafetyChecker(("sales",))

        result = checker.check(
            "select amount from sales.orders where order_date >= :start_date limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-05-25"},
            required_time_parameters=("start_date",),
        )

        self.assertFalse(result.allowed)
        self.assertIn("MISSING_RUNTIME_PARAMETER", {issue.code for issue in result.issues})

    def test_blocks_multiple_statements(self) -> None:
        checker = SQLSafetyChecker(("sales",))

        result = checker.check(
            "select amount from sales.orders where order_date >= :start_date limit :limit; select 1",
            ("start_date", "limit"),
            {"start_date": "2026-05-25", "limit": 100},
            required_time_parameters=("start_date",),
        )

        self.assertFalse(result.allowed)
        self.assertIn("SINGLE_STATEMENT", {issue.code for issue in result.issues})

    def test_blocks_sql_comments(self) -> None:
        checker = SQLSafetyChecker(("sales",))

        result = checker.check(
            "select amount from sales.orders -- hidden predicate\nwhere order_date >= :start_date limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-05-25", "limit": 100},
            required_time_parameters=("start_date",),
        )

        self.assertFalse(result.allowed)
        self.assertIn("NO_SQL_COMMENTS", {issue.code for issue in result.issues})

    def test_blocks_select_star(self) -> None:
        checker = SQLSafetyChecker(("sales",))

        result = checker.check(
            "select * from sales.orders where order_date >= :start_date limit :limit",
            ("start_date", "limit"),
            {"start_date": "2026-05-25", "limit": 100},
            required_time_parameters=("start_date",),
        )

        self.assertFalse(result.allowed)
        self.assertIn("NO_SELECT_STAR", {issue.code for issue in result.issues})


if __name__ == "__main__":
    unittest.main()
