"""S4 (RR-0048 Option 2): the outcome -> learning moat, closed to a REAL governed action.

The moat is governed action -> measured outcome -> compounding per-customer knowledge. S2/S3 proved the
governed action executes for real and reversibly; S4 closes the loop: a REAL governed action's
operator-attested realized value compounds the knowledge asset — AND a runtime self-report can never do
so. The compounding mechanism (recall quality-boost by outcome_correction_count; realized-value knowledge
promotion) already lives in OS Core and is unit-tested; this slice ties it to a real, disposer-governed,
executed action and asserts the anti-wirehead guarantee that makes the moat trustworthy.

Proven here:
  1. a real disposer-governed R0-R3 action executes -> a DRAFT KnowledgeAsset candidate (v1) is sedimented;
     when the OPERATOR attests realized external value (AdoptionIngest — the value channel the runtime
     never holds), promote_from_adoption supersedes it with a bumped version (v2). Real action -> realized
     value -> compounded knowledge.
  2. anti-wirehead: the runtime's own record_outcome("adopted") self-report is recorded for audit but does
     NOT promote knowledge (promote_from_adoption returns None; version stays v1). The runtime cannot grow
     its own moat by self-reporting success.
  3. with no value channel wired at all, promotion is structurally impossible — defense in depth.

Honest bound: this compounds KNOWLEDGE/recall value from realized outcomes (the value-capture moat); it is
not a claim that the disposer's causal model self-improves (a separate, unclaimed axis).
"""

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
    ConnectorExecutionSemantics,
    LifecycleState,
    MetricContract,
    ProviderContract,
    ProviderKind,
    QueryResult,
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.adoption import AdoptionIngest, AdoptionLedger  # noqa: E402
from agent_os_core.governance_decision_seam import (  # noqa: E402
    LocalGovernanceDecisionClient,
    MetricCohortABVerifier,
)
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from action_record import ActionRecordConnector, ActionRecordStore  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

_ACTION_INTENT = "记录行动：基于最近7天GMV创建一个跟进行动"
_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}


def _cohort() -> QueryResult:
    rows = tuple(
        [{"cohort": "A", "metric": v} for v in (120.0, 132.0, 128.0, 141.0)]
        + [{"cohort": "B", "metric": v} for v in (88.0, 91.0, 84.0, 90.0)]
    )
    return QueryResult(rows=rows, row_count=len(rows))


def _disposer() -> LocalGovernanceDecisionClient:
    return LocalGovernanceDecisionClient(
        MetricCohortABVerifier(lambda action: _cohort()),
        approval_required_at_or_above="R4",
    )


def _connector_registry(store: ActionRecordStore) -> ActionConnectorRegistry:
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
    registry.register(
        ActionRecordConnector(store=store),
        ActionConnectorContract(
            connector_name="action_record",
            display_name="Action Record",
            supported_action_types=("execute",),
            supports_snapshot=True,
            supports_rollback=True,
            compensating_action_description="Restore the action record store to the pre-execution snapshot",
            risk_ceiling="R3",
            owner="system",
            execution_semantics=ConnectorExecutionSemantics(
                durability_scope="connector_local_ledger",
                external_ack_status="not_applicable",
                ledger_status="recorded",
                supports_idempotency=True,
                supports_reconciliation=True,
            ),
        ),
    )
    return registry


def _runtime(store, *, adoption_ledger_view=None) -> TrustedLoopRuntime:
    metric = MetricContract(
        metric_name="gmv",
        display_name="GMV",
        definition="Gross merchandise value over paid orders.",
        owner="revenue_ops",
        unit="CNY",
        allowed_schemas=("sales",),
    )
    template = SQLTemplate(
        template_id="gmv_daily",
        metric_name="gmv",
        sql=(
            "select order_date, sum(paid_amount) as gmv from sales.orders "
            "where order_date >= :start_date and order_date < :end_date group by order_date limit :limit"
        ),
        required_parameters=("start_date", "end_date", "limit"),
    )
    return TrustedLoopRuntime(
        metric_contract=metric,
        sql_template=template,
        query_executor=StaticQueryExecutor([{"order_date": "2026-05-31", "gmv": 128800.0}]),
        semantic_registry=SemanticRegistry(metric_contracts=(metric,)),
        provider_registry=ProviderRegistry(
            (
                ProviderContract(
                    provider_id="provider-sales",
                    kind=ProviderKind.WAREHOUSE,
                    name="sales warehouse",
                    owner="revenue_ops",
                    allowed_schemas=("sales",),
                ),
            )
        ),
        connector_registry=_connector_registry(store),
        governance_decision_client=_disposer(),
        adoption_ledger_view=adoption_ledger_view,
    )


def _run_execute(runtime):
    """Run a real disposer-governed action to approval, approve, execute; return (result, trace_id)."""
    result = runtime.run(_ACTION_INTENT, _PARAMS)
    assert result.action_result["status"] == "awaiting_approval"
    approval_id = result.approval_record.approval_id
    runtime.approval_runtime.approve(approval_id, reason="approved by operator")
    runtime.execute_approved_operation(
        approval_id=approval_id,
        operation=result.operation_contract,
        action_parameters=result.action_proposal.action_parameters,
        evidence_chain=result.evidence_chain,
        proposal_id=result.action_proposal.proposal_id,
    )
    return result, result.evidence_chain.trace_id


class OutcomeLearningMoat(unittest.TestCase):
    def test_realized_value_from_real_governed_action_compounds_knowledge(self):
        store = ActionRecordStore()
        ingest = AdoptionIngest(AdoptionLedger())  # the OPERATOR holds the only writer
        runtime = _runtime(
            store, adoption_ledger_view=ingest.view()
        )  # runtime gets a READ-ONLY view

        _result, trace_id = _run_execute(runtime)

        self.assertEqual(len(store.records()), 1)  # the real reversible action executed
        candidate = runtime.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.state, LifecycleState.DRAFT)
        self.assertEqual(runtime.knowledge_store.version_of(trace_id), 1)

        # the OPERATOR attests realized external value for this executed action (the value channel)
        ingest.submit(trace_id=trace_id, outcome="adopted", metric_deltas={"gmv": 12.0})
        revised = runtime.promote_from_adoption(trace_id)

        self.assertIsNotNone(revised)  # realized value compounded the knowledge asset
        self.assertEqual(runtime.knowledge_store.version_of(trace_id), 2)  # v1 -> v2, superseded

    def test_self_report_cannot_grow_the_moat(self):
        # anti-wirehead: adoption channel wired, but the OPERATOR never attests. A runtime self-report
        # must not promote knowledge — else the system could grow its own moat by declaring success.
        store = ActionRecordStore()
        ingest = AdoptionIngest(AdoptionLedger())
        runtime = _runtime(store, adoption_ledger_view=ingest.view())

        _result, trace_id = _run_execute(runtime)

        feedback = runtime.record_outcome(
            trace_id=trace_id, outcome="adopted", metric_deltas={"gmv": 99.0}
        )
        # the self-report IS captured for audit/trace (observed) ...
        self.assertIn(feedback, runtime.feedback_store.get_by_trace(trace_id))
        # ... but it CANNOT promote knowledge: no operator-attested realized value exists.
        self.assertIsNone(runtime.promote_from_adoption(trace_id))
        self.assertEqual(
            runtime.knowledge_store.version_of(trace_id), 1
        )  # still v1, not compounded

    def test_no_value_channel_makes_promotion_structurally_impossible(self):
        # defense in depth: with NO adoption view wired at all, promotion cannot happen regardless.
        store = ActionRecordStore()
        runtime = _runtime(store, adoption_ledger_view=None)

        _result, trace_id = _run_execute(runtime)
        runtime.record_outcome(trace_id=trace_id, outcome="adopted", metric_deltas={"gmv": 5.0})

        self.assertIsNone(runtime.promote_from_adoption(trace_id))
        self.assertEqual(runtime.knowledge_store.version_of(trace_id), 1)


if __name__ == "__main__":
    unittest.main()
