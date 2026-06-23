from __future__ import annotations

from dataclasses import replace
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_contracts import (  # noqa: E402
    ActionConnectorContract,
    ActionProposal,
    ConnectorExecutionSemantics,
    EvidenceChain,
    MetricContract,
    OperationState,
    ProviderContract,
    ProviderKind,
    RiskLevel,
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    InMemorySnapshotStore,
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402

from action_record import ActionRecordConnector, ActionRecordStore  # noqa: E402


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


class _ActionRecordProposalBuilder:
    """Routes every proposal to the action_record connector at R2 risk.

    R2 (non-empty result) => non-approval AND snapshot-eligible (snapshot_required
    comes from the connector contract, risk is R2 which is >= R2).
    """

    def build(self, *, proposal_id: str, evidence: EvidenceChain) -> ActionProposal:
        return ActionProposal(
            proposal_id=proposal_id,
            evidence_chain_id=evidence.evidence_chain_id,
            target_object=evidence.metric_contract.metric_name,
            recommended_action="write_action_record",
            reason=evidence.conclusion,
            risk_level=RiskLevel.R2,
            expected_impact="record persisted",
            approval_required=False,
            approver_role=None,
            connector_name="action_record",
            action_type="execute",
            action_parameters={"amount": 100},
        )


class _R4ActionRecordProposalBuilder:
    """Routes every proposal to action_record as an approval-required R4 action."""

    def build(self, *, proposal_id: str, evidence: EvidenceChain) -> ActionProposal:
        return ActionProposal(
            proposal_id=proposal_id,
            evidence_chain_id=evidence.evidence_chain_id,
            target_object=evidence.metric_contract.metric_name,
            recommended_action="write_r4_action_record",
            reason=evidence.conclusion,
            risk_level=RiskLevel.R4,
            expected_impact="record persisted after approval",
            approval_required=True,
            approver_role="Business Owner",
            connector_name="action_record",
            action_type="execute",
            action_parameters={"amount": 100},
            idempotency_key="idem-r4-demo",
        )


class _R3ApprovalActionRecordProposalBuilder:
    """Routes every proposal to action_record as an approval-required R3 action."""

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
            idempotency_key="idem-r3-demo",
        )


class _ExternalWebhookAckLost(RuntimeError):
    def audit_event(self) -> dict[str, object]:
        return {
            "step": "connector_execution_uncertain",
            "connector_name": "external_webhook",
            "action_type": "execute",
            "status": "uncertain",
            "external_request_id": "ext-req-uncertain",
            "durability_scope": "external_connector",
            "replay_status": "not_replayed",
            "ledger_status": "connector_reported",
            "reason_code": "lost_after_submit",
            "error_type": self.__class__.__name__,
            "execution_certainty": "submitted_unconfirmed",
            "ack_status": "lost_after_submit",
            "secret_token": "must-not-leak",
            "raw_parameters": {"customer_id": "cust-1"},
        }


class _UncertainExternalWebhookConnector:
    @property
    def connector_name(self) -> str:
        return "external_webhook"

    def take_snapshot(self, operation):
        return None

    def dry_run(self, operation, parameters):
        return {
            "status": "dry_run",
            "connector_name": self.connector_name,
            "operation_id": operation.operation_id,
        }

    def execute(self, operation, parameters):
        raise _ExternalWebhookAckLost("external webhook submitted but ACK was not observed")

    def rollback(self, snapshot):
        return {"status": "not_supported"}

    def can_rollback(self) -> bool:
        return False

    def compensating_action(self) -> str | None:
        return None


class _R3ApprovalExternalWebhookProposalBuilder:
    def build(self, *, proposal_id: str, evidence: EvidenceChain) -> ActionProposal:
        return ActionProposal(
            proposal_id=proposal_id,
            evidence_chain_id=evidence.evidence_chain_id,
            target_object=evidence.metric_contract.metric_name,
            recommended_action="submit_external_webhook",
            reason=evidence.conclusion,
            risk_level=RiskLevel.R3,
            expected_impact="submit an approval-bound external connector request",
            approval_required=True,
            approver_role="Business Owner",
            connector_name="external_webhook",
            action_type="execute",
            action_parameters={"customer_id": "cust-1", "secret_token": "must-not-leak"},
            idempotency_key="idem-external-webhook",
        )


def _build_action_record_registry(
    store: ActionRecordStore,
    *,
    risk_ceiling: str = "R3",
    connector: ActionRecordConnector | None = None,
) -> ActionConnectorRegistry:
    registry = ActionConnectorRegistry()
    connector = connector or ActionRecordConnector(store=store)
    contract = ActionConnectorContract(
        connector_name="action_record",
        display_name="Action Record",
        supported_action_types=("execute",),
        supports_snapshot=True,
        supports_rollback=True,
        compensating_action_description="Restore the action record store to the snapshot state",
        risk_ceiling=risk_ceiling,
        owner="system",
        execution_semantics=ConnectorExecutionSemantics(
            durability_scope="connector_local_ledger",
            external_ack_status="not_applicable",
            ledger_status="recorded",
            supports_idempotency=True,
            supports_reconciliation=True,
        ),
    )
    registry.register(connector, contract)
    return registry


def _build_external_webhook_registry() -> ActionConnectorRegistry:
    registry = ActionConnectorRegistry()
    registry.register(
        _UncertainExternalWebhookConnector(),
        ActionConnectorContract(
            connector_name="external_webhook",
            display_name="External Webhook",
            supported_action_types=("execute",),
            supports_snapshot=False,
            supports_rollback=False,
            compensating_action_description=None,
            risk_ceiling="R3",
            owner="system",
        ),
    )
    return registry


def _build_runtime(
    store: ActionRecordStore,
    *,
    risk_ceiling: str = "R3",
    connector: ActionRecordConnector | None = None,
) -> TrustedLoopRuntime:
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
        connector_registry=_build_action_record_registry(
            store,
            risk_ceiling=risk_ceiling,
            connector=connector,
        ),
    )
    runtime.action_builder = _ActionRecordProposalBuilder()  # type: ignore[assignment]
    return runtime


def _build_r4_runtime(store: ActionRecordStore) -> TrustedLoopRuntime:
    runtime = _build_runtime(store, risk_ceiling="R4")
    runtime.action_builder = _R4ActionRecordProposalBuilder()  # type: ignore[assignment]
    return runtime


def _build_approval_runtime(store: ActionRecordStore) -> TrustedLoopRuntime:
    runtime = _build_runtime(store, risk_ceiling="R3")
    runtime.action_builder = _R3ApprovalActionRecordProposalBuilder()  # type: ignore[assignment]
    return runtime


def _build_external_approval_runtime() -> TrustedLoopRuntime:
    runtime = _build_runtime(ActionRecordStore(), risk_ceiling="R3")
    runtime.connector_registry = _build_external_webhook_registry()
    runtime.action_governance = runtime.action_governance.__class__(
        connector_registry=runtime.connector_registry
    )
    runtime.action_builder = _R3ApprovalExternalWebhookProposalBuilder()  # type: ignore[assignment]
    return runtime


def _run_params() -> dict[str, object]:
    return {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}


def _snapshot_id_from_trace_events(events: tuple[dict[str, object], ...]) -> str:
    for event in events:
        if event.get("step") == "state_snapshot":
            snapshot_id = event.get("snapshot_id")
            if isinstance(snapshot_id, str):
                return snapshot_id
    raise AssertionError("operation trace did not include a state_snapshot event")


class TrustedLoopSnapshotTest(unittest.TestCase):
    def test_default_snapshot_store_is_in_memory(self) -> None:
        store = ActionRecordStore()
        runtime = _build_runtime(store)
        self.assertIsInstance(runtime.snapshot_store, InMemorySnapshotStore)

    def test_governed_path_persists_snapshot_and_executes(self) -> None:
        record_store = ActionRecordStore()
        runtime = _build_runtime(record_store)

        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        # The connector executed a real write.
        self.assertFalse(result.action_proposal.approval_required)
        self.assertEqual(result.action_result.get("status"), "executed")
        self.assertEqual(len(record_store.records()), 1)

        # A snapshot was taken AND persisted in the snapshot_store.
        self.assertIsNotNone(result.state_snapshot)
        persisted = runtime.snapshot_store.get(result.state_snapshot.snapshot_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.connector_name, "action_record")

    def test_runtime_rollback_restores_store(self) -> None:
        record_store = ActionRecordStore()
        runtime = _build_runtime(record_store)

        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )
        snapshot_id = result.state_snapshot.snapshot_id
        self.assertEqual(len(record_store.records()), 1)

        rollback_result = runtime.rollback(snapshot_id)
        self.assertEqual(rollback_result["status"], "rolled_back")
        # Snapshot was taken BEFORE the execute write, so rollback empties the store.
        self.assertEqual(len(record_store.records()), 0)

    def test_rollback_unknown_snapshot_raises_keyerror(self) -> None:
        runtime = _build_runtime(ActionRecordStore())
        with self.assertRaises(KeyError):
            runtime.rollback("snapshot-does-not-exist")

    def test_governed_path_blocks_when_dry_run_fails(self) -> None:
        record_store = ActionRecordStore()
        runtime = _build_runtime(
            record_store,
            connector=_FailingDryRunActionRecordConnector(store=record_store),
        )

        with self.assertRaisesRegex(ValueError, "dry-run failed"):
            runtime.run("最近7天GMV是多少？", _run_params())

        self.assertEqual(record_store.records(), ())

    def test_governed_path_blocks_when_required_snapshot_missing(self) -> None:
        record_store = ActionRecordStore()
        runtime = _build_runtime(
            record_store,
            connector=_NoSnapshotActionRecordConnector(store=record_store),
        )

        with self.assertRaisesRegex(ValueError, "required snapshot"):
            runtime.run("最近7天GMV是多少？", _run_params())

        self.assertEqual(record_store.records(), ())

    def test_approval_resume_executes_only_after_approval(self) -> None:
        record_store = ActionRecordStore()
        runtime = _build_approval_runtime(record_store)
        result = runtime.run("最近7天GMV是多少？", _run_params())

        self.assertIsNotNone(result.approval_record)
        self.assertEqual(result.approval_record.status, "pending")
        self.assertEqual(record_store.records(), ())

        runtime.approval_runtime.approve(result.approval_record.approval_id, reason="approved test")
        operation_trace = runtime.execute_approved_operation(
            approval_id=result.approval_record.approval_id,
            operation=result.operation_contract,
            action_parameters=result.action_proposal.action_parameters,
            evidence_chain=result.evidence_chain,
            proposal_id=result.action_proposal.proposal_id,
        )

        self.assertEqual(len(record_store.records()), 1)
        self.assertEqual(operation_trace.state, OperationState.EXECUTED)
        self.assertEqual(
            [event["step"] for event in operation_trace.events],
            [
                "proposed",
                "approved",
                "connector_dry_run",
                "state_snapshot",
                "connector_executed",
            ],
        )

    def test_approval_resume_rejects_r4_r5_business_actions_in_mvp(self) -> None:
        record_store = ActionRecordStore()
        runtime = _build_r4_runtime(record_store)
        result = runtime.run("最近7天GMV是多少？", _run_params())
        runtime.approval_runtime.approve(result.approval_record.approval_id, reason="approved")

        with self.assertRaisesRegex(ValueError, "R4/R5 business actions are proposal-only"):
            runtime.execute_approved_operation(
                approval_id=result.approval_record.approval_id,
                operation=result.operation_contract,
                action_parameters=result.action_proposal.action_parameters,
                evidence_chain=result.evidence_chain,
                proposal_id=result.action_proposal.proposal_id,
            )

        self.assertEqual(record_store.records(), ())

    def test_approval_resume_rejects_pending_rejected_and_mismatched_approval(self) -> None:
        record_store = ActionRecordStore()
        runtime = _build_approval_runtime(record_store)
        pending = runtime.run("最近7天GMV是多少？", _run_params())

        with self.assertRaises(ValueError):
            runtime.execute_approved_operation(
                approval_id=pending.approval_record.approval_id,
                operation=pending.operation_contract,
                action_parameters=pending.action_proposal.action_parameters,
                evidence_chain=pending.evidence_chain,
                proposal_id=pending.action_proposal.proposal_id,
            )

        rejected = runtime.run("最近7天GMV是多少？", _run_params())
        runtime.approval_runtime.reject(rejected.approval_record.approval_id, reason="no")
        with self.assertRaises(ValueError):
            runtime.execute_approved_operation(
                approval_id=rejected.approval_record.approval_id,
                operation=rejected.operation_contract,
                action_parameters=rejected.action_proposal.action_parameters,
                evidence_chain=rejected.evidence_chain,
                proposal_id=rejected.action_proposal.proposal_id,
            )

        approved = runtime.run("最近7天GMV是多少？", _run_params())
        runtime.approval_runtime.approve(approved.approval_record.approval_id)
        with self.assertRaises(ValueError):
            runtime.execute_approved_operation(
                approval_id=approved.approval_record.approval_id,
                operation=approved.operation_contract,
                action_parameters=approved.action_proposal.action_parameters,
                evidence_chain=approved.evidence_chain,
                proposal_id="proposal-mismatch",
            )
        self.assertEqual(record_store.records(), ())

    def test_approval_resume_rejects_operation_not_bound_to_proposal(self) -> None:
        record_store = ActionRecordStore()
        runtime = _build_approval_runtime(record_store)
        result = runtime.run("最近7天GMV是多少？", _run_params())
        runtime.approval_runtime.approve(result.approval_record.approval_id)
        tampered_operation = replace(
            result.operation_contract,
            operation_id="operation-other-proposal",
        )

        with self.assertRaisesRegex(ValueError, "operation-proposal mismatch"):
            runtime.execute_approved_operation(
                approval_id=result.approval_record.approval_id,
                operation=tampered_operation,
                action_parameters=result.action_proposal.action_parameters,
                evidence_chain=result.evidence_chain,
                proposal_id=result.action_proposal.proposal_id,
            )

        self.assertEqual(record_store.records(), ())

    def test_approval_resume_rejects_action_parameters_not_bound_to_approval(self) -> None:
        record_store = ActionRecordStore()
        runtime = _build_approval_runtime(record_store)
        result = runtime.run("最近7天GMV是多少？", _run_params())
        runtime.approval_runtime.approve(result.approval_record.approval_id)

        with self.assertRaisesRegex(ValueError, "operation-approval mismatch"):
            runtime.execute_approved_operation(
                approval_id=result.approval_record.approval_id,
                operation=result.operation_contract,
                action_parameters={"amount": 999999},
                evidence_chain=result.evidence_chain,
                proposal_id=result.action_proposal.proposal_id,
            )

        self.assertEqual(record_store.records(), ())

    def test_approval_resume_rejects_missing_approval_fingerprint(self) -> None:
        record_store = ActionRecordStore()
        runtime = _build_approval_runtime(record_store)
        result = runtime.run("最近7天GMV是多少？", _run_params())
        legacy_approval = runtime.approval_runtime.create_pending(
            approval_id="approval-legacy",
            proposal_id=result.action_proposal.proposal_id,
            approver_role="Business Owner",
        )
        runtime.approval_runtime.approve(legacy_approval.approval_id)

        with self.assertRaisesRegex(ValueError, "operation approval fingerprint is missing"):
            runtime.execute_approved_operation(
                approval_id=legacy_approval.approval_id,
                operation=result.operation_contract,
                action_parameters=result.action_proposal.action_parameters,
                evidence_chain=result.evidence_chain,
                proposal_id=result.action_proposal.proposal_id,
            )

        self.assertEqual(record_store.records(), ())

    def test_approval_resume_rejects_evidence_not_bound_to_approval(self) -> None:
        record_store = ActionRecordStore()
        runtime = _build_approval_runtime(record_store)
        result = runtime.run("最近7天GMV是多少？", _run_params())
        runtime.approval_runtime.approve(result.approval_record.approval_id)
        tampered_evidence = replace(
            result.evidence_chain,
            evidence_chain_id="evidence-other-proposal",
        )

        with self.assertRaisesRegex(ValueError, "operation-approval mismatch"):
            runtime.execute_approved_operation(
                approval_id=result.approval_record.approval_id,
                operation=result.operation_contract,
                action_parameters=result.action_proposal.action_parameters,
                evidence_chain=tampered_evidence,
                proposal_id=result.action_proposal.proposal_id,
            )

        self.assertEqual(record_store.records(), ())

    def test_approval_resume_updates_persisted_run_trace(self) -> None:
        record_store = ActionRecordStore()
        runtime = _build_approval_runtime(record_store)
        result = runtime.run("最近7天GMV是多少？", _run_params())
        runtime.approval_runtime.approve(result.approval_record.approval_id)

        runtime.execute_approved_operation(
            approval_id=result.approval_record.approval_id,
            operation=result.operation_contract,
            action_parameters=result.action_proposal.action_parameters,
            evidence_chain=result.evidence_chain,
            proposal_id=result.action_proposal.proposal_id,
        )

        stored = runtime.trace_store.get(result.evidence_chain.trace_id)
        self.assertIsNotNone(stored)
        self.assertIn(
            "approved_operation_trace",
            [event.step for event in stored.events],
        )

    def test_approval_resume_persists_external_uncertain_audit_without_raw_payloads(self) -> None:
        runtime = _build_external_approval_runtime()
        result = runtime.run("最近7天GMV是多少？", _run_params())
        runtime.approval_runtime.approve(result.approval_record.approval_id)

        with self.assertRaises(_ExternalWebhookAckLost):
            runtime.execute_approved_operation(
                approval_id=result.approval_record.approval_id,
                operation=result.operation_contract,
                action_parameters=result.action_proposal.action_parameters,
                evidence_chain=result.evidence_chain,
                proposal_id=result.action_proposal.proposal_id,
            )

        stored = runtime.trace_store.get(result.evidence_chain.trace_id)
        self.assertIsNotNone(stored)
        uncertain = next(
            event.payload["operation_event"]
            for event in stored.events
            if event.step == "approved_operation_trace"
            and event.payload["operation_event"]["step"] == "connector_execution_uncertain"
        )
        self.assertEqual(uncertain["connector_name"], "external_webhook")
        self.assertEqual(uncertain["external_request_id"], "ext-req-uncertain")
        self.assertEqual(uncertain["durability_scope"], "external_connector")
        self.assertEqual(uncertain["external_ack_status"], "unknown")
        self.assertEqual(uncertain["replay_status"], "not_replayed")
        self.assertEqual(uncertain["ledger_status"], "connector_reported")
        self.assertNotIn("secret_token", uncertain)
        self.assertNotIn("raw_parameters", uncertain)

    def test_approved_action_rollback_demo_restores_store(self) -> None:
        record_store = ActionRecordStore()
        runtime = _build_approval_runtime(record_store)
        result = runtime.run("最近7天GMV是多少？", _run_params())
        runtime.approval_runtime.approve(result.approval_record.approval_id)

        operation_trace = runtime.execute_approved_operation(
            approval_id=result.approval_record.approval_id,
            operation=result.operation_contract,
            action_parameters=result.action_proposal.action_parameters,
            evidence_chain=result.evidence_chain,
            proposal_id=result.action_proposal.proposal_id,
        )
        self.assertEqual(len(record_store.records()), 1)

        rollback_result = runtime.rollback(_snapshot_id_from_trace_events(operation_trace.events))
        self.assertEqual(rollback_result["status"], "rolled_back")
        self.assertEqual(record_store.records(), ())


if __name__ == "__main__":
    unittest.main()
