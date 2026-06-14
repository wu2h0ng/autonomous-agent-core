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
    KnowledgeAsset,
    MetricContract,
    ProviderContract,
    ProviderKind,
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    FeedbackStore,
    FeedbackStorePort,
    InMemorySnapshotStore,
    KnowledgeStore,
    KnowledgeStorePort,
    ProviderRegistry,
    SemanticRegistry,
    SnapshotStore,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

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


class _RecordingKnowledgeStore(KnowledgeStorePort):
    """A port implementation that is NOT a KnowledgeStore, to prove the runtime
    programs to the port rather than the concrete in-memory class."""

    def __init__(self) -> None:
        self.registered: list[KnowledgeAsset] = []
        self._by_trace: dict[str, KnowledgeAsset] = {}
        self._versions: dict[str, int] = {}

    def register(self, asset: KnowledgeAsset) -> KnowledgeAsset:
        self.registered.append(asset)
        existing = self._by_trace.get(asset.source_trace_id)
        if existing is not None:
            return existing
        self._by_trace[asset.source_trace_id] = asset
        self._versions[asset.source_trace_id] = 1
        return asset

    def register_version(self, asset: KnowledgeAsset) -> KnowledgeAsset:
        self._by_trace[asset.source_trace_id] = asset
        self._versions[asset.source_trace_id] = self._versions.get(asset.source_trace_id, 0) + 1
        return asset

    def get_by_trace(self, trace_id: str) -> KnowledgeAsset | None:
        return self._by_trace.get(trace_id)

    def version_of(self, trace_id: str) -> int:
        return self._versions.get(trace_id, 0)

    def all_assets(self) -> tuple[KnowledgeAsset, ...]:
        return tuple(self._by_trace.values())


def _runtime(*, knowledge_store=None) -> TrustedLoopRuntime:
    metric = MetricContract(
        metric_name="gmv",
        display_name="GMV",
        definition="gmv metric.",
        owner="content_commerce_ops",
        unit="CNY",
        allowed_schemas=("sales",),
    )
    template = SQLTemplate(
        template_id="gmv_daily",
        metric_name="gmv",
        sql=(
            "select order_date, sum(paid_amount) as value from sales.orders "
            "where order_date >= :start_date and order_date < :end_date "
            "group by order_date limit :limit"
        ),
        required_parameters=("start_date", "end_date", "limit"),
    )
    return TrustedLoopRuntime(
        metric_contract=metric,
        sql_template=template,
        query_executor=StaticQueryExecutor([{"order_date": "2026-05-31", "value": 1.0}]),
        semantic_registry=SemanticRegistry(metric_contracts=(metric,)),
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
        knowledge_store=knowledge_store,
    )


class StorePortsTest(unittest.TestCase):
    def test_in_memory_stores_implement_ports(self) -> None:
        self.assertIsInstance(FeedbackStore(), FeedbackStorePort)
        self.assertIsInstance(KnowledgeStore(), KnowledgeStorePort)
        self.assertIsInstance(InMemorySnapshotStore(), SnapshotStore)

    def test_ports_are_abstract(self) -> None:
        with self.assertRaises(TypeError):
            FeedbackStorePort()  # type: ignore[abstract]
        with self.assertRaises(TypeError):
            KnowledgeStorePort()  # type: ignore[abstract]

    def test_runtime_programs_to_the_knowledge_port(self) -> None:
        # Inject a port impl that is NOT KnowledgeStore; the loop must still use it.
        store = _RecordingKnowledgeStore()
        runtime = _runtime(knowledge_store=store)
        result = runtime.run("GMV last 7 days", dict(PARAMS))

        self.assertEqual(len(store.registered), 1)
        trace_id = result.evidence_chain.trace_id
        self.assertIsNotNone(store.get_by_trace(trace_id))
        self.assertEqual(store.version_of(trace_id), 1)

        # P5.1b: a self-report does NOT program knowledge through the port
        # (wirehead closed) — promotion is reserved for realized adoption.
        runtime.record_outcome(trace_id=trace_id, outcome="adopted")
        self.assertEqual(store.version_of(trace_id), 1)


if __name__ == "__main__":
    unittest.main()
