"""Knowledge recall inside run() (AR-20260611-knowledge-recall-and-env-wiring).

The read-side of the learning loop: run() consults the KnowledgeRetriever after
semantic resolution and surfaces prior organizational knowledge on
``TrustedLoopResult.related_knowledge`` plus a ``knowledge_recall`` trace event.
Recall is advisory: a failing retriever must never block a governed answer, but
the failure must be trace-visible.
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_contracts import (  # noqa: E402
    ActionConnectorContract,
    KnowledgeAsset,
    KnowledgeQuery,
    LifecycleState,
    MetricContract,
    ProviderContract,
    ProviderKind,
    RiskLevel,
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    HashingEmbedder,
    IndexingKnowledgeStore,
    InMemoryKnowledgeRetriever,
    KnowledgeRetriever,
    KnowledgeStore,
    ProviderRegistry,
    SemanticRegistry,
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


def _runtime(*, knowledge_store=None, knowledge_retriever=None) -> TrustedLoopRuntime:
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
        knowledge_retriever=knowledge_retriever,
    )


def _recall_events(result):
    return [e for e in result.trace_events if e.step == "knowledge_recall"]


class KnowledgeRecallInRunTest(unittest.TestCase):
    def _wired_runtime(self) -> tuple[TrustedLoopRuntime, InMemoryKnowledgeRetriever]:
        retriever = InMemoryKnowledgeRetriever(HashingEmbedder(64))
        store = IndexingKnowledgeStore(KnowledgeStore(), retriever)
        return _runtime(knowledge_store=store, knowledge_retriever=retriever), retriever

    def test_first_run_recalls_nothing_no_self_hit(self) -> None:
        # Recall happens BEFORE the current run's candidate is registered.
        runtime, _ = self._wired_runtime()
        result = runtime.run("GMV", dict(PARAMS))
        self.assertEqual(result.related_knowledge, ())
        # The recall step is still traced (it ran and found nothing).
        self.assertEqual(len(_recall_events(result)), 1)

    def test_second_run_does_not_recall_unreviewed_draft_candidate(self) -> None:
        runtime, _ = self._wired_runtime()
        first = runtime.run("GMV", dict(PARAMS))
        first_asset = first.knowledge_asset_candidate
        self.assertIsNotNone(first_asset)

        second = runtime.run("GMV", dict(PARAMS))
        self.assertEqual(second.related_knowledge, ())
        (event,) = _recall_events(second)
        self.assertEqual(event.payload.get("asset_ids", []), [])

    def test_second_run_recalls_active_reviewed_knowledge(self) -> None:
        runtime, _ = self._wired_runtime()
        first = runtime.run("GMV", dict(PARAMS))
        first_asset = first.knowledge_asset_candidate
        self.assertIsNotNone(first_asset)
        active_asset = replace(first_asset, state=LifecycleState.ACTIVE)
        runtime.knowledge_store.register_version(active_asset)

        second = runtime.run("GMV", dict(PARAMS))
        recalled_ids = [r.asset.asset_id for r in second.related_knowledge]
        self.assertIn(active_asset.asset_id, recalled_ids)
        self.assertIn("total", second.related_knowledge[0].score_breakdown)
        (event,) = _recall_events(second)
        self.assertIn(active_asset.asset_id, event.payload.get("asset_ids", []))

    def test_recalled_reviewed_knowledge_is_bound_to_proposal_without_lowering_governance(
        self,
    ) -> None:
        runtime, _ = self._wired_runtime()
        first = runtime.run("GMV", dict(PARAMS))
        first_asset = first.knowledge_asset_candidate
        self.assertIsNotNone(first_asset)
        active_asset = replace(first_asset, state=LifecycleState.ACTIVE)
        runtime.knowledge_store.register_version(active_asset)

        second = runtime.run("GMV", dict(PARAMS))

        self.assertEqual(
            getattr(second.action_proposal, "knowledge_context_refs", ()),
            (active_asset.asset_id,),
        )
        proposal_events = [e for e in second.trace_events if e.step == "action_proposal"]
        self.assertEqual(len(proposal_events), 1)
        self.assertEqual(
            proposal_events[0].payload.get("knowledge_context_refs"),
            [active_asset.asset_id],
        )
        self.assertEqual(second.action_proposal.risk_level, RiskLevel.R2)
        self.assertFalse(second.action_proposal.approval_required)

    def test_without_retriever_behavior_unchanged(self) -> None:
        runtime = _runtime()
        result = runtime.run("GMV", dict(PARAMS))
        self.assertEqual(result.related_knowledge, ())
        self.assertEqual(_recall_events(result), [])

    def test_failing_retriever_is_advisory_and_trace_visible(self) -> None:
        class ExplodingRetriever(KnowledgeRetriever):
            def search(self, query: KnowledgeQuery):
                raise RuntimeError("index offline")

        runtime = _runtime(knowledge_retriever=ExplodingRetriever())
        result = runtime.run("GMV", dict(PARAMS))  # must NOT raise
        self.assertEqual(result.related_knowledge, ())
        (event,) = _recall_events(result)
        self.assertIn("index offline", event.payload.get("error", ""))


class IndexingKnowledgeStoreTest(unittest.TestCase):
    def _asset(self, aid: str, title: str, trace: str) -> KnowledgeAsset:
        return KnowledgeAsset(
            asset_id=aid,
            title=title,
            asset_type="decision_loop",
            source_trace_id=trace,
            owner="revenue_ops",
            state=LifecycleState.DRAFT,
        )

    def test_register_indexes_with_projected_metric(self) -> None:
        retriever = InMemoryKnowledgeRetriever(HashingEmbedder(64))
        store = IndexingKnowledgeStore(KnowledgeStore(), retriever)
        store.register_version(
            replace(
                self._asset("a", "[gmv] gross merchandise value", "trace-a"),
                state=LifecycleState.ACTIVE,
            )
        )

        hits = retriever.search(KnowledgeQuery(text="gross merchandise value", metric_name="gmv"))
        self.assertEqual([h.asset.asset_id for h in hits], ["a"])
        # Storage delegation intact.
        self.assertEqual(store.version_of("trace-a"), 1)

    def test_version_bump_replaces_index_entry_per_trace(self) -> None:
        # Mirrors the SQL knowledge_index: one current entry per trace.
        retriever = InMemoryKnowledgeRetriever(HashingEmbedder(64))
        store = IndexingKnowledgeStore(KnowledgeStore(), retriever)
        store.register_version(
            replace(
                self._asset("v1", "[gmv] original wording", "trace-x"), state=LifecycleState.ACTIVE
            )
        )
        store.register_version(
            replace(
                self._asset("v2", "[gmv] original wording", "trace-x"), state=LifecycleState.ACTIVE
            )
        )

        hits = retriever.search(KnowledgeQuery(text="original wording", k=10))
        self.assertEqual([h.asset.asset_id for h in hits], ["v2"])

    def test_outcome_projects_into_outcome_score(self) -> None:
        from dataclasses import replace

        retriever = InMemoryKnowledgeRetriever(HashingEmbedder(64))
        store = IndexingKnowledgeStore(KnowledgeStore(), retriever)
        adopted = replace(
            self._asset("k", "[gmv] adopted wisdom", "trace-k"),
            state=LifecycleState.ACTIVE,
            outcome="adopted",
        )
        store.register_version(adopted)

        (hit,) = retriever.search(KnowledgeQuery(text="adopted wisdom", k=1))
        self.assertGreater(hit.score_breakdown["outcome_boost"], 0.0)

    def test_traceless_assets_are_not_indexed(self) -> None:
        # The strict in-memory KnowledgeStore rejects traceless assets outright, so
        # use a permissive base to prove the DECORATOR also skips indexing them
        # (parity with the SQL EmbeddingKnowledgeStore's skip).
        from agent_os_core import KnowledgeStorePort

        class PermissiveStore(KnowledgeStorePort):
            def register(self, asset):
                return asset

            def register_version(self, asset):
                return asset

            def get_by_trace(self, trace_id):
                return None

            def version_of(self, trace_id):
                return 0

            def all_assets(self):
                return ()

        retriever = InMemoryKnowledgeRetriever(HashingEmbedder(64))
        store = IndexingKnowledgeStore(PermissiveStore(), retriever)
        asset = KnowledgeAsset(
            asset_id="no-trace",
            title="[gmv] not retrievable memory",
            asset_type="decision_loop",
            source_trace_id=None,
            owner="revenue_ops",
            state=LifecycleState.DRAFT,
        )
        store.register(asset)
        self.assertEqual(retriever.search(KnowledgeQuery(text="not retrievable memory")), ())


if __name__ == "__main__":
    unittest.main()
