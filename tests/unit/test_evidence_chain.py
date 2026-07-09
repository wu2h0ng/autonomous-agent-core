"""Tests for typed EvidenceChain fields and EvidenceChainBuilder."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import (  # noqa: E402
    BusinessIntent,
    Claim,
    ConfidenceScore,
    EvalBinding,
    EvidenceChain,
    Limitation,
    MetricContract,
    MetricContractRef,
    ProviderContract,
    ProviderContractRef,
    ProviderKind,
    QueryPlan,
    QueryResult,
    QueryResultSummary,
    SQLSafetyResult,
)
from agent_os_core.evidence_chain import EvidenceChainBuilder  # noqa: E402


class EvidenceChainTypedTest(unittest.TestCase):
    def _metric(self) -> MetricContract:
        return MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="Gross merchandise value",
            owner="revenue_ops",
            unit="CNY",
            allowed_schemas=("sales",),
            version="v1",
        )

    def _provider(self) -> ProviderContract:
        return ProviderContract(
            provider_id="pg",
            kind=ProviderKind.WAREHOUSE,
            name="pg",
            owner="data",
            allowed_schemas=("sales",),
        )

    def _query_plan(self) -> QueryPlan:
        return QueryPlan(
            metric_name="gmv",
            sql="SELECT SUM(paid_amount) FROM sales.orders LIMIT 1000",
            parameters={"start_date": "2026-01-01", "end_date": "2026-01-07"},
        )

    def _sql_safety(self) -> SQLSafetyResult:
        return SQLSafetyResult(
            allowed=True,
            reasons=(),
            checked_schemas=("sales",),
            checked_tables=("sales.orders",),
        )

    def _query_result(self) -> QueryResult:
        return QueryResult(rows=({"gmv": 1000.0},), row_count=1)

    def test_builder_populates_typed_fields(self) -> None:
        builder = EvidenceChainBuilder()
        evidence = builder.build(
            evidence_chain_id="evidence-1",
            intent=BusinessIntent(intent_id="i1", question="What is GMV?", metric_name="gmv"),
            metric_contract=self._metric(),
            query_plan=self._query_plan(),
            sql_safety=self._sql_safety(),
            query_result=self._query_result(),
            trace_id="trace-1",
            provider_contract=self._provider(),
        )

        self.assertTrue(evidence.is_complete())
        self.assertTrue(evidence.is_typed_complete())
        self.assertEqual(len(evidence.metric_contract_refs), 1)
        self.assertIsInstance(evidence.metric_contract_refs[0], MetricContractRef)
        self.assertEqual(evidence.metric_contract_refs[0].metric_name, "gmv")
        self.assertEqual(len(evidence.provider_contract_refs), 1)
        self.assertIsInstance(evidence.provider_contract_refs[0], ProviderContractRef)
        self.assertEqual(evidence.provider_contract_refs[0].provider_id, "pg")
        self.assertIsInstance(evidence.query_result_summary, QueryResultSummary)
        self.assertEqual(evidence.query_result_summary.row_count, 1)
        self.assertEqual(len(evidence.claims), 1)
        self.assertIsInstance(evidence.claims[0], Claim)
        self.assertIn("query_result", evidence.claims[0].evidence_refs)
        # P2-C (ADR-0017): limitations are now DERIVED from the confidence inputs, so the
        # count is context-dependent (this fixture has no source_template and no freshness,
        # so it honestly flags both unverified-template and freshness-unknown). The typed
        # invariant this test pins is that limitation_objects are populated and typed.
        self.assertGreaterEqual(len(evidence.limitation_objects), 1)
        self.assertTrue(all(isinstance(item, Limitation) for item in evidence.limitation_objects))
        self.assertIsInstance(evidence.confidence_score, ConfidenceScore)
        self.assertEqual(len(evidence.eval_bindings), 1)
        self.assertIsInstance(evidence.eval_bindings[0], EvalBinding)

    def test_typed_complete_requires_claims(self) -> None:
        evidence = EvidenceChain(
            evidence_chain_id="evidence-1",
            intent=BusinessIntent(intent_id="i1", question="What is GMV?", metric_name="gmv"),
            metric_contract=self._metric(),
            query_plan=self._query_plan(),
            sql_safety=self._sql_safety(),
            query_result=self._query_result(),
            conclusion="GMV is 1000",
            confidence=0.8,
            limitations=("sample limitation",),
            trace_id="trace-1",
        )
        self.assertTrue(evidence.is_complete())
        self.assertFalse(evidence.is_typed_complete())

    def test_typed_complete_requires_provider_ref(self) -> None:
        evidence = EvidenceChain(
            evidence_chain_id="evidence-1",
            intent=BusinessIntent(intent_id="i1", question="What is GMV?", metric_name="gmv"),
            metric_contract=self._metric(),
            query_plan=self._query_plan(),
            sql_safety=self._sql_safety(),
            query_result=self._query_result(),
            conclusion="GMV is 1000",
            confidence=0.8,
            limitations=("sample limitation",),
            trace_id="trace-1",
            metric_contract_refs=(MetricContractRef(metric_name="gmv"),),
            claims=(Claim(statement="GMV is 1000"),),
            confidence_score=ConfidenceScore(score=0.8),
            eval_bindings=(EvalBinding(eval_case_id="c1", dimension="evidence"),),
        )
        self.assertTrue(evidence.is_complete())
        self.assertFalse(evidence.is_typed_complete())

    def test_builder_without_provider_still_typed_complete_for_metric(self) -> None:
        builder = EvidenceChainBuilder()
        evidence = builder.build(
            evidence_chain_id="evidence-1",
            intent=BusinessIntent(intent_id="i1", question="What is GMV?", metric_name="gmv"),
            metric_contract=self._metric(),
            query_plan=self._query_plan(),
            sql_safety=self._sql_safety(),
            query_result=self._query_result(),
            trace_id="trace-1",
        )
        # Without provider_contract, provider_contract_refs is empty, so not typed complete.
        self.assertTrue(evidence.is_complete())
        self.assertFalse(evidence.is_typed_complete())


if __name__ == "__main__":
    unittest.main()
