"""Tests for QueryPlanner."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import (  # noqa: E402
    MetricContract,
    ProviderContract,
    ProviderKind,
    QueryPlan,
    SQLTemplate,
)
from agent_os_core.data_product_compiler.query_planner import (  # noqa: E402
    QueryPlanner,
    QueryPlanningError,
)


class QueryPlannerTest(unittest.TestCase):
    def _metric(self, verified_queries: tuple[SQLTemplate, ...] = ()) -> MetricContract:
        return MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="g",
            owner="o",
            unit="CNY",
            allowed_schemas=("sales",),
            verified_queries=verified_queries,
        )

    def _provider(self) -> ProviderContract:
        return ProviderContract(
            provider_id="pg",
            kind=ProviderKind.WAREHOUSE,
            name="pg",
            owner="data",
            allowed_schemas=("sales",),
        )

    def test_selects_verified_query_and_binds_parameters(self) -> None:
        metric = self._metric(
            verified_queries=(
                SQLTemplate(
                    template_id="gmv_daily",
                    metric_name="gmv",
                    sql="SELECT order_date, SUM(paid_amount) FROM sales.orders WHERE order_date >= :start_date AND order_date < :end_date GROUP BY 1 LIMIT 1000",
                    required_parameters=("start_date", "end_date"),
                    required_time_parameters=("start_date", "end_date"),
                ),
            )
        )
        planner = QueryPlanner()
        query_plan = planner.plan(
            metric_contract=metric,
            parameters={"start_date": "2026-01-01", "end_date": "2026-01-07"},
            provider_contract=self._provider(),
        )
        self.assertIsInstance(query_plan, QueryPlan)
        self.assertEqual(query_plan.metric_name, "gmv")
        self.assertIn("SUM(paid_amount)", query_plan.sql)
        self.assertEqual(query_plan.parameters["start_date"], "2026-01-01")
        self.assertIsNotNone(query_plan.source_template)
        self.assertEqual(query_plan.source_template.template_id, "gmv_daily")

    def test_raises_when_no_verified_queries(self) -> None:
        planner = QueryPlanner()
        with self.assertRaises(QueryPlanningError):
            planner.plan(
                metric_contract=self._metric(),
                parameters={"start_date": "2026-01-01", "end_date": "2026-01-07"},
                provider_contract=self._provider(),
            )

    def test_raises_when_parameters_missing(self) -> None:
        metric = self._metric(
            verified_queries=(
                SQLTemplate(
                    template_id="gmv_daily",
                    metric_name="gmv",
                    sql="SELECT * FROM sales.orders WHERE order_date >= :start_date AND order_date < :end_date LIMIT 1000",
                    required_parameters=("start_date", "end_date"),
                    required_time_parameters=("start_date", "end_date"),
                ),
            )
        )
        planner = QueryPlanner()
        with self.assertRaises(QueryPlanningError):
            planner.plan(
                metric_contract=metric,
                parameters={"start_date": "2026-01-01"},
                provider_contract=self._provider(),
            )


if __name__ == "__main__":
    unittest.main()
