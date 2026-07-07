"""Tests for MySqlQueryExecutor."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "apps" / "api_server" / "src",
):
    sys.path.insert(0, str(_p))

from agent_os_contracts import QueryPlan  # noqa: E402
from agent_os_api.mysql_executor import MySqlQueryExecutor  # noqa: E402


class MySqlQueryExecutorTest(unittest.TestCase):
    def test_rejects_insert(self) -> None:
        mock_engine = MagicMock()
        executor = MySqlQueryExecutor(engine=mock_engine)
        with self.assertRaises(ValueError):
            executor.execute(
                QueryPlan(metric_name="gmv", sql="INSERT INTO t VALUES (1)", parameters={})
            )

    def test_rejects_non_select(self) -> None:
        mock_engine = MagicMock()
        executor = MySqlQueryExecutor(engine=mock_engine)
        with self.assertRaises(ValueError):
            executor.execute(QueryPlan(metric_name="gmv", sql="SHOW TABLES", parameters={}))

    def test_executes_select_and_maps_rows(self) -> None:
        mock_engine = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.keys.return_value = ["order_date", "value"]
        mock_cursor.fetchall.return_value = [("2026-05-31", 100.0)]
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_cursor
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        executor = MySqlQueryExecutor(engine=mock_engine)
        result = executor.execute(
            QueryPlan(
                metric_name="gmv",
                sql="SELECT order_date, value FROM sales.orders",
                parameters={"start_date": "2026-05-25"},
            )
        )

        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.rows[0], {"order_date": "2026-05-31", "value": 100.0})

    def test_connection_error_returns_empty(self) -> None:
        from sqlalchemy.exc import OperationalError

        mock_engine = MagicMock()
        mock_engine.connect.side_effect = OperationalError("conn failed", {}, None)

        executor = MySqlQueryExecutor(engine=mock_engine)
        result = executor.execute(QueryPlan(metric_name="gmv", sql="SELECT 1", parameters={}))
        self.assertEqual(result.row_count, 0)


if __name__ == "__main__":
    unittest.main()
