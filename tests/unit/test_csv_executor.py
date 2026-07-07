"""Tests for CsvQueryExecutor."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import QueryPlan  # noqa: E402
from agent_os_core.query_runtime import CsvQueryExecutor  # noqa: E402


class CsvQueryExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
        self._tmp.write("order_date,paid_amount\n")
        self._tmp.write("2026-05-31,100.0\n")
        self._tmp.write("2026-06-01,200.0\n")
        self._tmp.close()
        self._path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._path.unlink(missing_ok=True)

    def test_execute_filters_rows_by_parameters(self) -> None:
        executor = CsvQueryExecutor(self._path)
        result = executor.execute(
            QueryPlan(
                metric_name="gmv",
                sql="SELECT order_date, paid_amount FROM sales.orders",
                parameters={"order_date": "2026-05-31"},
            )
        )
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.rows[0]["order_date"], "2026-05-31")
        self.assertEqual(result.rows[0]["paid_amount"], "100.0")

    def test_execute_returns_all_rows_when_no_matching_parameters(self) -> None:
        executor = CsvQueryExecutor(self._path)
        result = executor.execute(
            QueryPlan(
                metric_name="gmv",
                sql="SELECT order_date, paid_amount FROM sales.orders",
                parameters={"limit": 100},
            )
        )
        self.assertEqual(result.row_count, 2)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            CsvQueryExecutor("/nonexistent/data.csv")


if __name__ == "__main__":
    unittest.main()
