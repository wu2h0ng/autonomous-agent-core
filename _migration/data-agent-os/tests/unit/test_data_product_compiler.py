"""Integration tests for DataProductCompiler orchestration."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import (  # noqa: E402
    BusinessIntent,
    MetricContract,
    ProviderContract,
    ProviderKind,
    QueryPlan,
    SQLTemplate,
)
from agent_os_core.data_access_plane import ProviderRegistry  # noqa: E402
from agent_os_core.data_product_compiler import DataProductCompiler  # noqa: E402


class DataProductCompilerIntegrationTest(unittest.TestCase):
    def test_full_compile_pipeline(self) -> None:
        metric = MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="g",
            owner="o",
            unit="CNY",
            allowed_schemas=("sales",),
            dimensions=("order_date",),
            verified_queries=(
                SQLTemplate(
                    template_id="gmv_daily",
                    metric_name="gmv",
                    sql="SELECT order_date, SUM(paid_amount) FROM sales.orders WHERE order_date >= :start_date AND order_date < :end_date GROUP BY 1 LIMIT 1000",
                    required_parameters=("start_date", "end_date"),
                    required_time_parameters=("start_date", "end_date"),
                ),
            ),
        )
        registry = ProviderRegistry(
            (
                ProviderContract(
                    provider_id="pg",
                    kind=ProviderKind.WAREHOUSE,
                    name="pg",
                    owner="data",
                    allowed_schemas=("sales",),
                ),
            )
        )
        compiler = DataProductCompiler()
        result = compiler.compile(
            intent=BusinessIntent("i1", "what is gmv", "gmv"),
            metric_contract=metric,
            parameters={"start_date": "2026-01-01", "end_date": "2026-01-07"},
            provider_registry=registry,
        )
        self.assertIn("query_plan", result)
        self.assertIn("data_product_candidate", result)
        query_plan = result["query_plan"]
        assert isinstance(query_plan, QueryPlan)
        self.assertEqual(query_plan.metric_name, "gmv")
        self.assertIsNotNone(query_plan.source_template)
        self.assertEqual(query_plan.source_template.template_id, "gmv_daily")


if __name__ == "__main__":
    unittest.main()
