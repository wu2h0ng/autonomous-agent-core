from __future__ import annotations

from dataclasses import replace
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
    ActionProposal,
    BusinessIntent,
    ConnectorExecutionSemantics,
    EvidenceChain,
    FeedbackSource,
    MetricContract,
    OperationContract,
    ProviderContract,
    ProviderKind,
    QueryPlan,
    QueryResult,
    RiskLevel,
    SQLSafetyResult,
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    AdoptionLedger,
    GroundingInvariantViolation,
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402

from action_record import ActionRecordConnector, ActionRecordStore  # noqa: E402

RUN_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}


class _FailingDryRunActionRecordConnector(ActionRecordConnector):
    def dry_run(self, operation, parameters):
        return {
            "status": "failed",
            "connector_name": self.connector_name,
            "operation_id": operation.operation_id,
            "reason": "simulated dry-run failure",
        }


class _NoSnapshotActionRecordConnector(ActionRecordConnector):
    def take_snapshot(self, operation):
        return None


class _R3ActionRecordProposalBuilder:
    def build(self, *, proposal_id: str, evidence: EvidenceChain) -> ActionProposal:
        return ActionProposal(
            proposal_id=proposal_id,
            evidence_chain_id=evidence.evidence_chain_id,
            target_object=evidence.metric_contract.metric_name,
            recommended_action="write_r3_action_record",
            reason=evidence.conclusion,
            risk_level=RiskLevel.R3,
            expected_impact="record persisted after approval",
            approval_required=True,
            approver_role="Business Owner",
            connector_name="action_record",
            action_type="execute",
            action_parameters={"amount": 100},
            idempotency_key="idem-d6-r3-loop",
            # ADR-0014: this eval builder deliberately surfaces exactly one action.
            single_option_rationale=(
                "Eval fixture exercises the single approval-bound R3 write path."
            ),
        )


class _R4ActionRecordProposalBuilder:
    def build(self, *, proposal_id: str, evidence: EvidenceChain) -> ActionProposal:
        return ActionProposal(
            proposal_id=proposal_id,
            evidence_chain_id=evidence.evidence_chain_id,
            target_object=evidence.metric_contract.metric_name,
            recommended_action="write_r4_action_record",
            reason=evidence.conclusion,
            risk_level=RiskLevel.R4,
            expected_impact="proposal only in MVP",
            approval_required=True,
            approver_role="Business Owner",
            connector_name="action_record",
            action_type="execute",
            action_parameters={"amount": 100},
            idempotency_key="idem-d6-r4-loop",
            # ADR-0014: this eval builder deliberately surfaces exactly one action.
            single_option_rationale=(
                "Eval fixture exercises the single approval-bound R4 proposal path."
            ),
        )


def _build_runtime_with_action_record_r3() -> tuple[
    TrustedLoopRuntime, ActionRecordStore, AdoptionLedger
]:
    return _build_runtime_with_action_record(
        connector_cls=ActionRecordConnector,
        risk_ceiling="R3",
    )


def _build_runtime_with_action_record(
    *,
    connector_cls=ActionRecordConnector,
    risk_ceiling: str = "R3",
) -> tuple[TrustedLoopRuntime, ActionRecordStore, AdoptionLedger]:
    store = ActionRecordStore()
    ledger = AdoptionLedger()
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
            "select order_date, sum(paid_amount) as gmv "
            "from sales.orders "
            "where order_date >= :start_date and order_date < :end_date "
            "group by order_date "
            "limit :limit"
        ),
        required_parameters=("start_date", "end_date", "limit"),
    )
    registry = ActionConnectorRegistry()
    registry.register(
        connector_cls(store=store),
        ActionConnectorContract(
            connector_name="action_record",
            display_name="Action Record",
            supported_action_types=("execute",),
            supports_snapshot=True,
            supports_rollback=True,
            compensating_action_description="Restore store to snapshot",
            risk_ceiling=risk_ceiling,
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
    runtime = TrustedLoopRuntime(
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
        connector_registry=registry,
        adoption_ledger_view=ledger.view(),
    )
    runtime.action_builder = _R3ActionRecordProposalBuilder()  # type: ignore[assignment]
    return runtime, store, ledger


def _metric() -> MetricContract:
    return MetricContract(
        metric_name="gmv",
        display_name="GMV",
        definition="Gross merchandise value over paid orders.",
        owner="revenue_ops",
        unit="CNY",
        allowed_schemas=("sales",),
    )


def _operation(idempotency_key: str = "idem-d6-manual") -> OperationContract:
    return OperationContract(
        operation_id="operation-proposal-d6",
        name="d6",
        target_connector="action_record",
        risk_level="R3",
        approval_required=True,
        dry_run_required=True,
        rollback_supported=True,
        snapshot_required=True,
        connector_name="action_record",
        action_type="execute",
        idempotency_key=idempotency_key,
    )


def _incomplete_evidence_chain() -> EvidenceChain:
    metric = _metric()
    return EvidenceChain(
        evidence_chain_id="evidence-incomplete",
        intent=BusinessIntent(intent_id="intent-1", question="GMV", metric_name="gmv"),
        metric_contract=metric,
        query_plan=QueryPlan(
            metric_name="gmv",
            sql="select 1 from sales.orders limit :limit",
            parameters={"limit": 100},
        ),
        sql_safety=SQLSafetyResult(
            allowed=False,
            reasons=("forced incomplete evidence",),
            checked_schemas=("sales",),
            checked_tables=("sales.orders",),
            bound_parameters=("limit",),
            limit_value=100,
        ),
        query_result=QueryResult(rows=(), row_count=0),
        conclusion="unsafe",
        confidence=0.0,
        limitations=("sql safety blocked",),
        trace_id="trace-incomplete",
    )


def _approve_and_execute(runtime: TrustedLoopRuntime):
    result = runtime.run("最近7天GMV是多少？", dict(RUN_PARAMS))
    runtime.approval_runtime.approve(result.approval_record.approval_id, reason="approved")
    operation_trace = runtime.execute_approved_operation(
        approval_id=result.approval_record.approval_id,
        operation=result.operation_contract,
        action_parameters=result.action_proposal.action_parameters,
        evidence_chain=result.evidence_chain,
        proposal_id=result.action_proposal.proposal_id,
    )
    return result, operation_trace


def _snapshot_id(operation_trace) -> str:
    for event in operation_trace.events:
        if event.get("step") == "state_snapshot" and isinstance(event.get("snapshot_id"), str):
            return event["snapshot_id"]
    raise AssertionError("state_snapshot event missing")


class GovernedActionOutcomeLoopD6Eval(unittest.TestCase):
    def test_connector_risk_ceiling_cannot_be_exceeded(self) -> None:
        runtime, store, _ledger = _build_runtime_with_action_record(risk_ceiling="R3")
        runtime.action_builder = _R4ActionRecordProposalBuilder()  # type: ignore[assignment]

        with self.assertRaisesRegex(ValueError, "risk ceiling"):
            runtime.run("最近7天GMV是多少？", dict(RUN_PARAMS))

        self.assertEqual(store.records(), ())

    def test_dry_run_failure_cannot_execute_approved_action(self) -> None:
        runtime, store, _ledger = _build_runtime_with_action_record(
            connector_cls=_FailingDryRunActionRecordConnector
        )
        result = runtime.run("最近7天GMV是多少？", dict(RUN_PARAMS))
        runtime.approval_runtime.approve(result.approval_record.approval_id, reason="approved")

        with self.assertRaisesRegex(ValueError, "dry-run failed"):
            runtime.execute_approved_operation(
                approval_id=result.approval_record.approval_id,
                operation=result.operation_contract,
                action_parameters=result.action_proposal.action_parameters,
                evidence_chain=result.evidence_chain,
                proposal_id=result.action_proposal.proposal_id,
            )

        self.assertEqual(store.records(), ())

    def test_required_snapshot_missing_cannot_execute_approved_action(self) -> None:
        runtime, store, _ledger = _build_runtime_with_action_record(
            connector_cls=_NoSnapshotActionRecordConnector
        )
        result = runtime.run("最近7天GMV是多少？", dict(RUN_PARAMS))
        runtime.approval_runtime.approve(result.approval_record.approval_id, reason="approved")

        with self.assertRaisesRegex(ValueError, "required snapshot"):
            runtime.execute_approved_operation(
                approval_id=result.approval_record.approval_id,
                operation=result.operation_contract,
                action_parameters=result.action_proposal.action_parameters,
                evidence_chain=result.evidence_chain,
                proposal_id=result.action_proposal.proposal_id,
            )

        self.assertEqual(store.records(), ())

    def test_incomplete_evidence_chain_cannot_execute_approved_action(self) -> None:
        runtime, store, _ledger = _build_runtime_with_action_record_r3()
        runtime.approval_runtime.create_pending(
            approval_id="approval-d6",
            proposal_id="proposal-d6",
            approver_role="Business Owner",
            operation_fingerprint=TrustedLoopRuntime._approval_fingerprint(
                operation=_operation(),
                action_parameters={"amount": 100},
                evidence_chain_id="evidence-incomplete",
            ),
        )
        runtime.approval_runtime.approve("approval-d6", reason="approved")

        with self.assertRaises(GroundingInvariantViolation):
            runtime.execute_approved_operation(
                approval_id="approval-d6",
                operation=_operation(),
                action_parameters={"amount": 100},
                evidence_chain=_incomplete_evidence_chain(),
                proposal_id="proposal-d6",
            )
        self.assertEqual(store.records(), ())

    def test_mismatched_evidence_chain_cannot_execute_approved_action(self) -> None:
        runtime, store, _ledger = _build_runtime_with_action_record_r3()
        result = runtime.run("最近7天GMV是多少？", dict(RUN_PARAMS))
        runtime.approval_runtime.approve(result.approval_record.approval_id, reason="approved")
        mismatched_evidence = replace(
            result.evidence_chain,
            evidence_chain_id="evidence-mismatched",
        )

        with self.assertRaisesRegex(ValueError, "operation-approval mismatch"):
            runtime.execute_approved_operation(
                approval_id=result.approval_record.approval_id,
                operation=result.operation_contract,
                action_parameters=result.action_proposal.action_parameters,
                evidence_chain=mismatched_evidence,
                proposal_id=result.action_proposal.proposal_id,
            )
        self.assertEqual(store.records(), ())

    def test_runtime_self_report_does_not_promote_knowledge_or_external_adoption(self) -> None:
        runtime, _store, ledger = _build_runtime_with_action_record_r3()
        result = runtime.run("最近7天GMV是多少？", dict(RUN_PARAMS))
        trace_id = result.evidence_chain.trace_id

        feedback = runtime.record_outcome(
            trace_id=trace_id,
            outcome="adopted",
            reviewer="runtime",
            metric_deltas={"gmv": 1200},
        )

        self.assertEqual(feedback.source, FeedbackSource.RUNTIME_SELF_REPORT)
        self.assertEqual(runtime.knowledge_store.version_of(trace_id), 1)
        self.assertEqual(runtime.adoption_for_trace(trace_id), ())
        self.assertEqual(ledger.all_events(), ())

    def test_rollback_restores_approved_action_snapshot(self) -> None:
        runtime, store, _ledger = _build_runtime_with_action_record_r3()
        _result, operation_trace = _approve_and_execute(runtime)
        self.assertEqual(len(store.records()), 1)

        rollback = runtime.rollback(_snapshot_id(operation_trace))

        self.assertEqual(rollback["status"], "rolled_back")
        self.assertEqual(store.records(), ())

    def test_missing_adoption_event_cannot_promote_knowledge(self) -> None:
        runtime, _store, _ledger = _build_runtime_with_action_record_r3()
        result = runtime.run("最近7天GMV是多少？", dict(RUN_PARAMS))
        trace_id = result.evidence_chain.trace_id

        self.assertIsNone(runtime.promote_from_adoption(trace_id))
        self.assertEqual(runtime.knowledge_store.version_of(trace_id), 1)

    def test_repeated_idempotency_key_does_not_double_write(self) -> None:
        runtime, store, _ledger = _build_runtime_with_action_record_r3()
        result, first_trace = _approve_and_execute(runtime)
        second_trace = runtime.execute_approved_operation(
            approval_id=result.approval_record.approval_id,
            operation=result.operation_contract,
            action_parameters=result.action_proposal.action_parameters,
            evidence_chain=result.evidence_chain,
            proposal_id=result.action_proposal.proposal_id,
        )

        self.assertEqual(len(store.records()), 1)
        self.assertEqual(first_trace.events[-1]["status"], "executed")
        self.assertEqual(second_trace.events[-1]["status"], "idempotent_replay")

    def test_unapproved_action_cannot_execute(self) -> None:
        runtime, store, _ledger = _build_runtime_with_action_record_r3()
        result = runtime.run("最近7天GMV是多少？", dict(RUN_PARAMS))

        with self.assertRaises(ValueError):
            runtime.execute_approved_operation(
                approval_id=result.approval_record.approval_id,
                operation=result.operation_contract,
                action_parameters=result.action_proposal.action_parameters,
                evidence_chain=result.evidence_chain,
                proposal_id=result.action_proposal.proposal_id,
            )
        self.assertEqual(store.records(), ())


if __name__ == "__main__":
    unittest.main()
