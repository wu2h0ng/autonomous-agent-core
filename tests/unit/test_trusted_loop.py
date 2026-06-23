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
    ActionProposal,
    LifecycleState,
    MetricContract,
    OperationContract,
    OperationState,
    ProviderContract,
    ProviderKind,
    RiskLevel,
    SQLTemplate,
    TelemetryDimension,
)
from agent_os_core import ProviderRegistry, SemanticRegistry, TrustedLoopRuntime  # noqa: E402
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from action_record import ActionRecordConnector, ActionRecordStore  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402


def _build_default_connector_registry() -> ActionConnectorRegistry:
    """Build a connector registry with ManualReviewConnector.

    Caller-side construction: OS Core never imports action connectors.
    """
    registry = ActionConnectorRegistry()
    connector = ManualReviewConnector()
    contract = ActionConnectorContract(
        connector_name="manual_review",
        display_name="Manual Review",
        supported_action_types=("propose", "execute"),
        supports_snapshot=False,
        supports_rollback=False,
        compensating_action_description=None,
        risk_ceiling="R5",
        owner="system",
    )
    registry.register(connector, contract)
    return registry


class _ExecutionSpyConnector(ManualReviewConnector):
    """A connector that records whether execute() was invoked.

    Registered under the ``manual_review`` name so it routes normally. When
    ``raise_on_execute`` is True (default) it raises if execute() is called,
    making it a hard regression guard for the approval gate.
    """

    def __init__(self, raise_on_execute: bool = True) -> None:
        self.execute_called = False
        self._raise_on_execute = raise_on_execute

    def execute(self, operation, parameters):  # type: ignore[override]
        self.execute_called = True
        if self._raise_on_execute:
            raise AssertionError(
                "connector.execute() must not be called for approval_required operations"
            )
        return super().execute(operation, parameters)


class _FlakyDryRunActionRecordConnector(ActionRecordConnector):
    """Fails the first dry-run, then behaves like the real action_record connector."""

    def __init__(self, *, store: ActionRecordStore) -> None:
        super().__init__(store=store)
        self._failures_remaining = 1

    def dry_run(self, operation, parameters):  # type: ignore[override]
        if self._failures_remaining > 0:
            self._failures_remaining -= 1
            return {
                "status": "failed",
                "connector_name": self.connector_name,
                "operation_id": operation.operation_id,
                "reason": "simulated transient dry-run failure",
            }
        return super().dry_run(operation, parameters)


class _ExternalWebhookConnector(ManualReviewConnector):
    @property
    def connector_name(self) -> str:  # type: ignore[override]
        return "external_webhook"

    def execute(self, operation, parameters):  # type: ignore[override]
        return {
            "status": "accepted",
            "external_request_id": "ext-req-1",
            "durability_scope": "external_connector",
            "replay_status": "not_replayed",
            "ledger_status": "connector_reported",
            "secret_token": parameters.get("secret_token"),
            "raw_parameters": dict(parameters),
        }


class _ExternalWebhookActionBuilder:
    def build(self, *, proposal_id: str, evidence):  # type: ignore[no-untyped-def]
        return ActionProposal(
            proposal_id=proposal_id,
            evidence_chain_id=evidence.evidence_chain_id,
            target_object=evidence.metric_contract.metric_name,
            recommended_action="Submit the governed action to an external connector.",
            reason=evidence.conclusion,
            risk_level=RiskLevel.R2,
            expected_impact="Exercise external connector audit semantics.",
            approval_required=False,
            approver_role=None,
            connector_name="external_webhook",
            action_type="execute",
            action_parameters={
                "customer_id": "cust-1",
                "secret_token": "must-not-leak",
            },
        )


def _build_spy_connector_registry(spy: _ExecutionSpyConnector) -> ActionConnectorRegistry:
    """Register the spy under the ``manual_review`` routing name."""
    registry = ActionConnectorRegistry()
    contract = ActionConnectorContract(
        connector_name="manual_review",
        display_name="Manual Review",
        supported_action_types=("propose", "execute"),
        supports_snapshot=False,
        supports_rollback=False,
        compensating_action_description=None,
        risk_ceiling="R5",
        owner="system",
    )
    registry.register(spy, contract)
    return registry


def _build_action_record_connector_registry(
    store: ActionRecordStore,
    *,
    connector: ActionRecordConnector | None = None,
) -> ActionConnectorRegistry:
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
        connector or ActionRecordConnector(store=store),
        ActionConnectorContract(
            connector_name="action_record",
            display_name="Action Record",
            supported_action_types=("execute",),
            supports_snapshot=True,
            supports_rollback=True,
            compensating_action_description=(
                "Restore the action record store to the pre-execution snapshot state"
            ),
            risk_ceiling="R3",
            owner="system",
        ),
    )
    return registry


def _build_external_webhook_connector_registry() -> ActionConnectorRegistry:
    registry = ActionConnectorRegistry()
    registry.register(
        _ExternalWebhookConnector(),
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


class TrustedLoopRuntimeTest(unittest.TestCase):
    def test_runs_minimum_trusted_loop(self) -> None:
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
            query_executor=StaticQueryExecutor(
                [
                    {"order_date": "2026-05-31", "gmv": 128800.0},
                ]
            ),
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
            connector_registry=_build_default_connector_registry(),
        )

        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        self.assertEqual(result.intent.metric_name, "gmv")
        self.assertTrue(result.evidence_chain.is_complete())
        self.assertIsNotNone(result.provider_contract)
        self.assertEqual(result.provider_contract.provider_id, "provider-sales")
        self.assertIsNotNone(result.data_requirement)
        self.assertEqual(result.data_requirement.metric_names, ("gmv",))
        self.assertIsNotNone(result.lineage_snapshot)
        self.assertEqual(result.lineage_snapshot.provider_id, "provider-sales")
        self.assertIsNotNone(result.data_product_candidate)
        self.assertEqual(result.action_proposal.risk_level, RiskLevel.R2)
        self.assertFalse(result.action_proposal.approval_required)
        self.assertEqual(
            [event.step for event in result.trace_events],
            [
                "intent",
                "semantic_resolution",
                "query_plan",
                "sql_safety",
                "query_result",
                "data_product_candidate",
                "evidence_chain",
                "action_proposal",
                "operation_contract",
                "connector_dry_run",
                "connector_execute",
                "knowledge_asset_candidate",
            ],
        )
        telemetry_dimensions = {event.dimension for event in result.telemetry_events}
        self.assertIn(TelemetryDimension.BUSINESS, telemetry_dimensions)
        self.assertIn(TelemetryDimension.QUALITY, telemetry_dimensions)
        self.assertIn(TelemetryDimension.COST, telemetry_dimensions)
        self.assertIn(TelemetryDimension.SYSTEM, telemetry_dimensions)
        self.assertTrue(
            any(event.name == "evidence_chain.complete" for event in result.telemetry_events)
        )


class TrustedLoopGovernanceTest(unittest.TestCase):
    """Integration tests for the governance/connector/approval/trace pipeline."""

    def _build_runtime(
        self,
        rows: list[dict] | None = None,
        connector_registry: ActionConnectorRegistry | None = None,
    ) -> TrustedLoopRuntime:
        """Helper to build a runtime with sensible defaults for governance tests."""
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
        kwargs: dict = {
            "metric_contract": metric,
            "sql_template": template,
            "query_executor": StaticQueryExecutor(
                rows if rows is not None else [{"order_date": "2026-05-31", "gmv": 128800.0}]
            ),
            "semantic_registry": SemanticRegistry(metric_contracts=(metric,)),
            "provider_registry": ProviderRegistry(
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
        }
        if connector_registry is not None:
            kwargs["connector_registry"] = connector_registry
        else:
            kwargs["connector_registry"] = _build_default_connector_registry()
        return TrustedLoopRuntime(**kwargs)

    def test_trusted_loop_with_governance(self) -> None:
        """Full pipeline: intent → governance → state machine → connector → trace."""
        runtime = self._build_runtime()
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        # operation_contract should be populated
        self.assertIsNotNone(result.operation_contract)
        self.assertIsInstance(result.operation_contract, OperationContract)
        self.assertEqual(result.operation_contract.connector_name, "manual_review")

        # action_result should contain status
        self.assertIsNotNone(result.action_result)
        self.assertIsInstance(result.action_result, dict)
        self.assertIn("status", result.action_result)

        # trace_events should contain operation_contract and connector_execute steps
        trace_steps = [event.step for event in result.trace_events]
        self.assertIn("operation_contract", trace_steps)
        self.assertIn("connector_execute", trace_steps)

        # Verify the operation_contract step has the right info
        op_trace_event = next(e for e in result.trace_events if e.step == "operation_contract")
        self.assertEqual(op_trace_event.payload["connector_name"], "manual_review")

        # Verify the connector_execute step has the right info
        exec_trace_event = next(e for e in result.trace_events if e.step == "connector_execute")
        self.assertEqual(exec_trace_event.payload["connector_name"], "manual_review")
        self.assertIn("status", exec_trace_event.payload)

    def test_governance_with_high_risk_triggers_approval(self) -> None:
        """High risk (row_count=0) should trigger approval_required and create pending record."""
        runtime = self._build_runtime(rows=[])
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        # High risk => approval_required
        self.assertTrue(result.action_proposal.approval_required)
        self.assertIsNotNone(result.approval_record)
        self.assertEqual(result.approval_record.status, "pending")

    def test_approval_required_halts_before_execution(self) -> None:
        """Governance gate: approval_required operations MUST NOT call the
        side-effecting connector.execute() before human approval.

        This is hard boundary #4 (R4/R5 proposal-only) and the core of
        Governed Operation. The loop must halt at AWAITING_APPROVAL.

        Regression guard: the spy connector raises if execute() is invoked,
        so this test fails if the loop bypasses the approval gate.
        """
        spy = _ExecutionSpyConnector()
        runtime = self._build_runtime(
            rows=[],  # row_count=0 => high risk => approval_required
            connector_registry=_build_spy_connector_registry(spy),
        )
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        # The proposal is approval-required...
        self.assertTrue(result.action_proposal.approval_required)
        # ...so the connector's side-effecting execute() must NOT have been called.
        self.assertFalse(
            spy.execute_called,
            "connector.execute() was called for an approval_required operation",
        )
        # A pending approval must be recorded (human responsibility entry point).
        self.assertIsNotNone(result.approval_record)
        self.assertEqual(result.approval_record.status, "pending")
        # The loop halts at awaiting_approval, not connector_execute.
        trace_steps = [event.step for event in result.trace_events]
        self.assertIn("awaiting_approval", trace_steps)
        self.assertNotIn("connector_execute", trace_steps)
        # The result reports the halted status rather than an execution result.
        self.assertIsNotNone(result.action_result)
        self.assertEqual(result.action_result.get("status"), "awaiting_approval")

    def test_loop_emits_knowledge_asset_candidate(self) -> None:
        """The Trusted Loop must close the back half: every run emits a
        KnowledgeAsset candidate (DRAFT) derived from the evidence chain,
        bound to the run's trace. This is the moat — proof the loop does not
        stop at proposal/execution but sediments a reusable knowledge asset.
        """
        runtime = self._build_runtime()
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        candidate = result.knowledge_asset_candidate
        self.assertIsNotNone(candidate, "loop did not emit a knowledge_asset_candidate")
        # Bound to this run's trace (evidence shares the same trace_id).
        self.assertEqual(candidate.source_trace_id, result.evidence_chain.trace_id)
        # Candidate, not published.
        self.assertEqual(candidate.state, LifecycleState.DRAFT)
        # Title reflects the metric under analysis.
        self.assertIn("gmv", candidate.title.lower())

    def test_result_includes_operation_trace(self) -> None:
        """The end-to-end OperationTrace must be returned in the result, not
        built and discarded. It is the audit/replay record of the operation."""
        runtime = self._build_runtime()
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        op_trace = result.operation_trace
        self.assertIsNotNone(op_trace, "result did not include operation_trace")
        self.assertEqual(op_trace.evidence_chain_id, result.evidence_chain.evidence_chain_id)
        self.assertEqual(op_trace.proposal_id, result.action_proposal.proposal_id)
        # Non-approval (R2) path executes -> trace lands in EXECUTED.
        self.assertEqual(op_trace.state, OperationState.EXECUTED)

    def test_operation_trace_reflects_awaiting_approval(self) -> None:
        """For approval-required operations the returned trace must reflect the
        halted AWAITING_APPROVAL state (not EXECUTED)."""
        runtime = self._build_runtime(rows=[])  # high risk => approval_required
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )
        self.assertIsNotNone(result.operation_trace)
        self.assertEqual(result.operation_trace.state, OperationState.AWAITING_APPROVAL)

    def test_record_outcome_creates_feedback_without_promoting_knowledge(self) -> None:
        """Post-outcome self-report: observing an outcome (1) creates and stores a
        real FeedbackEvent bound to the trace, but P5.1b (anti-wirehead, AR-20260614)
        it (2) does NOT promote the trace's KnowledgeAsset. Knowledge promotion is
        reserved for realized external value (promote_from_adoption / adoption channel)."""
        runtime = self._build_runtime()
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )
        trace_id = result.evidence_chain.trace_id
        self.assertEqual(runtime.knowledge_store.version_of(trace_id), 1)

        feedback = runtime.record_outcome(
            trace_id=trace_id,
            outcome="adopted",
            reviewer="ops_lead",
            metric_deltas={"gmv": 1200.0},
        )

        # (1) real feedback, stored and bound to the trace
        self.assertEqual(feedback.outcome, "adopted")
        self.assertEqual(feedback.trace_id, trace_id)
        self.assertEqual(feedback.reviewer, "ops_lead")
        self.assertIn(feedback, runtime.feedback_store.get_by_trace(trace_id))

        # (2) knowledge NOT promoted by a self-report (wirehead closed): version stays 1
        self.assertEqual(runtime.knowledge_store.version_of(trace_id), 1)

    def test_record_outcome_requires_known_trace_for_knowledge_update(self) -> None:
        """Recording an outcome for an unknown trace still produces feedback but
        does not fabricate a knowledge asset out of nothing."""
        runtime = self._build_runtime()
        feedback = runtime.record_outcome(trace_id="trace-unknown", outcome="rejected")
        self.assertEqual(feedback.trace_id, "trace-unknown")
        self.assertIsNone(runtime.knowledge_store.get_by_trace("trace-unknown"))
        self.assertEqual(runtime.knowledge_store.version_of("trace-unknown"), 0)

    def test_non_approval_operation_executes(self) -> None:
        """Counterpart to the gate test: low/medium-risk, no-approval operations
        DO proceed through governed execution and call the connector."""
        spy = _ExecutionSpyConnector(raise_on_execute=False)
        runtime = self._build_runtime(
            rows=[{"order_date": "2026-05-31", "gmv": 128800.0}],  # non-empty => R2, no approval
            connector_registry=_build_spy_connector_registry(spy),
        )
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        self.assertFalse(result.action_proposal.approval_required)
        self.assertTrue(spy.execute_called)
        trace_steps = [event.step for event in result.trace_events]
        self.assertIn("connector_execute", trace_steps)
        self.assertNotIn("awaiting_approval", trace_steps)

    def test_external_connector_execution_audit_uses_safe_reported_fields_only(self) -> None:
        runtime = self._build_runtime(
            rows=[{"order_date": "2026-05-31", "gmv": 128800.0}],
            connector_registry=_build_external_webhook_connector_registry(),
        )
        runtime.action_builder = _ExternalWebhookActionBuilder()

        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        self.assertEqual(result.operation_trace.state, OperationState.EXECUTED)
        execute_event = next(
            event
            for event in result.operation_trace.events
            if event["step"] == "connector_executed"
        )
        self.assertEqual(execute_event["connector_name"], "external_webhook")
        self.assertEqual(execute_event["status"], "accepted")
        self.assertEqual(execute_event["durability_scope"], "external_connector")
        self.assertEqual(execute_event["external_request_id"], "ext-req-1")
        self.assertEqual(execute_event["external_ack_status"], "unknown")
        self.assertEqual(execute_event["replay_status"], "not_replayed")
        self.assertEqual(execute_event["ledger_status"], "connector_reported")
        self.assertNotIn("secret_token", execute_event)
        self.assertNotIn("raw_parameters", execute_event)

    def test_explicit_action_record_intent_routes_to_real_connector_after_approval(self) -> None:
        """A user-visible action request routes to a real reversible connector,
        but remains approval-bound until the operator approves it."""
        store = ActionRecordStore()
        runtime = self._build_runtime(
            rows=[{"order_date": "2026-05-31", "gmv": 128800.0}],
            connector_registry=_build_action_record_connector_registry(store),
        )
        result = runtime.run(
            "记录行动：基于最近7天GMV创建一个跟进行动",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        self.assertEqual(result.action_proposal.connector_name, "action_record")
        self.assertEqual(result.action_proposal.action_type, "execute")
        self.assertEqual(result.action_proposal.risk_level, RiskLevel.R3)
        self.assertTrue(result.action_proposal.approval_required)
        self.assertEqual(result.action_proposal.action_parameters["metric_name"], "gmv")
        self.assertEqual(result.operation_contract.connector_name, "action_record")
        self.assertTrue(result.operation_contract.approval_required)
        self.assertTrue(result.operation_contract.snapshot_required)
        self.assertTrue(result.operation_contract.rollback_supported)
        self.assertEqual(result.action_result["status"], "awaiting_approval")
        self.assertEqual(store.records(), ())
        self.assertNotIn("connector_execute", [event.step for event in result.trace_events])

        self.assertIsNotNone(result.approval_record)
        runtime.approval_runtime.approve(result.approval_record.approval_id, reason="approved")
        operation_trace = runtime.execute_approved_operation(
            approval_id=result.approval_record.approval_id,
            operation=result.operation_contract,
            action_parameters=result.action_proposal.action_parameters,
            evidence_chain=result.evidence_chain,
            proposal_id=result.action_proposal.proposal_id,
        )

        self.assertEqual(operation_trace.state, OperationState.EXECUTED)
        self.assertEqual(len(store.records()), 1)
        self.assertEqual(store.records()[0]["action_type"], "execute")
        self.assertEqual(
            store.records()[0]["parameters"]["evidence_chain_id"],
            result.evidence_chain.evidence_chain_id,
        )

    def test_pending_action_context_executes_after_approval_without_client_replay(self) -> None:
        """Approval resume should not require clients to replay operation/evidence payloads."""
        store = ActionRecordStore()
        runtime = self._build_runtime(
            rows=[{"order_date": "2026-05-31", "gmv": 128800.0}],
            connector_registry=_build_action_record_connector_registry(store),
        )
        result = runtime.run(
            "记录行动：基于最近7天GMV创建一个跟进行动",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )
        approval_id = result.approval_record.approval_id

        runtime.approval_runtime.approve(approval_id, reason="approved")
        operation_trace = runtime.execute_pending_approved_operation(approval_id=approval_id)

        self.assertEqual(operation_trace.state, OperationState.EXECUTED)
        self.assertEqual(len(store.records()), 1)
        self.assertEqual(
            store.records()[0]["parameters"]["evidence_chain_id"],
            result.evidence_chain.evidence_chain_id,
        )
        with self.assertRaises(KeyError):
            runtime.execute_pending_approved_operation(approval_id=approval_id)

    def test_approved_pending_action_remains_retryable_after_dry_run_failure(self) -> None:
        """A connector failure after approval must not consume the pending context."""
        store = ActionRecordStore()
        runtime = self._build_runtime(
            rows=[{"order_date": "2026-05-31", "gmv": 128800.0}],
            connector_registry=_build_action_record_connector_registry(
                store,
                connector=_FlakyDryRunActionRecordConnector(store=store),
            ),
        )
        result = runtime.run(
            "记录行动：基于最近7天GMV创建一个跟进行动",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )
        approval_id = result.approval_record.approval_id

        with self.assertRaisesRegex(ValueError, "dry-run failed"):
            runtime.approve_and_execute_pending_operation(
                approval_id=approval_id,
                reason="approved by operator",
                approved_by="ops@example.com",
            )

        approval = runtime.approval_runtime.get(approval_id)
        self.assertEqual(approval.status, "approved")
        self.assertEqual(approval.approved_by, "ops@example.com")
        self.assertEqual(store.records(), ())

        _approval, operation_trace = runtime.approve_and_execute_pending_operation(
            approval_id=approval_id,
            reason="retry after connector recovery",
            approved_by="ops@example.com",
        )

        self.assertEqual(operation_trace.state, OperationState.EXECUTED)
        self.assertEqual(len(store.records()), 1)
        self.assertEqual(
            store.records()[0]["parameters"]["evidence_chain_id"],
            result.evidence_chain.evidence_chain_id,
        )
        with self.assertRaises(KeyError):
            runtime.execute_pending_approved_operation(approval_id=approval_id)

    def test_nonexistent_connector_raises_keyerror(self) -> None:
        """Requesting a nonexistent connector should raise KeyError."""
        from agent_os_contracts import ActionProposal, EvidenceChain

        # Build a custom ActionProposalBuilder that produces proposals
        # with connector_name="nonexistent"
        class _NonexistentProposalBuilder:
            def build(self, *, proposal_id: str, evidence: EvidenceChain) -> ActionProposal:
                if evidence.query_result.row_count == 0:
                    risk_level = RiskLevel.R3
                    approval_required = True
                    approver_role = "Business Owner"
                    action_type = "execute"
                else:
                    risk_level = RiskLevel.R2
                    approval_required = False
                    approver_role = None
                    action_type = "propose"
                return ActionProposal(
                    proposal_id=proposal_id,
                    evidence_chain_id=evidence.evidence_chain_id,
                    target_object=evidence.metric_contract.metric_name,
                    recommended_action="test",
                    reason=evidence.conclusion,
                    risk_level=risk_level,
                    expected_impact="test",
                    approval_required=approval_required,
                    approver_role=approver_role,
                    connector_name="nonexistent",
                    action_type=action_type,
                    action_parameters={},
                )

        metric = MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="Gross merchandise value.",
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

        # Use an empty registry — no connectors registered at all
        empty_registry = ActionConnectorRegistry()

        runtime = TrustedLoopRuntime(
            metric_contract=metric,
            sql_template=template,
            query_executor=StaticQueryExecutor([{"gmv": 100}]),
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
            connector_registry=empty_registry,
        )
        # Override the action_builder to produce proposals with nonexistent connector
        runtime.action_builder = _NonexistentProposalBuilder()  # type: ignore[assignment]

        with self.assertRaises(KeyError):
            runtime.run(
                "最近7天GMV是多少？",
                {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
            )

    def test_connector_registry_required(self) -> None:
        """The runtime must raise ValueError if connector_registry is not provided.

        OS Core must not import action connectors, so the caller is responsible
        for constructing and injecting the registry.
        """
        metric = MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="Gross merchandise value.",
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
        with self.assertRaises(ValueError) as ctx:
            TrustedLoopRuntime(
                metric_contract=metric,
                sql_template=template,
                query_executor=StaticQueryExecutor([{"gmv": 100}]),
                connector_registry=None,
            )
        self.assertIn("connector_registry is required", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
