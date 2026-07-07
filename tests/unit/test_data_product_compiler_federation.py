"""Tests for DataProductCompiler federated query planning (ADR-0013 Workstream A)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import (  # noqa: E402
    BusinessIntent,
    FederatedQueryPlan,
    LogicalView,
    MaterializationHint,
    MetricContract,
    ProviderContract,
    ProviderKind,
    QueryPlan,
    RuntimeFeatureFlags,
    SQLTemplate,
)
from agent_os_core.data_access_plane import ProviderRegistry  # noqa: E402
from agent_os_core.data_product_compiler import DataProductCompiler  # noqa: E402


class DataProductCompilerFederationTest(unittest.TestCase):
    def _metric(self) -> MetricContract:
        return MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="gross merchandise value",
            owner="revenue_ops",
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

    def _registry(self) -> ProviderRegistry:
        return ProviderRegistry(
            (
                ProviderContract(
                    provider_id="pg",
                    kind=ProviderKind.WAREHOUSE,
                    name="postgres",
                    owner="data",
                    allowed_schemas=("sales",),
                ),
                ProviderContract(
                    provider_id="mysql",
                    kind=ProviderKind.WAREHOUSE,
                    name="mysql",
                    owner="data",
                    allowed_schemas=("sales",),
                ),
            )
        )

    def test_flag_off_multi_provider_returns_single_query_plan(self) -> None:
        compiler = DataProductCompiler()
        result = compiler.compile(
            intent=BusinessIntent("i1", "what is gmv", "gmv"),
            metric_contract=self._metric(),
            parameters={"start_date": "2026-01-01", "end_date": "2026-01-07"},
            provider_registry=self._registry(),
            provider_ids=("pg", "mysql"),
            feature_flags=RuntimeFeatureFlags(),
        )
        self.assertIsInstance(result["query_plan"], QueryPlan)
        self.assertNotIsInstance(result["query_plan"], FederatedQueryPlan)
        self.assertEqual(result["provider_contract"].provider_id, "pg")

    def test_flag_on_multi_provider_returns_federated_query_plan(self) -> None:
        compiler = DataProductCompiler()
        result = compiler.compile(
            intent=BusinessIntent("i1", "what is gmv", "gmv"),
            metric_contract=self._metric(),
            parameters={"start_date": "2026-01-01", "end_date": "2026-01-07"},
            provider_registry=self._registry(),
            provider_ids=("pg", "mysql"),
            logical_views=(
                LogicalView(
                    view_id="v1",
                    name="unified_gmv",
                    source_providers=("pg", "mysql"),
                    owner="data",
                ),
            ),
            feature_flags=RuntimeFeatureFlags(data_fabric_v1=True),
        )
        query_plan = result["query_plan"]
        self.assertIsInstance(query_plan, FederatedQueryPlan)
        self.assertEqual(len(query_plan.sub_queries), 2)
        self.assertEqual(query_plan.combine_strategy, "UNION ALL")
        self.assertTrue(all(isinstance(sub, QueryPlan) for sub in query_plan.sub_queries))

    def test_materialization_hints_propagated_to_candidate(self) -> None:
        hints = (
            MaterializationHint(
                hint_id="h1",
                data_product_id="*",
                strategy="view",
                refresh_policy="daily",
            ),
        )
        compiler = DataProductCompiler()
        result = compiler.compile(
            intent=BusinessIntent("i1", "what is gmv", "gmv"),
            metric_contract=self._metric(),
            parameters={"start_date": "2026-01-01", "end_date": "2026-01-07"},
            provider_registry=self._registry(),
            materialization_hints=hints,
        )
        candidate = result["data_product_candidate"]
        self.assertEqual(
            candidate.metadata.get("materialization_hints"),
            hints,
        )


if __name__ == "__main__":
    unittest.main()
