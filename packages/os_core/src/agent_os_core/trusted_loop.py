from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from agent_os_contracts import (
    ActionConnectorContract,
    BusinessIntent,
    MetricContract,
    OperationState,
    ProviderContract,
    ProviderKind,
    QueryPlan,
    SQLTemplate,
    StateSnapshot,
    TelemetryDimension,
    TrustedLoopResult,
)

from .action_connectors.registry import ActionConnectorRegistry
from .action_governance import ActionGovernance
from .action_proposal import ActionProposalBuilder
from .approval_lite import ApprovalLiteRuntime
from .data_access_plane import ProviderRegistry
from .data_product_compiler import DataProductCompiler
from .evidence_chain import EvidenceChainBuilder
from .intent_parser import IntentParser
from .operation_state_machine import OperationStateMachine
from .operation_trace import OperationTraceBuilder
from .query_runtime import StaticQueryExecutor
from .semantic_runtime import SemanticRegistry
from .sql_safety import SQLSafetyChecker
from .trace import TraceRecorder


class TrustedLoopRuntime:
    """Orchestrates the Trusted Loop: from business question to action execution.

    In the MVP, the runtime coordinates:
    - Intent parsing & semantic resolution (unchanged)
    - SQL safety checking & query execution (unchanged)
    - Action proposal building (extended with connector_name/action_type)
    - Operation governance & contract building (new)
    - State machine transitions (new)
    - Connector-based execution via the registry (new)
    - Approval lifecycle management (new)
    - Operation trace building (extended)
    """

    def __init__(
        self,
        *,
        metric_contract: MetricContract,
        sql_template: SQLTemplate,
        query_executor: StaticQueryExecutor,
        intent_parser: IntentParser | None = None,
        semantic_registry: SemanticRegistry | None = None,
        provider_registry: ProviderRegistry | None = None,
        data_product_compiler: DataProductCompiler | None = None,
        action_governance: ActionGovernance | None = None,
        connector_registry: ActionConnectorRegistry | None = None,
        approval_runtime: ApprovalLiteRuntime | None = None,
        operation_trace_builder: OperationTraceBuilder | None = None,
        state_machine: OperationStateMachine | None = None,
    ) -> None:
        self.metric_contract = metric_contract
        self.sql_template = sql_template
        self.query_executor = query_executor
        self.intent_parser = intent_parser or IntentParser()
        self.semantic_registry = semantic_registry or SemanticRegistry(
            metric_contracts=(metric_contract,)
        )
        default_provider = ProviderContract(
            provider_id="provider-default",
            kind=ProviderKind.WAREHOUSE,
            name="default",
            owner=metric_contract.owner,
            allowed_schemas=metric_contract.allowed_schemas,
        )
        self.provider_registry = provider_registry or ProviderRegistry((default_provider,))
        self.data_product_compiler = data_product_compiler or DataProductCompiler()
        self.evidence_builder = EvidenceChainBuilder()
        self.action_builder = ActionProposalBuilder()

        # --- New dependencies (with defaults for backward compatibility) ---
        self.connector_registry = connector_registry or self._build_default_registry()
        self.action_governance = action_governance or ActionGovernance(
            connector_registry=self.connector_registry
        )
        self.approval_runtime = approval_runtime or ApprovalLiteRuntime()
        self.operation_trace_builder = operation_trace_builder or OperationTraceBuilder()
        self.state_machine = state_machine or OperationStateMachine()

    @staticmethod
    def _build_default_registry() -> ActionConnectorRegistry:
        """Build a default connector registry with ManualReviewConnector registered.

        The import is deferred to avoid os_core importing from action_connectors/
        at module level (boundary rule).  Instead, ManualReviewConnector is
        imported only when a default registry is needed.
        """
        from manual_review import ManualReviewConnector

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

    def run(self, question: str, parameters: dict[str, object]) -> TrustedLoopResult:
        started_at = perf_counter()
        trace_id = f"trace-{uuid4().hex[:12]}"
        trace = TraceRecorder(trace_id)
        trace.metric(
            dimension=TelemetryDimension.BUSINESS,
            name="trusted_loop.run_started",
            value=1,
            unit="count",
        )

        intent = self._parse_intent(question)
        trace.record("intent", {"intent_id": intent.intent_id, "metric": intent.metric_name})

        metric_contract = self.semantic_registry.resolve_metric(intent.metric_name)
        provider_contract = self.provider_registry.choose_for_schemas(
            metric_contract.allowed_schemas
        )
        trace.record(
            "semantic_resolution",
            {
                "metric": metric_contract.metric_name,
                "provider_id": provider_contract.provider_id,
            },
        )

        query_plan = QueryPlan(
            metric_name=metric_contract.metric_name,
            sql=self.sql_template.sql,
            parameters=parameters,
        )
        trace.record("query_plan", {"metric": query_plan.metric_name})

        sql_safety = SQLSafetyChecker(metric_contract.allowed_schemas)
        safety = sql_safety.check(
            self.sql_template.sql,
            self.sql_template.required_parameters,
            parameters,
            required_time_parameters=self.sql_template.required_time_parameters,
            max_limit=self.sql_template.max_limit,
            allow_select_star=self.sql_template.allow_select_star,
        )
        trace.record("sql_safety", {"allowed": safety.allowed, "reasons": list(safety.reasons)})
        trace.metric(
            dimension=TelemetryDimension.QUALITY,
            name="sql_safety.allowed",
            value=1.0 if safety.allowed else 0.0,
            unit="ratio",
            attributes={"metric": metric_contract.metric_name},
        )
        if not safety.allowed:
            raise ValueError(f"SQL safety check failed: {'; '.join(safety.reasons)}")

        query_result = self.query_executor.execute(query_plan)
        trace.record("query_result", {"row_count": query_result.row_count})
        trace.metric(
            dimension=TelemetryDimension.SYSTEM,
            name="query_result.row_count",
            value=float(query_result.row_count),
            unit="rows",
            attributes={"metric": metric_contract.metric_name},
        )

        data_requirement = self.data_product_compiler.compile_requirement(
            intent=intent,
            metric_contract=metric_contract,
            provider_contract=provider_contract,
            parameters=parameters,
        )
        lineage_snapshot = self.data_product_compiler.build_lineage_snapshot(
            query_plan=query_plan,
            provider_contract=provider_contract,
        )
        data_product_candidate = self.data_product_compiler.build_candidate(
            requirement=data_requirement,
            metric_contract=metric_contract,
            query_plan=query_plan,
            lineage_snapshot=lineage_snapshot,
        )
        trace.record(
            "data_product_candidate",
            {"data_product_id": data_product_candidate.data_product_id},
        )

        evidence = self.evidence_builder.build(
            evidence_chain_id=f"evidence-{uuid4().hex[:12]}",
            intent=intent,
            metric_contract=metric_contract,
            query_plan=query_plan,
            sql_safety=safety,
            query_result=query_result,
            trace_id=trace_id,
        )
        trace.record("evidence_chain", {"evidence_chain_id": evidence.evidence_chain_id})
        trace.metric(
            dimension=TelemetryDimension.BUSINESS,
            name="evidence_chain.generated",
            value=1,
            unit="count",
            attributes={"metric": metric_contract.metric_name},
        )
        trace.metric(
            dimension=TelemetryDimension.QUALITY,
            name="evidence_chain.complete",
            value=1.0 if evidence.is_complete() else 0.0,
            unit="ratio",
            attributes={"metric": metric_contract.metric_name},
        )

        proposal = self.action_builder.build(
            proposal_id=f"proposal-{uuid4().hex[:12]}",
            evidence=evidence,
        )
        trace.record(
            "action_proposal",
            {
                "proposal_id": proposal.proposal_id,
                "risk_level": proposal.risk_level.value,
                "approval_required": proposal.approval_required,
            },
        )

        # ====== New: Governance → State Machine → Connector → Approval → Trace ======

        # 1. Build operation contract from proposal
        operation = self.action_governance.build_operation_contract(proposal)
        trace.record(
            "operation_contract",
            {
                "operation_id": operation.operation_id,
                "connector_name": operation.connector_name,
                "action_type": operation.action_type,
                "risk_level": operation.risk_level,
                "approval_required": operation.approval_required,
                "snapshot_required": operation.snapshot_required,
                "rollback_supported": operation.rollback_supported,
            },
        )

        # 2. Transition: PROPOSED → APPROVED
        self.state_machine.transition(OperationState.PROPOSED, OperationState.APPROVED)

        # 3. Snapshot if needed
        state_snapshot: StateSnapshot | None = None
        if self.action_governance.should_snapshot(operation):
            self.state_machine.transition(OperationState.APPROVED, OperationState.SNAPSHOTTING)
            connector = self.connector_registry.get(proposal.connector_name)
            state_snapshot = connector.take_snapshot(operation)
            trace.record(
                "state_snapshot",
                {
                    "connector_name": proposal.connector_name,
                    "has_snapshot": state_snapshot is not None,
                },
            )
            self.state_machine.transition(OperationState.SNAPSHOTTING, OperationState.EXECUTED)
        else:
            self.state_machine.transition(OperationState.APPROVED, OperationState.EXECUTED)

        # 4. Create pending approval if required
        approval_record = None
        if operation.approval_required:
            approval_id = f"approval-{uuid4().hex[:12]}"
            approval_record = self.approval_runtime.create_pending(
                approval_id=approval_id,
                proposal_id=proposal.proposal_id,
                approver_role=proposal.approver_role,
            )
            trace.record(
                "approval_pending",
                {
                    "approval_id": approval_id,
                    "approver_role": proposal.approver_role,
                },
            )

        # 5. Execute via connector
        connector = self.connector_registry.get(proposal.connector_name)
        action_result = connector.execute(operation, proposal.action_parameters)
        trace.record(
            "connector_execute",
            {
                "connector_name": proposal.connector_name,
                "action_type": proposal.action_type,
                "status": action_result.get("status"),
            },
        )

        # 6. Build operation trace
        operation_trace = self.operation_trace_builder.open_trace(
            trace_id=f"optrace-{uuid4().hex[:12]}",
            proposal_id=proposal.proposal_id,
            evidence_chain_id=evidence.evidence_chain_id,
            operation_id=operation.operation_id,
        )
        operation_trace = self.operation_trace_builder.update_trace(
            operation_trace,
            OperationState.EXECUTED,
            {"step": "connector_executed", "connector_name": proposal.connector_name},
        )

        # Final telemetry
        trace.metric(
            dimension=TelemetryDimension.BUSINESS,
            name="action_proposal.generated",
            value=1,
            unit="count",
            attributes={"risk_level": proposal.risk_level.value},
        )
        trace.metric(
            dimension=TelemetryDimension.COST,
            name="model.estimated_cost",
            value=0.0,
            unit="usd",
            attributes={"reason": "deterministic_runtime_no_model_call"},
        )
        trace.metric(
            dimension=TelemetryDimension.SYSTEM,
            name="trusted_loop.duration_ms",
            value=(perf_counter() - started_at) * 1000,
            unit="ms",
        )

        return TrustedLoopResult(
            intent=intent,
            query_plan=query_plan,
            evidence_chain=evidence,
            action_proposal=proposal,
            trace_events=trace.events(),
            telemetry_events=trace.telemetry_events(),
            provider_contract=provider_contract,
            data_requirement=data_requirement,
            lineage_snapshot=lineage_snapshot,
            data_product_candidate=data_product_candidate,
            operation_contract=operation,
            state_snapshot=state_snapshot,
            action_result=action_result,
            approval_record=approval_record,
        )

    def _parse_intent(self, question: str) -> BusinessIntent:
        parsed = self.intent_parser.parse(question)
        metric_name = parsed.metric_name
        if not metric_name or metric_name == "unknown":
            metric_name = self.metric_contract.metric_name

        return BusinessIntent(
            intent_id=f"intent-{uuid4().hex[:12]}",
            question=question,
            metric_name=metric_name,
            tenant_id=parsed.tenant_id,
            workspace_id=parsed.workspace_id,
        )
