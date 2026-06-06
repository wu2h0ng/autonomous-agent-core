from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))
sys.path.insert(0, str(ROOT / "apps" / "api_server" / "src"))

from agent_os_contracts import (  # noqa: E402
    ActionConnectorContract,
    BlockCode,
    MetricContract,
    ProviderContract,
    ProviderKind,
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    ProviderRegistry,
    SemanticRegistry,
    TemplateRegistry,
    TrustedLoopBlocked,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

GMV_SQL = (
    "select order_date, sum(paid_amount) as value from sales.orders "
    "where order_date >= :start_date and order_date < :end_date "
    "group by order_date limit :limit"
)
SPEND_SQL = (
    "select order_date, sum(spend) as value from sales.orders "
    "where order_date >= :start_date and order_date < :end_date "
    "group by order_date limit :limit"
)
PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}


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


def _metric(name: str, unit: str) -> MetricContract:
    return MetricContract(
        metric_name=name,
        display_name=name.upper(),
        definition=f"{name} metric.",
        owner="content_commerce_ops",
        unit=unit,
        allowed_schemas=("sales",),
    )


def _tpl(metric: str, sql: str) -> SQLTemplate:
    return SQLTemplate(
        template_id=f"{metric}_daily",
        metric_name=metric,
        sql=sql,
        required_parameters=("start_date", "end_date", "limit"),
    )


class MultiMetricTemplateSelectionTest(unittest.TestCase):
    def _runtime(self, registry: TemplateRegistry) -> TrustedLoopRuntime:
        metrics = (_metric("gmv", "CNY"), _metric("spend", "CNY"))
        return TrustedLoopRuntime(
            metric_contract=metrics[0],
            template_registry=registry,
            query_executor=StaticQueryExecutor([{"order_date": "2026-05-31", "value": 1.0}]),
            semantic_registry=SemanticRegistry(metric_contracts=metrics),
            provider_registry=ProviderRegistry(
                (
                    ProviderContract(
                        provider_id="provider-sales",
                        kind=ProviderKind.WAREHOUSE,
                        name="sales",
                        owner="data_platform",
                        allowed_schemas=("sales",),
                    ),
                )
            ),
            connector_registry=_connector_registry(),
        )

    def test_runtime_selects_template_by_resolved_metric(self) -> None:
        registry = TemplateRegistry((_tpl("gmv", GMV_SQL), _tpl("spend", SPEND_SQL)))
        runtime = self._runtime(registry)

        gmv_result = runtime.run("GMV last 7 days", dict(PARAMS))
        self.assertEqual(gmv_result.intent.metric_name, "gmv")
        self.assertEqual(gmv_result.query_plan.sql, GMV_SQL)
        self.assertEqual(gmv_result.evidence_chain.query_plan.sql, GMV_SQL)

        spend_result = runtime.run("ad spend last 7 days", dict(PARAMS))
        self.assertEqual(spend_result.intent.metric_name, "spend")
        self.assertEqual(spend_result.query_plan.sql, SPEND_SQL)
        self.assertEqual(spend_result.evidence_chain.query_plan.sql, SPEND_SQL)

    def test_missing_template_for_resolved_metric_blocks(self) -> None:
        # Strict registry knows gmv only; spend metric resolves but has no template.
        registry = TemplateRegistry((_tpl("gmv", GMV_SQL),))
        runtime = self._runtime(registry)
        with self.assertRaises(TrustedLoopBlocked) as ctx:
            runtime.run("ad spend last 7 days", dict(PARAMS))
        self.assertEqual(ctx.exception.block.code, BlockCode.NO_TEMPLATE)
        # The unified evaluate() surface reports it as a structured block.
        outcome = runtime.evaluate("ad spend last 7 days", dict(PARAMS))
        self.assertTrue(outcome.blocked)
        self.assertEqual(outcome.block.code, BlockCode.NO_TEMPLATE)

    def test_requires_a_template_source(self) -> None:
        with self.assertRaises(ValueError):
            TrustedLoopRuntime(
                metric_contract=_metric("gmv", "CNY"),
                query_executor=StaticQueryExecutor([{"value": 1.0}]),
                connector_registry=_connector_registry(),
            )


class FactoryMultiMetricTest(unittest.TestCase):
    """The factory-built sqlite runtime serves multiple metrics with real SQL."""

    def _runtime(self):
        from agent_os_api.runtime_factory import (
            EXECUTOR_SQLITE,
            ContentCommerceRuntimeFactory,
            RuntimeFactoryConfig,
        )

        config = RuntimeFactoryConfig(
            domain_pack_path=ROOT / "domain_packs" / "content_commerce",
            executor=EXECUTOR_SQLITE,
        )
        return ContentCommerceRuntimeFactory(config).build()

    def test_gmv_and_spend_return_different_real_aggregates(self) -> None:
        gmv = self._runtime().run("GMV last 7 days", dict(PARAMS))
        spend = self._runtime().run("ad spend last 7 days", dict(PARAMS))

        self.assertEqual(gmv.intent.metric_name, "gmv")
        self.assertEqual(spend.intent.metric_name, "spend")
        # Real, distinct aggregates computed by the selected SQL against the seed.
        gmv_value = gmv.evidence_chain.query_result.rows[0]["value"]
        spend_value = spend.evidence_chain.query_result.rows[0]["value"]
        self.assertEqual(gmv_value, 128800.0)
        self.assertNotEqual(gmv_value, spend_value)


if __name__ == "__main__":
    unittest.main()
