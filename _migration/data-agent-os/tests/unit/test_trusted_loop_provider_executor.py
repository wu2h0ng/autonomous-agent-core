"""Tests for provider-driven query executor selection in TrustedLoopRuntime."""

from __future__ import annotations

import sys
import tempfile
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
    ConnectorExecutionSemantics,
    MetricContract,
    ProviderConnection,
    ProviderContract,
    ProviderKind,
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from manual_review.connector import ManualReviewConnector  # noqa: E402
from agent_os_core.query_runtime import CsvQueryExecutor, StaticQueryExecutor  # noqa: E402


class _RecordingExecutorFactory:
    """Wraps StaticQueryExecutor and records which provider was used."""

    def __init__(self, rows: tuple[dict, ...]) -> None:
        self.selected_provider_ids: list[str] = []
        self._rows = rows

    def __call__(self, provider_contract: ProviderContract) -> StaticQueryExecutor:
        self.selected_provider_ids.append(provider_contract.provider_id)
        return StaticQueryExecutor(self._rows)


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
            execution_semantics=ConnectorExecutionSemantics(
                durability_scope="connector_local",
                external_ack_status="unknown",
                ledger_status="connector_reported",
                supports_idempotency=False,
            ),
        ),
    )
    return registry


class TrustedLoopProviderExecutorTest(unittest.TestCase):
    def _metric(self) -> MetricContract:
        return MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="Gross merchandise value.",
            owner="revenue_ops",
            unit="CNY",
            allowed_schemas=("sales",),
        )

    def _template(self) -> SQLTemplate:
        return SQLTemplate(
            template_id="gmv_daily",
            metric_name="gmv",
            sql=(
                "SELECT order_date, paid_amount FROM sales.orders "
                "WHERE order_date >= :start_date AND order_date < :end_date "
                "LIMIT :limit"
            ),
            required_parameters=("start_date", "end_date", "limit"),
        )

    def test_executor_factory_receives_selected_provider(self) -> None:
        provider = ProviderContract(
            provider_id="csv-sales",
            kind=ProviderKind.FILE,
            name="sales csv",
            owner="data",
            allowed_schemas=("sales",),
            connection=ProviderConnection(connection_type="csv", path="/data/orders.csv"),
        )
        factory = _RecordingExecutorFactory(({"order_date": "2026-05-31", "paid_amount": 100.0},))
        runtime = TrustedLoopRuntime(
            metric_contract=self._metric(),
            sql_template=self._template(),
            executor_factory=factory,
            semantic_registry=SemanticRegistry(metric_contracts=(self._metric(),)),
            provider_registry=ProviderRegistry((provider,)),
            connector_registry=_connector_registry(),
        )

        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        self.assertEqual(factory.selected_provider_ids, ["csv-sales"])
        self.assertEqual(result.evidence_chain.query_result.row_count, 1)
        self.assertEqual(result.provider_contract.provider_id, "csv-sales")
        self.assertTrue(result.evidence_chain.is_complete())

    def test_csv_provider_runs_end_to_end(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as tmp:
            tmp.write("order_date,paid_amount\n")
            tmp.write("2026-05-31,100.0\n")
            tmp.write("2026-06-01,200.0\n")
            path = Path(tmp.name)
        try:
            provider = ProviderContract(
                provider_id="csv-sales",
                kind=ProviderKind.FILE,
                name="sales csv",
                owner="data",
                allowed_schemas=("sales",),
                connection=ProviderConnection(connection_type="csv", path=str(path)),
            )

            def factory(_provider: ProviderContract) -> CsvQueryExecutor:
                return CsvQueryExecutor(_provider.connection.path)

            runtime = TrustedLoopRuntime(
                metric_contract=self._metric(),
                sql_template=self._template(),
                executor_factory=factory,
                semantic_registry=SemanticRegistry(metric_contracts=(self._metric(),)),
                provider_registry=ProviderRegistry((provider,)),
                connector_registry=_connector_registry(),
            )

            result = runtime.run(
                "最近7天GMV是多少？",
                {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
            )

            self.assertEqual(result.evidence_chain.query_result.row_count, 2)
            self.assertEqual(result.provider_contract.provider_id, "csv-sales")
        finally:
            path.unlink(missing_ok=True)

    def test_missing_query_executor_and_factory_raises(self) -> None:
        with self.assertRaises(ValueError):
            TrustedLoopRuntime(
                metric_contract=self._metric(),
                sql_template=self._template(),
                connector_registry=_connector_registry(),
            )


if __name__ == "__main__":
    unittest.main()
