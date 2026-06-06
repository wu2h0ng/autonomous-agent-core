from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import (  # noqa: E402
    ActionProposal,
    BusinessIntent,
    EvidenceChain,
    FeedbackEvent,
    KnowledgeAsset,
    LifecycleState,
    MetricContract,
    QueryPlan,
    QueryResult,
    RiskLevel,
    SQLSafetyResult,
)
from agent_os_core.knowledge_memory import (  # noqa: E402
    KnowledgeAssetBuilder,
    KnowledgeStore,
)


def _evidence_chain(
    *,
    trace_id: str = "trace-7",
    question: str = "What drove GMV growth last week?",
    metric_name: str = "gmv",
    owner: str = "revenue_ops",
) -> EvidenceChain:
    intent = BusinessIntent(
        intent_id="intent-1",
        question=question,
        metric_name=metric_name,
    )
    metric_contract = MetricContract(
        metric_name=metric_name,
        display_name="Gross Merchandise Value",
        definition="Sum of order amounts.",
        owner=owner,
        unit="CNY",
        allowed_schemas=("sales",),
    )
    query_plan = QueryPlan(
        metric_name=metric_name,
        sql="SELECT sum(amount) FROM sales.orders",
        parameters={},
    )
    sql_safety = SQLSafetyResult(
        allowed=True,
        reasons=("ok",),
        checked_schemas=("sales",),
    )
    query_result = QueryResult(rows=({"gmv": 100.0},), row_count=1)
    return EvidenceChain(
        evidence_chain_id="evidence-1",
        intent=intent,
        metric_contract=metric_contract,
        query_plan=query_plan,
        sql_safety=sql_safety,
        query_result=query_result,
        conclusion="GMV grew 12% driven by repeat buyers.",
        confidence=0.82,
        limitations=("single week window",),
        trace_id=trace_id,
    )


def _proposal(evidence_chain_id: str = "evidence-1") -> ActionProposal:
    return ActionProposal(
        proposal_id="proposal-1",
        evidence_chain_id=evidence_chain_id,
        target_object="gmv_daily",
        recommended_action="Increase retention budget.",
        reason="Repeat buyers drove growth.",
        risk_level=RiskLevel.R2,
        expected_impact="Higher GMV.",
        approval_required=True,
        approver_role="revenue_lead",
    )


class KnowledgeAssetBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = KnowledgeAssetBuilder()

    def test_candidate_captures_source_trace_and_draft_state(self) -> None:
        chain = _evidence_chain(trace_id="trace-99")
        asset = self.builder.build(
            evidence_chain=chain,
            action_proposal=_proposal(),
            trace_id="trace-99",
        )
        self.assertIsInstance(asset, KnowledgeAsset)
        self.assertEqual(asset.source_trace_id, "trace-99")
        self.assertEqual(asset.state, LifecycleState.DRAFT)
        self.assertEqual(asset.asset_type, "decision_loop")

    def test_title_reflects_metric_and_question(self) -> None:
        chain = _evidence_chain(metric_name="gmv", question="Why did GMV move?")
        asset = self.builder.build(
            evidence_chain=chain,
            action_proposal=_proposal(),
            trace_id=chain.trace_id,
        )
        # Title must reflect actual inputs, not be a constant.
        self.assertIn("gmv", asset.title.lower())
        self.assertIn("GMV move", asset.title)

    def test_title_changes_with_different_metric(self) -> None:
        chain_a = _evidence_chain(metric_name="gmv", question="Q about gmv")
        chain_b = _evidence_chain(metric_name="dau", question="Q about dau")
        asset_a = self.builder.build(
            evidence_chain=chain_a, action_proposal=_proposal(), trace_id="t-a"
        )
        asset_b = self.builder.build(
            evidence_chain=chain_b, action_proposal=_proposal(), trace_id="t-b"
        )
        self.assertNotEqual(asset_a.title, asset_b.title)

    def test_owner_derived_from_metric_contract(self) -> None:
        chain = _evidence_chain(owner="growth_team")
        asset = self.builder.build(
            evidence_chain=chain, action_proposal=_proposal(), trace_id=chain.trace_id
        )
        self.assertEqual(asset.owner, "growth_team")

    def test_asset_id_is_deterministic_from_trace(self) -> None:
        chain = _evidence_chain(trace_id="trace-x")
        a1 = self.builder.build(
            evidence_chain=chain, action_proposal=_proposal(), trace_id="trace-x"
        )
        a2 = self.builder.build(
            evidence_chain=chain, action_proposal=_proposal(), trace_id="trace-x"
        )
        self.assertEqual(a1.asset_id, a2.asset_id)

    def test_optional_feedback_influences_candidate(self) -> None:
        chain = _evidence_chain()
        feedback = FeedbackEvent(
            feedback_id="fb-1",
            trace_id=chain.trace_id,
            outcome="adopted",
        )
        without = self.builder.build(
            evidence_chain=chain, action_proposal=_proposal(), trace_id=chain.trace_id
        )
        with_fb = self.builder.build(
            evidence_chain=chain,
            action_proposal=_proposal(),
            trace_id=chain.trace_id,
            feedback=feedback,
        )
        # Feedback should be reflected somewhere observable (id differs).
        self.assertNotEqual(without.asset_id, with_fb.asset_id)


class KnowledgeStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = KnowledgeAssetBuilder()
        self.store = KnowledgeStore()

    def _candidate(self, trace_id: str) -> KnowledgeAsset:
        chain = _evidence_chain(trace_id=trace_id)
        return self.builder.build(
            evidence_chain=chain, action_proposal=_proposal(), trace_id=trace_id
        )

    def test_register_and_retrieve_by_trace(self) -> None:
        asset = self._candidate("trace-1")
        stored = self.store.register(asset)
        self.assertEqual(stored, asset)
        self.assertEqual(self.store.get_by_trace("trace-1"), asset)

    def test_dedup_same_trace_does_not_create_duplicate(self) -> None:
        first = self._candidate("trace-1")
        second = self._candidate("trace-1")
        self.store.register(first)
        self.store.register(second)
        self.assertEqual(len(self.store.all_assets()), 1)

    def test_dedup_preserves_first_registered_asset(self) -> None:
        first = self._candidate("trace-1")
        second = self._candidate("trace-1")
        self.store.register(first)
        returned = self.store.register(second)
        # Dedup returns the already-registered asset, not a duplicate.
        self.assertEqual(returned, first)
        self.assertEqual(self.store.version_of("trace-1"), 1)

    def test_distinct_traces_create_distinct_assets(self) -> None:
        self.store.register(self._candidate("trace-1"))
        self.store.register(self._candidate("trace-2"))
        self.assertEqual(len(self.store.all_assets()), 2)

    def test_get_by_unknown_trace_returns_none(self) -> None:
        self.assertIsNone(self.store.get_by_trace("missing"))

    def test_register_version_supersedes_and_bumps_version(self) -> None:
        first = self._candidate("trace-1")
        self.store.register(first)
        chain = _evidence_chain(trace_id="trace-1", metric_name="dau")
        revised = self.builder.build(
            evidence_chain=chain, action_proposal=_proposal(), trace_id="trace-1"
        )
        returned = self.store.register_version(revised)
        self.assertEqual(returned, revised)
        self.assertEqual(self.store.get_by_trace("trace-1"), revised)
        self.assertEqual(self.store.version_of("trace-1"), 2)
        self.assertEqual(len(self.store.all_assets()), 1)


if __name__ == "__main__":
    unittest.main()
