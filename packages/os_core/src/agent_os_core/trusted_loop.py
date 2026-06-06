from __future__ import annotations

from time import perf_counter
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    BusinessIntent,
    FeedbackEvent,
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
from .feedback import FeedbackEventBuilder, FeedbackStore
from .intent_parser import IntentParser
from .knowledge_memory import KnowledgeAssetBuilder, KnowledgeStore
from .operation_state_machine import OperationStateMachine
from .operation_trace import OperationTraceBuilder
from .query_runtime import StaticQueryExecutor, TemplateRegistry
from .semantic_runtime import SemanticRegistry
from .snapshot_store import InMemorySnapshotStore, SnapshotStore
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
        sql_template: SQLTemplate | None = None,
        template_registry: TemplateRegistry | None = None,
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
        knowledge_builder: KnowledgeAssetBuilder | None = None,
        knowledge_store: KnowledgeStore | None = None,
        feedback_builder: FeedbackEventBuilder | None = None,
        feedback_store: FeedbackStore | None = None,
        snapshot_store: SnapshotStore | None = None,
    ) -> None:
        self.metric_contract = metric_contract
        if template_registry is not None and sql_template is not None:
            raise ValueError(
                "Provide exactly one of 'sql_template' or 'template_registry', not both."
            )
        if template_registry is not None:
            self.template_registry = template_registry
        elif sql_template is not None:
            # Back-compat: a single template also serves as the default fallback.
            self.template_registry = TemplateRegistry.from_single(sql_template)
        else:
            raise ValueError("Provide either 'sql_template' or 'template_registry'.")
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

        # --- New dependencies (caller MUST provide connector_registry) ---
        if connector_registry is None:
            raise ValueError(
                "connector_registry is required. "
                "OS Core must not import action connectors — the caller is responsible "
                "for constructing and injecting the registry."
            )
        self.connector_registry = connector_registry
        self.action_governance = action_governance or ActionGovernance(
            connector_registry=self.connector_registry
        )
        self.approval_runtime = approval_runtime or ApprovalLiteRuntime()
        self.operation_trace_builder = operation_trace_builder or OperationTraceBuilder()
        self.state_machine = state_machine or OperationStateMachine()
        self.knowledge_builder = knowledge_builder or KnowledgeAssetBuilder()
        self.knowledge_store = knowledge_store or KnowledgeStore()
        self.feedback_builder = feedback_builder or FeedbackEventBuilder()
        self.feedback_store = feedback_store or FeedbackStore()
        self.snapshot_store = snapshot_store or InMemorySnapshotStore()

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

        # Select the SQL template that computes THIS metric (not a fixed template),
        # so the EvidenceChain reproduces the requested metric. Unsupported metrics
        # raise here rather than silently running the wrong SQL.
        sql_template = self.template_registry.resolve(metric_contract.metric_name)

        query_plan = QueryPlan(
            metric_name=metric_contract.metric_name,
            sql=sql_template.sql,
            parameters=parameters,
        )
        trace.record(
            "query_plan",
            {"metric": query_plan.metric_name, "template_id": sql_template.template_id},
        )

        sql_safety = SQLSafetyChecker(metric_contract.allowed_schemas)
        safety = sql_safety.check(
            sql_template.sql,
            sql_template.required_parameters,
            parameters,
            required_time_parameters=sql_template.required_time_parameters,
            max_limit=sql_template.max_limit,
            allow_select_star=sql_template.allow_select_star,
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

        # ====== Governance gate: propose-only vs governed execution ======
        #
        # Hard boundary #4: operations that require approval (this includes all
        # R4/R5 high-risk actions, see ActionGovernance.build_operation_contract)
        # MUST NOT invoke the side-effecting connector.execute() before a human
        # approves. The loop halts at AWAITING_APPROVAL and records a pending
        # approval as the human responsibility entry point. Only non-approval
        # operations proceed through governed execution.

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

        operation_trace = self.operation_trace_builder.open_trace(
            trace_id=f"optrace-{uuid4().hex[:12]}",
            proposal_id=proposal.proposal_id,
            evidence_chain_id=evidence.evidence_chain_id,
            operation_id=operation.operation_id,
        )

        state_snapshot: StateSnapshot | None = None
        approval_record = None

        if operation.approval_required:
            # Halt before execution: record pending approval, do NOT execute.
            self.state_machine.transition(OperationState.PROPOSED, OperationState.AWAITING_APPROVAL)
            approval_id = f"approval-{uuid4().hex[:12]}"
            approval_record = self.approval_runtime.create_pending(
                approval_id=approval_id,
                proposal_id=proposal.proposal_id,
                approver_role=proposal.approver_role,
            )
            action_result: dict[str, object] = {
                "status": "awaiting_approval",
                "operation_id": operation.operation_id,
                "approval_id": approval_id,
                "approver_role": proposal.approver_role,
            }
            trace.record(
                "awaiting_approval",
                {
                    "approval_id": approval_id,
                    "approver_role": proposal.approver_role,
                    "operation_id": operation.operation_id,
                },
            )
            operation_trace = self.operation_trace_builder.update_trace(
                operation_trace,
                OperationState.AWAITING_APPROVAL,
                {"step": "awaiting_approval", "approval_id": approval_id},
            )
        else:
            # Governed execution path for non-approval operations.
            self.state_machine.transition(OperationState.PROPOSED, OperationState.APPROVED)
            if self.action_governance.should_snapshot(operation):
                self.state_machine.transition(OperationState.APPROVED, OperationState.SNAPSHOTTING)
                connector = self.connector_registry.get(proposal.connector_name)
                state_snapshot = connector.take_snapshot(operation)
                if state_snapshot is not None:
                    self.snapshot_store.save(state_snapshot)
                trace.record(
                    "state_snapshot",
                    {
                        "connector_name": proposal.connector_name,
                        "has_snapshot": state_snapshot is not None,
                        "snapshot_id": state_snapshot.snapshot_id
                        if state_snapshot is not None
                        else None,
                    },
                )
                self.state_machine.transition(OperationState.SNAPSHOTTING, OperationState.EXECUTED)
            else:
                self.state_machine.transition(OperationState.APPROVED, OperationState.EXECUTED)

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
            operation_trace = self.operation_trace_builder.update_trace(
                operation_trace,
                OperationState.EXECUTED,
                {"step": "connector_executed", "connector_name": proposal.connector_name},
            )

        # ====== Back half: sediment a reusable KnowledgeAsset candidate ======
        # Every run produces a DRAFT knowledge-asset candidate bound to this
        # trace, so the loop does not stop at proposal/execution — it feeds the
        # organizational knowledge store. Feedback (post-outcome) folds in later
        # via the separate feedback path and can supersede this candidate.
        knowledge_candidate = self.knowledge_builder.build(
            evidence_chain=evidence,
            action_proposal=proposal,
            trace_id=trace_id,
        )
        self.knowledge_store.register(knowledge_candidate)
        trace.record(
            "knowledge_asset_candidate",
            {
                "asset_id": knowledge_candidate.asset_id,
                "asset_type": knowledge_candidate.asset_type,
                "source_trace_id": knowledge_candidate.source_trace_id,
            },
        )
        trace.metric(
            dimension=TelemetryDimension.BUSINESS,
            name="knowledge_asset.candidate_generated",
            value=1,
            unit="count",
            attributes={"asset_type": knowledge_candidate.asset_type},
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
            operation_trace=operation_trace,
            state_snapshot=state_snapshot,
            action_result=action_result,
            approval_record=approval_record,
            knowledge_asset_candidate=knowledge_candidate,
        )

    def record_outcome(
        self,
        *,
        trace_id: str,
        outcome: str,
        reviewer: str | None = None,
        metric_deltas: dict[str, object] | None = None,
    ) -> FeedbackEvent:
        """Record an observed outcome for a completed run and fold it back in.

        This is the post-outcome half of the loop, invoked separately from
        ``run()`` once a business result is observed. It:

        1. Builds and stores a typed ``FeedbackEvent`` bound to ``trace_id``.
        2. If a KnowledgeAsset candidate exists for that trace, supersedes it
           with a revision that reflects the feedback (version bumped), closing
           the Feedback -> KnowledgeAsset learning loop.

        Feedback for an unknown trace is still recorded, but no knowledge asset
        is fabricated where none existed.

        Args:
            trace_id: The trace of the originating run (``evidence_chain.trace_id``).
            outcome: The observed outcome signal (e.g. ``"adopted"``).
            reviewer: Optional human/agent attribution.
            metric_deltas: Optional observed metric changes.

        Returns:
            The recorded ``FeedbackEvent``.
        """
        feedback = self.feedback_builder.build(
            trace_id=trace_id,
            outcome=outcome,
            reviewer=reviewer,
            metric_deltas=metric_deltas,
        )
        self.feedback_store.record(feedback)

        base_asset = self.knowledge_store.get_by_trace(trace_id)
        if base_asset is not None:
            revised = self.knowledge_builder.with_feedback(base_asset, feedback)
            self.knowledge_store.register_version(revised)

        return feedback

    def rollback(self, snapshot_id: str) -> dict[str, Any]:
        """Roll back a previously persisted snapshot via its connector.

        Loads the snapshot from ``snapshot_store``, resolves the connector that
        produced it (by ``snapshot.connector_name``), and delegates to the
        connector's ``rollback`` to restore the captured pre-execution state.

        Args:
            snapshot_id: The id of the snapshot to roll back.

        Returns:
            The connector's rollback result (contains a ``status`` key).

        Raises:
            KeyError: If no snapshot with ``snapshot_id`` is registered.
        """
        snapshot = self.snapshot_store.get(snapshot_id)
        if snapshot is None:
            raise KeyError(f"No snapshot registered with id '{snapshot_id}'.")
        connector = self.connector_registry.get(snapshot.connector_name)
        return connector.rollback(snapshot)

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
