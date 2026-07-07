"""Tests for FeishuQueryExecutor."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "apps" / "api_server" / "src",
):
    sys.path.insert(0, str(_p))

from agent_os_contracts import QueryPlan  # noqa: E402
from agent_os_api.feishu_executor import FeishuQueryExecutor  # noqa: E402


class FeishuQueryExecutorTest(unittest.TestCase):
    def test_rejects_insert(self) -> None:
        executor = FeishuQueryExecutor(app_token="app", table_id="table", api_token="token")
        with self.assertRaises(ValueError):
            executor.execute(
                QueryPlan(metric_name="gmv", sql="INSERT INTO t VALUES (1)", parameters={})
            )

    @patch("agent_os_api.feishu_executor.httpx.get")
    def test_executes_read_and_filters_rows(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "data": {
                "items": [
                    {
                        "record_id": "r1",
                        "fields": {
                            "order_date": {"text": "2026-05-31"},
                            "paid_amount": 100.0,
                        },
                    },
                    {
                        "record_id": "r2",
                        "fields": {
                            "order_date": {"text": "2026-06-01"},
                            "paid_amount": 200.0,
                        },
                    },
                ]
            }
        }
        mock_get.return_value = mock_response

        executor = FeishuQueryExecutor(app_token="app", table_id="table", api_token="token")
        result = executor.execute(
            QueryPlan(
                metric_name="gmv",
                sql="SELECT order_date, paid_amount FROM bitable",
                parameters={"order_date": "2026-05-31"},
            )
        )
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.rows[0]["record_id"], "r1")
        self.assertEqual(result.rows[0]["order_date"], "2026-05-31")

    @patch("agent_os_api.feishu_executor.httpx.get")
    def test_request_error_returns_empty(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = Exception("network")
        executor = FeishuQueryExecutor(app_token="app", table_id="table", api_token="token")
        result = executor.execute(
            QueryPlan(metric_name="gmv", sql="SELECT 1 FROM bitable", parameters={})
        )
        self.assertEqual(result.row_count, 0)


if __name__ == "__main__":
    unittest.main()
