from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

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

PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}
SAFE_SQL = (
    "select order_date, sum(paid_amount) as value from sales.orders "
    "where order_date >= :start_date and order_date < :end_date "
    "group by order_date limit :limit"
)
UNSAFE_SQL = (
    "select * from sales.orders "
    "where order_date >= :start_date and order_date < :end_date limit :limit"
)


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


def _metric(name: str = "gmv") -> MetricContract:
    return MetricContract(
        metric_name=name,
        display_name=name.upper(),
        definition=f"{name} metric.",
        owner="content_commerce_ops",
        unit="CNY",
        allowed_schemas=("sales",),
    )


def _provider(schemas: tuple[str, ...] = ("sales",)) -> ProviderContract:
    return ProviderContract(
        provider_id="provider-sales",
        kind=ProviderKind.WAREHOUSE,
        name="sales",
        owner="data_platform",
        allowed_schemas=schemas,
    )


def _tpl(metric: str, sql: str = SAFE_SQL) -> SQLTemplate:
    return SQLTemplate(
        template_id=f"{metric}_daily",
        metric_name=metric,
        sql=sql,
        required_parameters=("start_date", "end_date", "limit"),
    )


def _runtime(
    *,
    metrics: tuple[MetricContract, ...] = (_metric("gmv"),),
    template_registry: TemplateRegistry | None = None,
    sql_template: SQLTemplate | None = None,
    provider: ProviderContract | None = None,
) -> TrustedLoopRuntime:
    if template_registry is None and sql_template is None:
        sql_template = _tpl("gmv")
    return TrustedLoopRuntime(
        metric_contract=metrics[0],
        sql_template=sql_template,
        template_registry=template_registry,
        query_executor=StaticQueryExecutor([{"order_date": "2026-05-31", "value": 1.0}]),
        semantic_registry=SemanticRegistry(metric_contracts=metrics),
        provider_registry=ProviderRegistry((provider or _provider(),)),
        connector_registry=_connector_registry(),
    )


class TrustedLoopOutcomeTest(unittest.TestCase):
    def test_evaluate_ok_for_normal_run(self) -> None:
        outcome = _runtime().evaluate("GMV last 7 days", dict(PARAMS))
        self.assertTrue(outcome.ok)
        self.assertFalse(outcome.blocked)
        self.assertEqual(outcome.status, "ok")
        self.assertIsNotNone(outcome.result)
        self.assertIsNone(outcome.block)
        self.assertEqual(outcome.result.intent.metric_name, "gmv")

    def test_evaluate_blocked_on_unsafe_sql(self) -> None:
        runtime = _runtime(sql_template=_tpl("gmv", UNSAFE_SQL))
        outcome = runtime.evaluate("GMV last 7 days", dict(PARAMS))
        self.assertTrue(outcome.blocked)
        self.assertEqual(outcome.status, "blocked")
        self.assertIsNone(outcome.result)
        self.assertIsNotNone(outcome.block)
        self.assertEqual(outcome.block.code, BlockCode.SQL_SAFETY)
        self.assertEqual(outcome.block.stage, "sql_safety")
        self.assertTrue(outcome.block.details)  # carries the safety reasons

    def test_evaluate_blocked_on_missing_template(self) -> None:
        # spend metric resolves, but the strict registry only knows gmv.
        runtime = _runtime(
            metrics=(_metric("gmv"), _metric("spend")),
            template_registry=TemplateRegistry((_tpl("gmv"),)),
        )
        outcome = runtime.evaluate("ad spend last 7 days", dict(PARAMS))
        self.assertTrue(outcome.blocked)
        self.assertEqual(outcome.block.code, BlockCode.NO_TEMPLATE)
        self.assertEqual(outcome.block.stage, "template_selection")

    def test_evaluate_blocked_on_unknown_metric(self) -> None:
        # semantic registry knows only gmv; the question resolves to 'roi'.
        runtime = _runtime(metrics=(_metric("gmv"),))
        outcome = runtime.evaluate("ROI last 7 days", dict(PARAMS))
        self.assertTrue(outcome.blocked)
        self.assertEqual(outcome.block.code, BlockCode.UNKNOWN_METRIC)
        self.assertEqual(outcome.block.stage, "metric_resolution")

    def test_evaluate_blocked_on_no_provider(self) -> None:
        # provider cannot satisfy the metric's 'sales' schema.
        runtime = _runtime(provider=_provider(schemas=("marketing",)))
        outcome = runtime.evaluate("GMV last 7 days", dict(PARAMS))
        self.assertTrue(outcome.blocked)
        self.assertEqual(outcome.block.code, BlockCode.NO_PROVIDER)
        self.assertEqual(outcome.block.stage, "provider_selection")

    def test_run_raises_typed_block(self) -> None:
        runtime = _runtime(sql_template=_tpl("gmv", UNSAFE_SQL))
        with self.assertRaises(TrustedLoopBlocked) as ctx:
            runtime.run("GMV last 7 days", dict(PARAMS))
        self.assertEqual(ctx.exception.block.code, BlockCode.SQL_SAFETY)


if __name__ == "__main__":
    unittest.main()
