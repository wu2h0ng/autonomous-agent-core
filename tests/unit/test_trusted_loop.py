from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import MetricContract, RiskLevel, SQLTemplate
from agent_os_core import TrustedLoopRuntime
from agent_os_core.query_runtime import StaticQueryExecutor


class TrustedLoopRuntimeTest(unittest.TestCase):
    def test_runs_minimum_trusted_loop(self) -> None:
        metric = MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="Gross merchandise value over paid orders.",
            owner="revenue_ops",
            unit="CNY",
            allowed_schemas=("sales",),
        )
        template = SQLTemplate(
            template_id="gmv_daily",
            metric_name="gmv",
            sql=(
                "select order_date, sum(paid_amount) as gmv "
                "from sales.orders "
                "where order_date >= :start_date and order_date < :end_date "
                "group by order_date "
                "limit :limit"
            ),
            required_parameters=("start_date", "end_date", "limit"),
        )
        runtime = TrustedLoopRuntime(
            metric_contract=metric,
            sql_template=template,
            query_executor=StaticQueryExecutor(
                [
                    {"order_date": "2026-05-31", "gmv": 128800.0},
                ]
            ),
        )

        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        self.assertEqual(result.intent.metric_name, "gmv")
        self.assertTrue(result.evidence_chain.is_complete())
        self.assertEqual(result.action_proposal.risk_level, RiskLevel.R2)
        self.assertFalse(result.action_proposal.approval_required)
        self.assertEqual(
            [event.step for event in result.trace_events],
            [
                "intent",
                "query_plan",
                "sql_safety",
                "query_result",
                "evidence_chain",
                "action_proposal",
            ],
        )


if __name__ == "__main__":
    unittest.main()
