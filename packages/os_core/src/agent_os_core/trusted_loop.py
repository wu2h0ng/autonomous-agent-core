from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from time import perf_counter
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    BlockCode,
    BusinessIntent,
    EvidenceChain,
    FeedbackEvent,
    KnowledgeQuery,
    MetricContract,
    OperationState,
    ProviderContract,
    ProviderKind,
    QueryPlan,
    RetrievalResult,
    RunTrace,
    SQLSafetyResult,
    SQLTemplate,
    StateSnapshot,
    TelemetryDimension,
    TrustedLoopBlock,
    TrustedLoopOutcome,
    TrustedLoopResult,
)

from .action_connectors.registry import ActionConnectorRegistry
from .action_governance import ActionGovernance
from .adoption import AdoptionLedgerView
from .action_proposal import ActionProposalBuilder
from .approval_lite import ApprovalLiteRuntime
from .corrigibility import ShellView
from .data_access_plane import ProviderRegistry
from .data_product_compiler import DataProductCompiler
from .evidence_chain import EvidenceChainBuilder
from .feedback import FeedbackEventBuilder, FeedbackStore, FeedbackStorePort
from .intent_parser import IntentParser
from .knowledge_memory import KnowledgeAssetBuilder, KnowledgeStore, KnowledgeStorePort
from .knowledge_retrieval import KnowledgeRetriever
from .operation_state_machine import OperationStateMachine
from .operation_trace import OperationTraceBuilder
from .query_runtime import StaticQueryExecutor, TemplateRegistry
from .semantic_runtime import SemanticRegistry
from .snapshot_store import InMemorySnapshotStore, SnapshotStore
from .sql_safety import SQLSafetyChecker
from .trace import InMemoryTraceStore, TraceRecorder, TraceStorePort


class TrustedLoopBlocked(Exception):
    """Raised when the Trusted Loop refuses to produce an answer (an expected block).

    Carries a structured :class:`TrustedLoopBlock`. This is distinct from a
    programming/wiring error (e.g. a missing connector raises ``KeyError``): a
    block is a first-class, user-facing outcome with a machine-readable code.
    """

    def __init__(self, block: TrustedLoopBlock) -> None:
        self.block = block
        super().__init__(f"[{block.code.value}] {block.message}")


class GroundingInvariantViolation(Exception):
    """Raised when a formal answer/action would be emitted WITHOUT passing SQL Safety
    and a complete EvidenceChain — a bypass of the Trusted Loop's non-bypassable
    mediation (P5.1b, ADR-0001 P5-1 / AR-20260614).

    This is distinct from :class:`TrustedLoopBlocked`: a block is an expected,
    user-facing business outcome; this is a HARD invariant breach. The Trusted Loop
    is the only sanctioned producer of grounded answers, so reaching here means the
    data/evidence path was bypassed by a wiring/refactor bug. Fail loudly; never
    emit an ungrounded answer or action.
    """


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
        knowledge_store: KnowledgeStorePort | None = None,
        feedback_builder: FeedbackEventBuilder | None = None,
        feedback_store: FeedbackStorePort | None = None,
        snapshot_store: SnapshotStore | None = None,
        feedback_knowledge_uow: Any | None = None,
        knowledge_retriever: KnowledgeRetriever | None = None,
        recall_k: int = 3,
        trace_store: TraceStorePort | None = None,
        adoption_ledger_view: AdoptionLedgerView | None = None,
        shell_view: ShellView | None = None,
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
        # The runtime's feedback builder is the SELF-REPORT channel (default
        # source). It is structurally unable to mint realized external value
        # (P5.1a, ADR-0001): realized value lives in the adoption ledger, which
        # the runtime can only READ through the read-only view below.
        self.feedback_builder = feedback_builder or FeedbackEventBuilder()
        self.feedback_store = feedback_store or FeedbackStore()
        self.snapshot_store = snapshot_store or InMemorySnapshotStore()
        # Read-only port onto the external adoption value channel (P5.1a). The
        # runtime holds NO writer — only an operator-held AdoptionIngest writes
        # realized value. ``None`` = no value channel wired (reads return empty).
        self.adoption_ledger_view = adoption_ledger_view
        # Operator sovereignty: a read-only view of the corrigibility shell (P5.2,
        # ADR-0001). The runtime reads ``paused`` and can ``observe`` into the
        # tamper-evident audit, but holds no op_* — it cannot pause/resume itself.
        # ``None`` = no shell wired (the loop runs unguarded).
        self.shell_view = shell_view
        # Optional unit-of-work factory: a zero-arg callable returning a context
        # manager that yields (feedback_store, knowledge_store) bound to one
        # transaction, making record_outcome's two writes atomic. When None,
        # record_outcome uses the runtime's own stores (in-memory needs no txn).
        self.feedback_knowledge_uow = feedback_knowledge_uow
        # Read-side of the learning loop (AR-20260611): when a retriever is wired,
        # run() recalls prior knowledge for the resolved metric as advisory context.
        self.knowledge_retriever = knowledge_retriever
        self.recall_k = recall_k
        # Observability v1 (AR-20260611): every run persists its RunTrace here,
        # on success AND on block, so runs are auditable by trace_id after the fact.
        self.trace_store = trace_store or InMemoryTraceStore()

    def run(self, question: str, parameters: dict[str, object]) -> TrustedLoopResult:
        """Run the loop and persist its trace on BOTH exits (AR-20260611).

        Success persists a ``status="ok"`` RunTrace; an expected business block
        persists ``status="blocked"`` (final ``blocked`` step records code/stage)
        and the re-raised block carries the trace_id, so refusals are as auditable
        as answers. Programming/wiring errors propagate unpersisted — they are
        bugs, not auditable outcomes.
        """
        trace_id = f"trace-{uuid4().hex[:12]}"
        trace = TraceRecorder(trace_id)
        try:
            result = self._execute_loop(question, parameters, trace_id, trace)
        except TrustedLoopBlocked as blocked:
            trace.record(
                "blocked",
                {
                    "code": blocked.block.code.value,
                    "stage": blocked.block.stage,
                    "message": blocked.block.message,
                },
            )
            self.trace_store.save(
                RunTrace(
                    trace_id=trace_id,
                    status="blocked",
                    events=trace.events(),
                    telemetry_events=trace.telemetry_events(),
                )
            )
            raise TrustedLoopBlocked(replace(blocked.block, trace_id=trace_id)) from None
        self.trace_store.save(
            RunTrace(
                trace_id=trace_id,
                status="ok",
                events=result.trace_events,
                telemetry_events=result.telemetry_events,
            )
        )
        return result

    def _execute_loop(
        self,
        question: str,
        parameters: dict[str, object],
        trace_id: str,
        trace: TraceRecorder,
    ) -> TrustedLoopResult:
        started_at = perf_counter()
        trace.metric(
            dimension=TelemetryDimension.BUSINESS,
            name="trusted_loop.run_started",
            value=1,
            unit="count",
        )

        # Operator sovereignty (P5.2, ADR-0001 P5-2): if the operator has paused the
        # system via the corrigibility shell, the loop refuses to answer until resumed.
        # The runtime holds only a read-only ShellView — it cannot un-pause itself. The
        # refusal is recorded in the tamper-evident audit chain.
        if self.shell_view is not None and self.shell_view.paused:
            self.shell_view.observe({"event": "run_refused_paused", "trace_id": trace_id})
            raise TrustedLoopBlocked(
                TrustedLoopBlock(
                    code=BlockCode.PAUSED,
                    message="The system is paused by the operator.",
                    stage="corrigibility_pause",
                )
            )

        intent = self._parse_intent(question)
        trace.record("intent", {"intent_id": intent.intent_id, "metric": intent.metric_name})

        try:
            metric_contract = self.semantic_registry.resolve_metric(intent.metric_name)
        except KeyError as exc:
            raise TrustedLoopBlocked(
                TrustedLoopBlock(
                    code=BlockCode.UNKNOWN_METRIC,
                    message=f"No metric contract for '{intent.metric_name}'.",
                    stage="metric_resolution",
                    details=(str(exc).strip("'"),),
                )
            ) from exc
        try:
            provider_contract = self.provider_registry.choose_for_schemas(
                metric_contract.allowed_schemas
            )
        except KeyError as exc:
            raise TrustedLoopBlocked(
                TrustedLoopBlock(
                    code=BlockCode.NO_PROVIDER,
                    message=(
                        "No provider can satisfy schemas "
                        f"{', '.join(metric_contract.allowed_schemas)}."
                    ),
                    stage="provider_selection",
                    details=(str(exc).strip("'"),),
                )
            ) from exc
        trace.record(
            "semantic_resolution",
            {
                "metric": metric_contract.metric_name,
                "provider_id": provider_contract.provider_id,
            },
        )

        # ====== Knowledge recall (read-side of the learning loop, AR-20260611) ======
        #
        # Recall happens BEFORE this run's own candidate is registered (no self-hit)
        # and is ADVISORY: it adds explainable context to the result and the trace,
        # never alters the data/evidence path, and a retriever failure must not block
        # a governed answer — but it must be trace-visible, never silent.
        related_knowledge: tuple[RetrievalResult, ...] = ()
        if self.knowledge_retriever is not None:
            try:
                related_knowledge = self.knowledge_retriever.search(
                    KnowledgeQuery(
                        text=question,
                        metric_name=metric_contract.metric_name,
                        k=self.recall_k,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - advisory path, traced below
                trace.record("knowledge_recall", {"error": str(exc)})
            else:
                trace.record(
                    "knowledge_recall",
                    {
                        "asset_ids": [r.asset.asset_id for r in related_knowledge],
                        "scores": [r.score for r in related_knowledge],
                    },
                )

        # Select the SQL template that computes THIS metric (not a fixed template),
        # so the EvidenceChain reproduces the requested metric. Unsupported metrics
        # block here rather than silently running the wrong SQL.
        try:
            sql_template = self.template_registry.resolve(metric_contract.metric_name)
        except ValueError as exc:
            raise TrustedLoopBlocked(
                TrustedLoopBlock(
                    code=BlockCode.NO_TEMPLATE,
                    message=f"No SQL template registered for metric '{metric_contract.metric_name}'.",
                    stage="template_selection",
                    details=(str(exc),),
                )
            ) from exc

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
            raise TrustedLoopBlocked(
                TrustedLoopBlock(
                    code=BlockCode.SQL_SAFETY,
                    message="SQL safety check rejected the query.",
                    stage="sql_safety",
                    details=tuple(safety.reasons),
                )
            )

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

        # Non-bypassable mediation invariant (P5.1b, ADR-0001 P5-1 / AR-20260614):
        # the single, explicit grounding checkpoint. No proposal, governed execution,
        # R4/R5 halt, or answer below this line exists unless the query passed SQL
        # Safety AND the EvidenceChain is complete. A surface/refactor that bypasses
        # the data/evidence path trips this loudly instead of emitting an ungrounded answer.
        self._assert_grounded(safety, evidence)

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
            related_knowledge=related_knowledge,
        )

    def evaluate(self, question: str, parameters: dict[str, object]) -> TrustedLoopOutcome:
        """Run the loop and return a unified outcome instead of raising on blocks.

        Returns an ``ok`` outcome carrying the ``TrustedLoopResult`` on success, or a
        ``blocked`` outcome carrying the ``TrustedLoopBlock`` for an expected business
        block (unsafe SQL, unknown metric, no template, no provider). Programming/wiring
        errors (e.g. a missing connector) still propagate as exceptions.
        """
        try:
            result = self.run(question, parameters)
        except TrustedLoopBlocked as blocked:
            return TrustedLoopOutcome(status="blocked", block=blocked.block)
        return TrustedLoopOutcome(status="ok", result=result)

    def record_outcome(
        self,
        *,
        trace_id: str,
        outcome: str,
        reviewer: str | None = None,
        metric_deltas: dict[str, object] | None = None,
    ) -> FeedbackEvent:
        """Record a runtime SELF-REPORT for a completed run and fold it back in.

        This is the post-outcome half of the loop. Its events are stamped with
        the runtime's self-report provenance (``FeedbackSource.RUNTIME_SELF_REPORT``)
        — it CANNOT mint realized external value, which is a separate, operator-only
        channel (P5.1a, ADR-0001; see ``AdoptionIngest`` / ``adoption_for_trace``).
        Invoked separately from ``run()`` once a result is observed.

        Records the typed ``FeedbackEvent`` (self-report) bound to ``trace_id`` as
        an OBSERVATION ONLY. P5.1b (ADR-0001): a self-report MUST NOT promote
        knowledge — value-driven knowledge promotion is reserved for realized
        external value via :meth:`promote_from_adoption`. This closes the
        self-feeding loop: the runtime cannot grow its own knowledge by
        self-reporting ``"adopted"``.

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
        # P5.1b (ADR-0001): self-report is recorded for trace/audit ONLY and never
        # folds into knowledge. Knowledge promotion is reserved for realized
        # external value (``promote_from_adoption``) — the anti-wirehead guarantee.
        self.feedback_store.record(feedback)
        return feedback

    def promote_from_adoption(self, trace_id: str) -> Any | None:
        """Promote the trace's KnowledgeAsset from REALIZED external value (P5.1b).

        Value-driven knowledge promotion consumes the operator-attested adoption
        ledger (read through the read-only ``AdoptionLedgerView`` — the runtime
        holds no writer, P5.1a), never self-report. If realized-value events exist
        for ``trace_id`` and a knowledge candidate exists, the candidate is
        superseded by a revision reflecting the latest adoption outcome (version
        bumped), atomically under the configured unit of work.

        Returns the revised ``KnowledgeAsset``, or ``None`` when no value channel
        is wired, no adoption is recorded, or no base candidate exists (no
        knowledge is fabricated where none existed).
        """
        if self.adoption_ledger_view is None:
            return None
        events = self.adoption_ledger_view.get_by_trace(trace_id)
        if not events:
            return None
        if self.feedback_knowledge_uow is not None:
            context = self.feedback_knowledge_uow()
        else:
            context = nullcontext((self.feedback_store, self.knowledge_store))
        with context as (_feedback_store, knowledge_store):
            base_asset = knowledge_store.get_by_trace(trace_id)
            if base_asset is None:
                return None
            revised = self.knowledge_builder.with_feedback(base_asset, events[-1])
            knowledge_store.register_version(revised)
            return revised

    def adoption_for_trace(self, trace_id: str) -> tuple[FeedbackEvent, ...]:
        """Read realized external-value (adoption) events for ``trace_id``.

        Read-only by construction (P5.1a, ADR-0001): the runtime holds an
        ``AdoptionLedgerView``, never a writer, so this is the only adoption
        surface OS Core code can reach. Returns an empty tuple when no value
        channel is wired.
        """
        if self.adoption_ledger_view is None:
            return ()
        return self.adoption_ledger_view.get_by_trace(trace_id)

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

    @staticmethod
    def _assert_grounded(safety: SQLSafetyResult, evidence: EvidenceChain) -> None:
        """The non-bypassable mediation invariant (P5.1b, ADR-0001 P5-1).

        A formal answer or action MUST be grounded: the query passed SQL Safety AND
        the EvidenceChain is complete (``is_complete()`` itself requires
        ``sql_safety.allowed``). This is the single explicit checkpoint every
        answer/proposal/execution flows through; bypassing the data/evidence path
        raises :class:`GroundingInvariantViolation` — a hard breach, not a block.
        """
        if not safety.allowed:
            raise GroundingInvariantViolation(
                "refused to ground a formal answer/action: SQL Safety did not pass"
            )
        if not evidence.is_complete():
            raise GroundingInvariantViolation(
                "refused to ground a formal answer/action: EvidenceChain is incomplete"
            )
