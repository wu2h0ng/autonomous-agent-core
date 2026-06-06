from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import QueryPlan, QueryResult  # noqa: E402
from agent_os_core.query_runtime import SQLiteQueryExecutor  # noqa: E402


def _seed_orders(connection: sqlite3.Connection) -> None:
    """Create a tiny orders table with rows spanning the window boundaries."""
    connection.execute("create table orders (order_date text, paid_amount real)")
    connection.executemany(
        "insert into orders (order_date, paid_amount) values (?, ?)",
        [
            # before the window -> must be excluded
            ("2026-05-24", 999.0),
            # inside the window -> two orders on the same day, must be summed
            ("2026-05-31", 100000.0),
            ("2026-05-31", 28800.0),
            # on end_date (exclusive upper bound) -> must be excluded
            ("2026-06-01", 555.0),
        ],
    )
    connection.commit()


class SQLiteQueryExecutorTest(unittest.TestCase):
    def test_executes_real_aggregation_with_named_parameters(self) -> None:
        """The executor must COMPUTE the aggregate from real rows.

        The expected value (128800.0) is the sum of the two in-window rows.
        A StaticQueryExecutor could not fabricate this from the inputs; only a
        real SQL engine binding :start_date/:end_date/:limit and summing the
        matching rows produces it. This is the regression guard against a fake.
        """
        connection = sqlite3.connect(":memory:")
        _seed_orders(connection)
        executor = SQLiteQueryExecutor(connection)

        plan = QueryPlan(
            metric_name="gmv",
            sql=(
                "select order_date, sum(paid_amount) as value "
                "from orders "
                "where order_date >= :start_date and order_date < :end_date "
                "group by order_date "
                "limit :limit"
            ),
            parameters={
                "start_date": "2026-05-25",
                "end_date": "2026-06-01",
                "limit": 100,
            },
        )

        result = executor.execute(plan)

        self.assertIsInstance(result, QueryResult)
        self.assertEqual(result.row_count, 1)
        self.assertEqual(len(result.rows), 1)
        row = result.rows[0]
        # Real column names must be preserved.
        self.assertEqual(set(row.keys()), {"order_date", "value"})
        self.assertEqual(row["order_date"], "2026-05-31")
        # The summed, computed aggregate — proof of real execution.
        self.assertEqual(row["value"], 128800.0)

    def test_named_parameter_binding_filters_window(self) -> None:
        """Changing only the bound parameters must change the computed result,
        proving parameters are really bound (not ignored)."""
        connection = sqlite3.connect(":memory:")
        _seed_orders(connection)
        executor = SQLiteQueryExecutor(connection)

        sql = (
            "select sum(paid_amount) as value "
            "from orders "
            "where order_date >= :start_date and order_date < :end_date"
        )

        # Wider window that also includes 2026-06-01 (555.0).
        wide = executor.execute(
            QueryPlan(
                metric_name="gmv",
                sql=sql,
                parameters={"start_date": "2026-05-25", "end_date": "2026-06-02"},
            )
        )
        self.assertEqual(wide.rows[0]["value"], 128800.0 + 555.0)

        # Narrow window excludes everything.
        narrow = executor.execute(
            QueryPlan(
                metric_name="gmv",
                sql=sql,
                parameters={"start_date": "2026-05-25", "end_date": "2026-05-26"},
            )
        )
        self.assertIsNone(narrow.rows[0]["value"])

    def test_empty_result_maps_to_zero_row_count(self) -> None:
        """A grouped query matching no rows returns row_count=0 and no rows."""
        connection = sqlite3.connect(":memory:")
        _seed_orders(connection)
        executor = SQLiteQueryExecutor(connection)

        result = executor.execute(
            QueryPlan(
                metric_name="gmv",
                sql=(
                    "select order_date, sum(paid_amount) as value "
                    "from orders "
                    "where order_date >= :start_date and order_date < :end_date "
                    "group by order_date "
                    "limit :limit"
                ),
                parameters={
                    "start_date": "2030-01-01",
                    "end_date": "2030-02-01",
                    "limit": 100,
                },
            )
        )

        self.assertEqual(result.row_count, 0)
        self.assertEqual(result.rows, ())

    def test_can_construct_from_path(self) -> None:
        """The executor may own the connection by accepting a database path."""
        db_path = ROOT / "tests" / "unit" / "_tmp_sqlite_executor.db"
        if db_path.exists():
            db_path.unlink()
        # Seed via a separate connection to the same file.
        seed_conn = sqlite3.connect(str(db_path))
        _seed_orders(seed_conn)
        seed_conn.close()
        try:
            executor = SQLiteQueryExecutor(database=str(db_path))
            result = executor.execute(
                QueryPlan(
                    metric_name="gmv",
                    sql="select sum(paid_amount) as value from orders",
                    parameters={},
                )
            )
            self.assertEqual(result.row_count, 1)
            self.assertEqual(result.rows[0]["value"], 999.0 + 128800.0 + 555.0)
            executor.close()
        finally:
            db_path.unlink(missing_ok=True)

    def test_requires_connection_or_path(self) -> None:
        """Constructing with neither a connection nor a path is a usage error."""
        with self.assertRaises(ValueError):
            SQLiteQueryExecutor()


if __name__ == "__main__":
    unittest.main()
