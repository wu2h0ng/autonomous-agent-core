"""Tests for the DataProductCompiler path in TrustedLoopRuntime."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "os_core" / "src",
    ROOT / "action_connectors",
):
    sys.path.insert(0, str(_p))

from agent_os_contracts import (  # noqa: E402
    ActionConnectorContract,
    MetricContract,
    ProviderContract,
    ProviderKind,
    SQLTemplate,
)
from agent_os_core import ProviderRegistry, SemanticRegistry, TrustedLoopRuntime  # noqa: E402
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from manual_review.connector import ManualReviewConnector  # noqa: E402


def _connector_registry() -> ActionConnectorRegistry:
    registry = ActionConnectorRegistry()
    registry.register(
        ManualReviewConnector(),
        ActionConnectorContract(
            connector_name="manual_review",
            display_name="Manual Review",
            supported_action_types=("propose", "execute"),
            supports_snapshot=False,
            supports_rollback=False,
            compensating_action_description=None,
            risk_ceiling="R5",
            owner="system",
        ),
    )
    return registry


def _verified_template(metric_name: str) -> SQLTemplate:
    return SQLTemplate(
        template_id=f"{metric_name}_daily",
        metric_name=metric_name,
        sql=(
            "select order_date, sum(paid_amount) as value "
            "from sales.orders "
            "where order_date >= :start_date and order_date < :end_date "
            "group by order_date limit :limit"
        ),
        required_parameters=("start_date", "end_date", "limit"),
        required_time_parameters=("start_date", "end_date"),
    )


class TrustedLoopCompilerPathTest(unittest.TestCase):
    def _metric(self, metric_name: str = "gmv") -> MetricContract:
        return MetricContract(
            metric_name=metric_name,
            display_name=metric_name.upper(),
            definition=f"{metric_name} metric contract.",
            owner="content_commerce_ops",
            unit="CNY",
            allowed_schemas=("sales",),
            verified_queries=(_verified_template(metric_name),),
        )

    def _provider(self) -> ProviderContract:
        return ProviderContract(
            provider_id="provider-sales",
            kind=ProviderKind.WAREHOUSE,
            name="sales warehouse",
            owner="data_platform",
            allowed_schemas=("sales",),
        )

    def test_compiler_path_runs_without_template_registry(self) -> None:
        metric = self._metric()
        runtime = TrustedLoopRuntime(
            metric_contract=metric,
            query_executor=StaticQueryExecutor([{"order_date": "2026-05-31", "value": 100.0}]),
            semantic_registry=SemanticRegistry(metric_contracts=(metric,)),
            provider_registry=ProviderRegistry((self._provider(),)),
            connector_registry=_connector_registry(),
        )

        self.assertIsNone(runtime.template_registry)
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        self.assertEqual(result.intent.metric_name, "gmv")
        self.assertEqual(result.query_plan.metric_name, "gmv")
        self.assertIsNotNone(result.query_plan.source_template)
        self.assertEqual(result.provider_contract.provider_id, "provider-sales")
        self.assertTrue(result.evidence_chain.is_complete())
        self.assertTrue(result.evidence_chain.is_typed_complete())
        self.assertIsNotNone(result.data_product_candidate)

    def test_compiler_path_blocks_when_metric_has_no_verified_queries(self) -> None:
        metric = MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="Gross merchandise value.",
            owner="ops",
            unit="CNY",
            allowed_schemas=("sales",),
            verified_queries=(),
        )
        runtime = TrustedLoopRuntime(
            metric_contract=metric,
            query_executor=StaticQueryExecutor([{"order_date": "2026-05-31", "value": 100.0}]),
            semantic_registry=SemanticRegistry(metric_contracts=(metric,)),
            provider_registry=ProviderRegistry((self._provider(),)),
            connector_registry=_connector_registry(),
        )

        result = runtime.evaluate(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.block.stage, "data_product_compiler")

    def test_legacy_template_registry_path_still_works(self) -> None:
        metric = self._metric()
        runtime = TrustedLoopRuntime(
            metric_contract=metric,
            sql_template=_verified_template("gmv"),
            query_executor=StaticQueryExecutor([{"order_date": "2026-05-31", "value": 100.0}]),
            semantic_registry=SemanticRegistry(metric_contracts=(metric,)),
            provider_registry=ProviderRegistry((self._provider(),)),
            connector_registry=_connector_registry(),
        )

        self.assertIsNotNone(runtime.template_registry)
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        self.assertEqual(result.intent.metric_name, "gmv")
        self.assertEqual(result.query_plan.metric_name, "gmv")
        self.assertTrue(result.evidence_chain.is_complete())


if __name__ == "__main__":
    unittest.main()
