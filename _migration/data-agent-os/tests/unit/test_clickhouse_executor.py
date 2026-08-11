"""Tests for ClickHouseQueryExecutor."""

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
from agent_os_api.clickhouse_executor import ClickHouseQueryExecutor  # noqa: E402


class _MockResult:
    def __init__(self, rows: list[tuple], columns: tuple[str, ...]) -> None:
        self.result_rows = rows
        self.column_names = columns


class ClickHouseQueryExecutorTest(unittest.TestCase):
    def test_rejects_insert(self) -> None:
        mock_client = MagicMock()
        executor = ClickHouseQueryExecutor(client=mock_client)
        with self.assertRaises(ValueError):
            executor.execute(
                QueryPlan(metric_name="gmv", sql="INSERT INTO t VALUES (1)", parameters={})
            )

    def test_executes_select_and_maps_rows(self) -> None:
        mock_client = MagicMock()
        mock_client.query.return_value = _MockResult(
            rows=[("2026-05-31", 100.0)],
            columns=("order_date", "value"),
        )
        executor = ClickHouseQueryExecutor(client=mock_client)
        result = executor.execute(
            QueryPlan(
                metric_name="gmv",
                sql="SELECT order_date, value FROM sales.orders",
                parameters={"start_date": "2026-05-25"},
            )
        )
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.rows[0], {"order_date": "2026-05-31", "value": 100.0})

    def test_query_error_returns_empty(self) -> None:
        mock_client = MagicMock()
        mock_client.query.side_effect = Exception("network")
        executor = ClickHouseQueryExecutor(client=mock_client)
        result = executor.execute(QueryPlan(metric_name="gmv", sql="SELECT 1", parameters={}))
        self.assertEqual(result.row_count, 0)


if __name__ == "__main__":
    unittest.main()
