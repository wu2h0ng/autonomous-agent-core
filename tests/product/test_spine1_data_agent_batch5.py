"""SPINE-1 batch 5: Data Agent data-product / knowledge / feedback modules (domain pack).

Representative entry-point tests proving each ported module is real (not just importable).
"""

from __future__ import annotations

import pytest

from domain_packs.data_agent.adoption import AdoptionIngest, AdoptionLedger
from domain_packs.data_agent.alert_agent import AlertAgent, AlertRule
from domain_packs.data_agent.conversation import ContextResolver, InMemoryConversationStore
from domain_packs.data_agent.dashboard import Dashboard, DashboardCard, InMemoryDashboardStore
from domain_packs.data_agent.data_access_plane import ProviderRegistry
from domain_packs.data_agent.data_product_compiler import DataProductCompiler
from domain_packs.data_agent.domain_contracts import (
    DataRequirement,
    KnowledgeAsset,
    KnowledgeQuery,
    LineageSnapshot,
    MetricContract,
    ProviderContract,
    ProviderKind,
    QueryPlan,
)
from domain_packs.data_agent.embedding import HashingEmbedder, tokenize
from domain_packs.data_agent.eval_hub import EvalCaseOutcome, EvalThresholdReporter
from domain_packs.data_agent.feedback import FeedbackEventBuilder, FeedbackStore
from domain_packs.data_agent.knowledge_memory import KnowledgeStore
from domain_packs.data_agent.knowledge_retrieval import Candidate, HybridScorer


def _provider() -> ProviderContract:
    return ProviderContract(
        provider_id="pg",
        kind=ProviderKind.WAREHOUSE,
        name="pg",
        owner="data",
        allowed_schemas=("sales",),
    )


def _metric() -> MetricContract:
    return MetricContract(
        metric_name="gmv",
        display_name="GMV",
        definition="Gross merchandise value",
        owner="revenue_ops",
        unit="CNY",
        allowed_schemas=("sales",),
    )


def test_embedding_produces_deterministic_fixed_dimension_vector() -> None:
    embedder = HashingEmbedder(dimensions=8)

    vector = embedder.embed("gmv revenue")

    assert len(vector) == 8
    assert vector == embedder.embed("gmv revenue")
    assert vector != embedder.embed("orders")
    assert tokenize("GMV by channel")  # non-empty tokens


def test_provider_registry_selects_by_schema() -> None:
    registry = ProviderRegistry((_provider(),))

    assert registry.choose_for_schemas(("sales",)).provider_id == "pg"
    assert registry.list_ids() == ("pg",)
    with pytest.raises(KeyError):
        registry.choose_for_schemas(("unknown_schema",))


def test_alert_agent_emits_proposal_when_threshold_crossed() -> None:
    agent = AlertAgent((AlertRule(rule_id="r1", metric_name="gmv", threshold=100.0, comparison="lt"),))

    assert agent.evaluate("gmv", 50.0) is not None
    assert agent.evaluate("gmv", 500.0) is None


def test_dashboard_store_roundtrip() -> None:
    store = InMemoryDashboardStore()
    dashboard = Dashboard(
        dashboard_id="d1",
        tenant_id="tenant:acme",
        title="Revenue",
        cards=(DashboardCard(card_id="c1", title="GMV", question="GMV?", metric_name="gmv", chart_type="line"),),
        created_at="2026-09-15T00:00:00+00:00",
    )

    store.save(dashboard)

    assert store.get("d1", "tenant:acme") is not None
    assert len(store.list("tenant:acme", 10, 0)) == 1


def test_conversation_store_and_context_resolver() -> None:
    store = InMemoryConversationStore()
    session = store.get_or_create("s1")
    session.current_metric = "gmv"

    resolved = ContextResolver().resolve("转化率是多少", session)

    assert isinstance(resolved, str) and resolved


def test_feedback_builder_record_and_counts() -> None:
    event = FeedbackEventBuilder().build(trace_id="t1", outcome="success", reviewer="ops")
    store = FeedbackStore()

    store.record(event)

    assert store.get_by_trace("t1")[0].outcome == "success"
    assert store.outcome_counts()["success"] == 1


def test_adoption_ledger_and_ingest() -> None:
    ledger = AdoptionLedger()
    ingest = AdoptionIngest(ledger)

    ingest.submit(trace_id="t2", outcome="adopted", reviewer="ops")

    assert ledger.get_by_trace("t2")
    assert ledger.view().adoption_counts()["adopted"] == 1


def test_eval_threshold_reporter_builds_report() -> None:
    reporter = EvalThresholdReporter({"evidence": 0.5})

    report = reporter.build((EvalCaseOutcome(case_id="c1", checks={"evidence": True}),))

    assert report is not None


def test_knowledge_store_register_and_lookup() -> None:
    store = KnowledgeStore()
    asset = KnowledgeAsset(
        asset_id="a1",
        title="GMV drop playbook",
        asset_type="decision_loop",
        source_trace_id="t1",
        owner="revenue_ops",
        outcome="success",
    )

    store.register(asset)

    assert store.get_by_trace("t1").asset_id == "a1"


def test_hybrid_scorer_ranks_matching_asset_higher() -> None:
    embedder = HashingEmbedder(dimensions=32)
    scorer = HybridScorer(embedder)
    matching = KnowledgeAsset(
        asset_id="a1", title="GMV", asset_type="decision_loop", source_trace_id="t1", owner="o", outcome="success"
    )
    other = KnowledgeAsset(
        asset_id="a2", title="orders", asset_type="decision_loop", source_trace_id="t2", owner="o", outcome="success"
    )
    candidates = [
        Candidate(asset=matching, embedding=embedder.embed("GMV"), tokens=tuple(tokenize("GMV")), recency=0.0, outcome_score=1.0),
        Candidate(asset=other, embedding=embedder.embed("orders"), tokens=tuple(tokenize("orders")), recency=0.0, outcome_score=1.0),
    ]

    results = scorer.score(KnowledgeQuery(text="GMV"), candidates)

    assert results[0].asset.asset_id == "a1"
    assert results[0].score >= results[1].score


def test_data_product_compiler_builds_candidate() -> None:
    requirement = DataRequirement(
        requirement_id="req1",
        intent_id="i1",
        metric_names=("gmv",),
        dimensions=(),
        time_window={},
    )
    lineage = LineageSnapshot(
        lineage_id="ls1", provider_id="pg", source_objects=("sales.orders",), generated_by="compiler"
    )
    plan = QueryPlan("gmv", "SELECT 1 FROM sales.orders LIMIT 1", {})

    candidate = DataProductCompiler().build_candidate(
        requirement=requirement,
        metric_contract=_metric(),
        query_plan=plan,
        lineage_snapshot=lineage,
    )

    assert candidate.data_product_id
    assert candidate.requirement_id == "req1"
