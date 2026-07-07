from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
import json
import threading
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
    OperationContract,
    OperationState,
    OperationTrace,
    ProviderContract,
    ProviderKind,
    QueryPlan,
    RetrievalResult,
    RunTrace,
    SQLSafetyResult,
    SQLTemplate,
    StateSnapshot,
    TelemetryDimension,
    TraceEvent,
    TrustedLoopBlock,
    TrustedLoopOutcome,
    TrustedLoopResult,
)
from agent_os_contracts.governance_decision_seam import (
    GovernanceDecisionRequest,
    ALLOW as _GD_ALLOW,
    DENY as _GD_DENY,
    ESCALATE as _GD_ESCALATE,
    VERIFY_MORE as _GD_VERIFY_MORE,
)

from .action_connectors.registry import ActionConnectorRegistry
from .action_governance import ActionGovernance
from .adoption import AdoptionLedgerView
from .action_proposal import ActionProposalBuilder
from .approval_lite import (
    ApprovalContextStorePort,
    ApprovalLiteRuntime,
    ApprovalOperationContext,
    ApprovalRecord,
    InMemoryApprovalContextStore,
)
from .corrigibility import ShellView
from .data_access_plane import ProviderRegistry
from .data_product_compiler import (
    DataProductCompiler,
    ProviderPlanningError,
    QueryPlanningError,
)
from .evidence_chain import EvidenceChainBuilder
from .feedback import FeedbackEventBuilder, FeedbackStore, FeedbackStorePort
from .intent_parser import IntentParser
from .knowledge_memory import KnowledgeAssetBuilder, KnowledgeStore, KnowledgeStorePort
from .nl_query import NLQueryEngine, QueryEngineResult
from .knowledge_retrieval import KnowledgeRetriever
from .operation_state_machine import OperationStateMachine
from .operation_trace import OperationTraceBuilder
from .query_runtime import TemplateRegistry
from .semantic_runtime import SemanticRegistry
from .snapshot_store import InMemorySnapshotStore, SnapshotStore
from .sql_safety import SQLSafetyChecker
from .trace import InMemoryTraceStore, TraceRecorder, TraceStorePort

_GOVERNANCE_DECISION_REASON_WITHHELD = "governance decision reason withheld"
_GOVERNANCE_DECISION_CLIENT_UNAVAILABLE = "governance decision client unavailable"
_GOVERNANCE_DECISION_INVALID_VERDICT = "governance decision invalid verdict"
_GOVERNANCE_DECISION_ALLOWED_VERDICTS = frozenset(
    (_GD_ALLOW, _GD_DENY, _GD_ESCALATE, _GD_VERIFY_MORE)
)
_OUTCOME_CONTEXT_QUALITY_BOOST = 0.2
_ADOPTION_CONTEXT_QUALITY_BOOST = 0.3
_MAX_CONTEXT_QUALITY_BOOST = 0.5
_RECORD_OUTCOME_TOOL_NAME = "trusted_loop.record_outcome"
_ATTEST_ADOPTION_TOOL_NAME = "trusted_loop.attest_adoption"


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
        query_executor: object | None = None,
        executor_factory: Any | None = None,
        intent_parser: IntentParser | None = None,
        nl_query_engine: NLQueryEngine | None = None,
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
        approval_context_store: ApprovalContextStorePort | None = None,
        approval_context_reclaim_after_seconds: float | None = 300.0,
        governance_decision_client: Any | None = None,
        causal_discovery_client: Any | None = None,
        approval_router: Any | None = None,
        policy_guardrails_provider: Any | None = None,
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
            # Compiler path: the runtime builds the query plan from the metric
            # contract's verified_queries via DataProductCompiler.
            self.template_registry = None
        self.sql_template = sql_template
        if query_executor is None and executor_factory is None:
            raise ValueError(
                "Provide either 'query_executor' or 'executor_factory' so the runtime can execute queries."
            )
        self.query_executor = query_executor
        self.executor_factory = executor_factory
        self.intent_parser = intent_parser or IntentParser()
        self.nl_query_engine = nl_query_engine
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
        self.evidence_builder = EvidenceChainBuilder(semantic_registry=semantic_registry)
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
        # RR-0032 governed-decision seam (R0-R3 wire): an optional injected client consulted at the
        # governance gate. It can only TIGHTEN (DENY -> block; ESCALATE/VERIFY_MORE -> force approval),
        # never loosen. None = no external governance (the loop is unchanged). #19: contract-only.
        self.governance_decision_client = governance_decision_client
        self.causal_discovery_client = causal_discovery_client
        self.approval_router = approval_router
        self.policy_guardrails_provider = policy_guardrails_provider
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
        # Approval-resume context: API/CLI callers approve by approval_id without
        # replaying operation/evidence/action payloads. The default is in-memory;
        # durable deployments inject a persistence-backed store at composition time.
        self.approval_context_store = approval_context_store or InMemoryApprovalContextStore()
        self.approval_context_reclaim_after_seconds = approval_context_reclaim_after_seconds
        self._pending_operation_lock = threading.RLock()

    def _policy_guardrails(self, proposal: Any, operation: Any) -> Any:
        """Build GuardrailInput for the router from the current run state.

        Default: evidence is complete (we are past the EvidenceChain step) and
        the dry-run is considered satisfied for the routing decision; the actual
        connector dry-run still runs in governed execution. An injected provider
        overrides this.
        """
        if self.policy_guardrails_provider is not None:
            return self.policy_guardrails_provider(proposal, operation)
        from .policy_engine import GuardrailInput

        return GuardrailInput(dry_run_success=True, evidence_complete=True, confidence=1.0)

    def _consume_policy_approval(self, policy_approval_id: str) -> None:
        """Consume a policy approval record via the router's policy engine.

        Best-effort: if no policy engine is wired or consumption fails (e.g. the
        shell was paused between decision and consume), the execution already
        happened; the failure is surfaced via trace, not a hard loop error, so a
        governed execution is not silently rolled back by a policy bookkeeping
        issue.
        """
        engine = (
            getattr(self.approval_router, "_policy_engine", None) if self.approval_router else None
        )
        if engine is None:
            return
        try:
            engine.consume_approval(policy_approval_id)
        except Exception:  # noqa: BLE001 - bookkeeping failure must not abort governed exec
            self.trace_writer = self.trace_writer  # no-op anchor; failure is trace-visible

    def run(
        self,
        question: str,
        parameters: dict[str, object],
        *,
        tenant_id: str = "default",
    ) -> TrustedLoopResult:
        """Run the loop and persist its trace on BOTH exits (AR-20260611).

        Success persists a ``status="ok"`` RunTrace; an expected business block
        persists ``status="blocked"`` (final ``blocked`` step records code/stage)
        and the re-raised block carries the trace_id, so refusals are as auditable
        as answers. Programming/wiring errors propagate unpersisted — they are
        bugs, not auditable outcomes.

        Args:
            question: Natural-language business question.
            parameters: Runtime parameters for the query plan.
            tenant_id: Tenant scope for the run and all persisted state.
        """
        trace_id = f"trace-{uuid4().hex[:12]}"
        trace = TraceRecorder(trace_id)
        try:
            result = self._execute_loop(question, parameters, trace_id, trace, tenant_id=tenant_id)
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
                ),
                tenant_id=tenant_id,
            )
            raise TrustedLoopBlocked(replace(blocked.block, trace_id=trace_id)) from None
        self.trace_store.save(
            RunTrace(
                trace_id=trace_id,
                status="ok",
                events=result.trace_events,
                telemetry_events=result.telemetry_events,
            ),
            tenant_id=tenant_id,
        )
        return result

    def _execute_loop(
        self,
        question: str,
        parameters: dict[str, object],
        trace_id: str,
        trace: TraceRecorder,
        *,
        tenant_id: str = "default",
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

        nl_result: QueryEngineResult | None = None
        if self.nl_query_engine is not None:
            nl_result = self.nl_query_engine.query(question)
            trace.record(
                "nl_query",
                {
                    "matched_metric": (
                        nl_result.matched_metric.metric_name
                        if nl_result.matched_metric is not None
                        else None
                    ),
                    "confidence": nl_result.confidence,
                    "dimensions": list(nl_result.dimensions),
                },
            )

        intent = self._parse_intent(question, nl_result, tenant_id=tenant_id)
        trace.record("intent", {"intent_id": intent.intent_id, "metric": intent.metric_name})

        runtime_parameters = dict(parameters)
        if self.nl_query_engine is not None and nl_result is not None:
            for key, value in nl_result.parameters.items():
                if key not in runtime_parameters and key in ("start_date", "end_date"):
                    runtime_parameters[key] = value
            trace.record("nl_parameters", runtime_parameters)

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
        # Resolve provider and query plan. The DataProductCompiler path is the
        # production default when no template_registry/sql_template is supplied;
        # the legacy template_registry path remains for narrow tests and simple
        # wiring.
        if self.template_registry is not None:
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
                parameters=runtime_parameters,
            )
            data_requirement = self.data_product_compiler.compile_requirement(
                intent=intent,
                metric_contract=metric_contract,
                provider_contract=provider_contract,
                parameters=runtime_parameters,
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
        else:
            try:
                compile_result = self.data_product_compiler.compile(
                    intent=intent,
                    metric_contract=metric_contract,
                    parameters=runtime_parameters,
                    provider_registry=self.provider_registry,
                )
            except (ProviderPlanningError, QueryPlanningError) as exc:
                raise TrustedLoopBlocked(
                    TrustedLoopBlock(
                        code=BlockCode.NO_TEMPLATE,
                        message=str(exc),
                        stage="data_product_compiler",
                        details=(str(exc),),
                    )
                ) from exc
            provider_contract = compile_result["provider_contract"]
            query_plan = compile_result["query_plan"]
            data_product_candidate = compile_result["data_product_candidate"]
            data_requirement = compile_result["requirement"]
            lineage_snapshot = compile_result["lineage_snapshot"]
            sql_template = query_plan.source_template
            if sql_template is None:
                raise TrustedLoopBlocked(
                    TrustedLoopBlock(
                        code=BlockCode.NO_TEMPLATE,
                        message="DataProductCompiler produced a QueryPlan without a source template.",
                        stage="query_planning",
                        details=(),
                    )
                )

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
                    ),
                    tenant_id=tenant_id,
                )
            except Exception as exc:  # noqa: BLE001 - advisory path, traced below
                trace.record("knowledge_recall", {"error": str(exc)})
            else:
                related_knowledge, context_quality_boosts = (
                    self._rank_related_knowledge_by_context_quality(
                        related_knowledge, tenant_id=tenant_id
                    )
                )
                trace.record(
                    "knowledge_recall",
                    {
                        "asset_ids": [r.asset.asset_id for r in related_knowledge],
                        "scores": [r.score for r in related_knowledge],
                        "quality_boosts": context_quality_boosts,
                    },
                )

        trace.record(
            "query_plan",
            {"metric": query_plan.metric_name, "template_id": sql_template.template_id},
        )

        sql_safety = SQLSafetyChecker(metric_contract.allowed_schemas)
        safety = sql_safety.check(
            sql_template.sql,
            sql_template.required_parameters,
            query_plan.parameters,
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

        query_executor = self.query_executor
        if query_executor is None:
            query_executor = self.executor_factory(provider_contract)
        query_result = query_executor.execute(query_plan)
        trace.record("query_result", {"row_count": query_result.row_count})
        trace.metric(
            dimension=TelemetryDimension.SYSTEM,
            name="query_result.row_count",
            value=float(query_result.row_count),
            unit="rows",
            attributes={"metric": metric_contract.metric_name},
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
            provider_contract=provider_contract,
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

        # ====== Causal Discovery (RR-0032 seam): optional step between evidence and action ======
        # If a causal discovery client is configured, send the query result data to the
        # autonomous-agent-core discovery engine. The returned DAG informs action proposals
        # with discovered causal structure (which variables affect which outcomes).
        causal_discovery_result: dict | None = None
        if self.causal_discovery_client is not None:
            try:
                rows = [[float(v) for v in row] for row in query_result.rows]
                from agent_os_contracts.causal_discovery_seam import CausalDiscoveryRequest

                cd_req = CausalDiscoveryRequest(data=rows, tau=0.05, use_fast_orient=True)
                causal_discovery_result = self.causal_discovery_client.discover(cd_req)
                trace.record(
                    "causal_discovery",
                    {
                        "n_nodes": causal_discovery_result.n_nodes,
                        "n_edges": causal_discovery_result.n_dag_edges,
                        "confidence": causal_discovery_result.confidence,
                    },
                )
            except Exception:  # noqa: BLE001 — degrade gracefully
                trace.record("causal_discovery", {"error": "client_unavailable"})

        proposal = self.action_builder.build(
            proposal_id=f"proposal-{uuid4().hex[:12]}",
            evidence=evidence,
        )
        if causal_discovery_result is not None:
            proposal = replace(
                proposal,
                causal_dag=getattr(causal_discovery_result, "dag", []),
                causal_confidence=getattr(causal_discovery_result, "confidence", 0.0),
            )
        knowledge_context_refs = tuple(r.asset.asset_id for r in related_knowledge)
        if knowledge_context_refs:
            proposal = replace(proposal, knowledge_context_refs=knowledge_context_refs)
        trace.record(
            "action_proposal",
            {
                "proposal_id": proposal.proposal_id,
                "risk_level": proposal.risk_level.value,
                "approval_required": proposal.approval_required,
                "knowledge_context_refs": list(proposal.knowledge_context_refs),
            },
        )

        # ====== Governed-decision seam (RR-0032, R0-R3 wire): optional external governance ======
        # The injected client (a remote RPC stub or a local reference) returns a verdict that can only
        # TIGHTEN: DENY -> block the loop; ESCALATE/VERIFY_MORE -> force this proposal through approval.
        # ALLOW -> unchanged. Default None -> this block is skipped and the loop behaves exactly as before.
        if self.governance_decision_client is not None:
            try:
                # S5: when the proposer enumerated candidate interventions, the governed disposer selects
                # among ALL of them by interventional evidence (chosen_action); otherwise it verifies the
                # single recommended action. The seam can still only tighten — it never loosens.
                seam_decision = self.governance_decision_client.decide(
                    GovernanceDecisionRequest(
                        task_id=proposal.proposal_id,
                        risk_tier=proposal.risk_level.value,
                        candidate_actions=(
                            proposal.candidate_actions or (proposal.recommended_action,)
                        ),
                        evidence_count=1 if evidence.is_complete() else 0,
                        approved=False,  # the OS Approval lifecycle still owns approval; the seam only tightens
                    )
                )
            except Exception as exc:  # noqa: BLE001 - seam failures must degrade safely
                trace.record(
                    "governed_decision",
                    {
                        "verdict": _GD_VERIFY_MORE,
                        "reason": _GOVERNANCE_DECISION_CLIENT_UNAVAILABLE,
                        "audit_ref": f"local-fail-closed:{proposal.proposal_id}",
                        "trace_id": trace_id,
                        "evidence_chain_id": evidence.evidence_chain_id,
                        "client_error_code": exc.__class__.__name__,
                        "chosen_action": None,  # degraded -> never a selection
                    },
                )
                if self.shell_view is not None:
                    self.shell_view.observe(
                        {
                            "event": "governed_decision",
                            "proposal_id": proposal.proposal_id,
                            "verdict": _GD_VERIFY_MORE,
                        }
                    )
                if not proposal.approval_required:
                    proposal = replace(proposal, approval_required=True)
            else:
                if seam_decision.verdict not in _GOVERNANCE_DECISION_ALLOWED_VERDICTS:
                    trace.record(
                        "governed_decision",
                        {
                            "verdict": _GD_VERIFY_MORE,
                            "reason": _GOVERNANCE_DECISION_INVALID_VERDICT,
                            "audit_ref": f"local-invalid-verdict:{proposal.proposal_id}",
                            "trace_id": trace_id,
                            "evidence_chain_id": evidence.evidence_chain_id,
                            "chosen_action": None,  # rejected verdict -> never a selection
                        },
                    )
                    if self.shell_view is not None:
                        self.shell_view.observe(
                            {
                                "event": "governed_decision",
                                "proposal_id": proposal.proposal_id,
                                "verdict": _GD_VERIFY_MORE,
                            }
                        )
                    if not proposal.approval_required:
                        proposal = replace(proposal, approval_required=True)
                else:
                    trace.record(
                        "governed_decision",
                        {
                            "verdict": seam_decision.verdict,
                            "reason": _GOVERNANCE_DECISION_REASON_WITHHELD,
                            "audit_ref": seam_decision.audit_ref,
                            "trace_id": trace_id,
                            "evidence_chain_id": evidence.evidence_chain_id,
                            # S5: which enumerated intervention the governed disposer causally selected
                            # (None when nothing was verified-effective — the loop never auto-selects).
                            "chosen_action": seam_decision.chosen_action,
                        },
                    )
                    if self.shell_view is not None:
                        self.shell_view.observe(
                            {
                                "event": "governed_decision",
                                "proposal_id": proposal.proposal_id,
                                "verdict": seam_decision.verdict,
                            }
                        )
                    if seam_decision.verdict == _GD_DENY:
                        raise TrustedLoopBlocked(
                            TrustedLoopBlock(
                                code=BlockCode.GOVERNANCE_DENIED,
                                message="External governed-decision seam denied the action.",
                                stage="governed_decision",
                                details=(_GOVERNANCE_DECISION_REASON_WITHHELD,),
                            )
                        )
                    if (
                        seam_decision.verdict in (_GD_ESCALATE, _GD_VERIFY_MORE)
                        and not proposal.approval_required
                    ):
                        proposal = replace(proposal, approval_required=True)
                    # S5 soundness: when the disposer causally SELECTED a candidate, bind the surfaced
                    # recommendation to that selection. Otherwise the loop could present a different
                    # (possibly correlational) recommended_action than the one the ALLOW verdict actually
                    # endorsed — misleading the approver and un-binding the verdict from the output.
                    elif (
                        seam_decision.verdict == _GD_ALLOW
                        and seam_decision.chosen_action
                        and seam_decision.chosen_action in proposal.candidate_actions
                        and seam_decision.chosen_action != proposal.recommended_action
                    ):
                        proposal = replace(proposal, recommended_action=seam_decision.chosen_action)

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
        feedback_event: FeedbackEvent | None = None

        # Router consultation (ADR-0012 / AR-20260707): if a router is wired and
        # pre-approves this action, take the governed execution path under policy
        # pre-approval instead of halting for human approval. No router (flag-off
        # default) leaves the MVP awaiting_approval behavior unchanged.
        policy_pre_approved = False
        policy_approval_id: str | None = None
        if operation.approval_required and self.approval_router is not None:
            guardrails = self._policy_guardrails(proposal, operation)
            route_decision = self.approval_router.route(
                proposal,
                operation,
                guardrails,
                tenant_id=tenant_id,
                trace_id=trace_id,
            )
            if route_decision.mode == "policy_pre_approved":
                policy_pre_approved = True
                policy_approval_id = route_decision.policy_approval_id
                proposal = route_decision.proposal

        if operation.approval_required and not policy_pre_approved:
            # Halt before execution: record pending approval, do NOT execute.
            self.state_machine.transition(OperationState.PROPOSED, OperationState.AWAITING_APPROVAL)
            approval_id = f"approval-{uuid4().hex[:12]}"
            approval_record = self.approval_runtime.create_pending(
                approval_id=approval_id,
                proposal_id=proposal.proposal_id,
                approver_role=proposal.approver_role,
                operation_fingerprint=self._approval_fingerprint(
                    operation=operation,
                    action_parameters=proposal.action_parameters,
                    evidence_chain_id=proposal.evidence_chain_id,
                ),
                tenant_id=tenant_id,
            )
            with self._pending_operation_lock:
                self.approval_context_store.save(
                    ApprovalOperationContext(
                        approval_id=approval_id,
                        proposal_id=proposal.proposal_id,
                        operation=operation,
                        action_parameters=dict(proposal.action_parameters),
                        evidence_chain=evidence,
                    ),
                    tenant_id=tenant_id,
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
            # Governed execution path for non-approval operations, OR policy
            # pre-approved R4/R5 actions (ADR-0012). The pre-approved path
            # transitions through POLICY_PRE_APPROVED and consumes the policy
            # approval record after successful execution (F1: consume re-checks
            # the pause shell at execution time).
            if policy_pre_approved:
                # ADR-0012 §3.4 sequence: PROPOSED -> POLICY_EVALUATED ->
                # POLICY_PRE_APPROVED (the PolicyEngine already ran its own
                # trace; the loop's OperationTrace mirrors the same lifecycle).
                self.state_machine.transition(
                    OperationState.PROPOSED, OperationState.POLICY_EVALUATED
                )
                operation_trace = self.operation_trace_builder.update_trace(
                    operation_trace,
                    OperationState.POLICY_EVALUATED,
                    {"step": "policy_evaluated", "approval_id": policy_approval_id},
                )
                self.state_machine.transition(
                    OperationState.POLICY_EVALUATED, OperationState.POLICY_PRE_APPROVED
                )
                operation_trace = self.operation_trace_builder.update_trace(
                    operation_trace,
                    OperationState.POLICY_PRE_APPROVED,
                    {"step": "policy_pre_approved", "approval_id": policy_approval_id},
                )
            else:
                self.state_machine.transition(OperationState.PROPOSED, OperationState.APPROVED)
                operation_trace = self.operation_trace_builder.update_trace(
                    operation_trace,
                    OperationState.APPROVED,
                    {"step": "approved", "approval_id": None},
                )
            operation, operation_trace, state_snapshot, action_result = (
                self._execute_governed_operation(
                    operation=operation,
                    action_parameters=proposal.action_parameters,
                    evidence_chain=evidence,
                    proposal_id=proposal.proposal_id,
                    operation_trace=operation_trace,
                    trace=trace,
                    tenant_id=tenant_id,
                )
            )

            # Auto-self-report the runtime-observed execution outcome. This closes
            # the ActionRuntime loop for low/medium-risk operations that do not
            # stop at the approval gate. The event is RUNTIME_SELF_REPORT only;
            # it cannot mint realized external value (P5.1a, ADR-0001).
            execution_status = action_result.get("status") if action_result else None
            if execution_status in ("executed", "accepted", "completed"):
                outcome = "executed"
            elif execution_status == "pending_approval":
                # Connector recorded the operation without side effects; runtime
                # self-reports an observation, not a realized execution outcome.
                outcome = "observed"
            else:
                outcome = execution_status or "observed"
            feedback_event = self.feedback_builder.build(
                trace_id=trace_id,
                outcome=outcome,
                reviewer="trusted_loop_runtime",
                metric_deltas=action_result.get("metric_deltas")
                if isinstance(action_result, dict)
                else None,
            )
            self.feedback_store.record(feedback_event, tenant_id=tenant_id)
            trace.record(
                "feedback_event",
                {
                    "feedback_id": feedback_event.feedback_id,
                    "outcome": feedback_event.outcome,
                    "source": feedback_event.source,
                },
            )
            if policy_pre_approved and policy_approval_id is not None:
                # Consume the policy approval after successful governed execution
                # (F1: consume re-checks pause shell + record validity at exec time).
                self._consume_policy_approval(policy_approval_id)

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
        self.knowledge_store.register(knowledge_candidate, tenant_id=tenant_id)
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
            feedback_event=feedback_event,
            knowledge_asset_candidate=knowledge_candidate,
            related_knowledge=related_knowledge,
        )

    def evaluate(
        self,
        question: str,
        parameters: dict[str, object],
        *,
        tenant_id: str = "default",
    ) -> TrustedLoopOutcome:
        """Run the loop and return a unified outcome instead of raising on blocks.

        Returns an ``ok`` outcome carrying the ``TrustedLoopResult`` on success, or a
        ``blocked`` outcome carrying the ``TrustedLoopBlock`` for an expected business
        block (unsafe SQL, unknown metric, no template, no provider). Programming/wiring
        errors (e.g. a missing connector) still propagate as exceptions.
        """
        try:
            result = self.run(question, parameters, tenant_id=tenant_id)
        except TrustedLoopBlocked as blocked:
            return TrustedLoopOutcome(status="blocked", block=blocked.block)
        return TrustedLoopOutcome(status="ok", result=result)

    def execute_pending_approved_operation(
        self, *, approval_id: str, tenant_id: str = "default"
    ) -> OperationTrace:
        """Execute an in-process pending operation after its approval is approved.

        This is the user-surface-friendly approval-resume path: callers pass only
        the ``approval_id``. The runtime reuses the exact operation/evidence/action
        context created during ``run()``, so clients do not need to replay payloads
        that could be incomplete or tampered with.
        """
        with self._pending_operation_lock:
            context = self.approval_context_store.claim(
                approval_id,
                reclaim_stale_after_seconds=self.approval_context_reclaim_after_seconds,
                tenant_id=tenant_id,
            )
            if context is None:
                raise KeyError(f"No pending operation context found for approval '{approval_id}'")
            try:
                operation_trace = self.execute_approved_operation(
                    approval_id=approval_id,
                    operation=context.operation,
                    action_parameters=context.action_parameters,
                    evidence_chain=context.evidence_chain,
                    proposal_id=context.proposal_id,
                    tenant_id=tenant_id,
                )
            except Exception:
                self.approval_context_store.release_claim(approval_id, tenant_id=tenant_id)
                raise
            self.approval_context_store.delete(approval_id, tenant_id=tenant_id)
            return operation_trace

    def approve_and_execute_pending_operation(
        self,
        *,
        approval_id: str,
        reason: str | None = None,
        approved_by: str | None = None,
        tenant_id: str = "default",
    ) -> tuple[ApprovalRecord, OperationTrace]:
        """Approve and execute a pending operation without creating orphan approvals."""
        with self._pending_operation_lock:
            if self.approval_context_store.get(approval_id, tenant_id=tenant_id) is None:
                raise KeyError(f"No pending operation context found for approval '{approval_id}'")
            approval = self.approval_runtime.get(approval_id, tenant_id=tenant_id)
            if approval.status == "pending":
                approval = self.approval_runtime.approve(
                    approval_id,
                    reason=reason,
                    approved_by=approved_by,
                    tenant_id=tenant_id,
                )
            elif approval.status != "approved":
                raise ValueError(
                    f"Approval '{approval_id}' is '{approval.status}', expected pending or approved."
                )
            operation_trace = self.execute_pending_approved_operation(
                approval_id=approval_id, tenant_id=tenant_id
            )
            return approval, operation_trace

    def _assert_execution_time_governance(
        self,
        *,
        operation: OperationContract,
        evidence_chain: EvidenceChain,
        proposal_id: str,
    ) -> None:
        """ADR-0005: re-verify corrigibility (C7) and the governed-decision seam AT EXECUTION TIME, before any
        connector side-effect. The proposal-time gate in ``run()`` can be stale by the time an approved action
        executes: the operator may have PAUSED, or the disposer may have flipped to DENY, between approval and
        execution. Fail-closed on those two state changes only; an already-approved action is NOT re-gated by
        ESCALATE/VERIFY_MORE (redundant post-approval) or by the seam being unavailable (never block on the
        organ, ADR-0047 — the human approval stands). The runtime holds a read-only ``ShellView`` and cannot
        un-pause itself."""
        # Corrigibility (C7) is absolute: a paused operator halts the action regardless of prior approval.
        if self.shell_view is not None and self.shell_view.paused:
            self.shell_view.observe(
                {"event": "execution_refused_paused", "proposal_id": proposal_id}
            )
            raise TrustedLoopBlocked(
                TrustedLoopBlock(
                    code=BlockCode.PAUSED,
                    message="The system is paused by the operator.",
                    stage="corrigibility_pause_execution",
                )
            )
        if self.governance_decision_client is None:
            return
        # Governed-decision seam re-consulted at execution time (closes the ADR-0004 gap). Only a fresh DENY
        # blocks; the human approval already stands.
        try:
            seam_decision = self.governance_decision_client.decide(
                GovernanceDecisionRequest(
                    task_id=proposal_id,
                    risk_tier=operation.risk_level,
                    candidate_actions=(operation.action_type,),
                    evidence_count=1 if evidence_chain.is_complete() else 0,
                    approved=True,  # the OS Approval lifecycle has approved; the seam still governs at exec time
                )
            )
        except Exception as exc:  # noqa: BLE001 - never block on the organ; the human approval stands
            if self.shell_view is not None:
                self.shell_view.observe(
                    {
                        "event": "execution_governed_decision",
                        "proposal_id": proposal_id,
                        "verdict": _GD_VERIFY_MORE,
                        "reason": _GOVERNANCE_DECISION_CLIENT_UNAVAILABLE,
                        "client_error_code": exc.__class__.__name__,
                    }
                )
            return
        if self.shell_view is not None:
            self.shell_view.observe(
                {
                    "event": "execution_governed_decision",
                    "proposal_id": proposal_id,
                    "verdict": seam_decision.verdict,
                }
            )
        if seam_decision.verdict == _GD_DENY:
            raise TrustedLoopBlocked(
                TrustedLoopBlock(
                    code=BlockCode.GOVERNANCE_DENIED,
                    message="External governed-decision seam denied the action at execution time.",
                    stage="governed_decision_execution",
                    details=(_GOVERNANCE_DECISION_REASON_WITHHELD,),
                )
            )

    def execute_approved_operation(
        self,
        *,
        approval_id: str,
        operation: OperationContract,
        action_parameters: dict[str, Any],
        evidence_chain: EvidenceChain,
        proposal_id: str,
        tenant_id: str = "default",
    ) -> OperationTrace:
        """Resume an approval-required operation after human approval.

        This is deliberately not an auto-execution path: it reads the approval
        store and refuses anything other than an approved record for the exact
        proposal before touching a connector.
        """
        approval = self.approval_runtime.get(approval_id, tenant_id=tenant_id)
        if approval.status != "approved":
            raise ValueError(
                f"Approval '{approval_id}' is '{approval.status}', expected 'approved'."
            )
        if approval.proposal_id != proposal_id:
            raise ValueError(
                f"Approval '{approval_id}' belongs to proposal "
                f"'{approval.proposal_id}', not '{proposal_id}'."
            )
        expected_operation_id = f"operation-{proposal_id}"
        if operation.operation_id != expected_operation_id:
            raise ValueError(
                "operation-proposal mismatch: "
                f"operation '{operation.operation_id}' does not belong to proposal "
                f"'{proposal_id}'."
            )
        if approval.operation_fingerprint is None:
            raise ValueError("operation approval fingerprint is missing.")
        actual_fingerprint = self._approval_fingerprint(
            operation=operation,
            action_parameters=action_parameters,
            evidence_chain_id=evidence_chain.evidence_chain_id,
        )
        if actual_fingerprint != approval.operation_fingerprint:
            raise ValueError(
                "operation-approval mismatch: operation contract, action "
                "parameters, or evidence chain do not match the approved payload."
            )
        if not operation.approval_required:
            raise ValueError("execute_approved_operation requires an approval-required operation.")
        if operation.risk_level in {"R4", "R5"}:
            raise ValueError(
                "R4/R5 business actions are proposal-only in MVP and cannot be executed."
            )

        self._assert_grounded(evidence_chain.sql_safety, evidence_chain)
        # ADR-0005: re-verify corrigibility (C7) and the governed-decision seam AT EXECUTION TIME, before any
        # connector side-effect — proposal-time governance can be stale by the time an approved action executes.
        self._assert_execution_time_governance(
            operation=operation,
            evidence_chain=evidence_chain,
            proposal_id=proposal_id,
        )
        self.state_machine.transition(OperationState.AWAITING_APPROVAL, OperationState.APPROVED)
        operation_trace = self.operation_trace_builder.open_trace(
            trace_id=f"optrace-{uuid4().hex[:12]}",
            proposal_id=proposal_id,
            evidence_chain_id=evidence_chain.evidence_chain_id,
            operation_id=operation.operation_id,
        )
        operation_trace = self.operation_trace_builder.update_trace(
            operation_trace,
            OperationState.APPROVED,
            {"step": "approved", "approval_id": approval_id},
        )
        try:
            _operation, operation_trace, _snapshot, _result = self._execute_governed_operation(
                operation=operation,
                action_parameters=action_parameters,
                evidence_chain=evidence_chain,
                proposal_id=proposal_id,
                operation_trace=operation_trace,
                trace=None,
                tenant_id=tenant_id,
            )
        except Exception as exc:
            audit_event = self._connector_uncertain_audit_event(exc)
            if audit_event is not None:
                failed_trace = getattr(exc, "_operation_trace", None)
                if not isinstance(failed_trace, OperationTrace):
                    failed_trace = self.operation_trace_builder.update_trace(
                        operation_trace,
                        OperationState.FAILED,
                        audit_event,
                    )
                self._persist_approved_operation_trace(
                    run_trace_id=evidence_chain.trace_id,
                    approval_id=approval_id,
                    operation_trace=failed_trace,
                    tenant_id=tenant_id,
                )
            raise
        self._persist_approved_operation_trace(
            run_trace_id=evidence_chain.trace_id,
            approval_id=approval_id,
            operation_trace=operation_trace,
            tenant_id=tenant_id,
        )
        return operation_trace

    def record_outcome(
        self,
        *,
        trace_id: str,
        outcome: str,
        reviewer: str | None = None,
        metric_deltas: dict[str, object] | None = None,
        tenant_id: str = "default",
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
            tenant_id: Tenant scope for the feedback record.

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
        self.feedback_store.record(feedback, tenant_id=tenant_id)
        return feedback

    def promote_from_adoption(self, trace_id: str, *, tenant_id: str = "default") -> Any | None:
        """Promote the trace's KnowledgeAsset from REALIZED external value (P5.1b).

        Value-driven knowledge promotion consumes the operator-attested adoption
        ledger (read through the read-only ``AdoptionLedgerView`` — the runtime
        holds no writer, P5.1a), never self-report. If realized-value events exist
        for ``trace_id`` and a knowledge candidate exists, the candidate is
        superseded by a revision reflecting the latest adoption outcome (version
        bumped), atomically under the configured unit of work.

        Args:
            trace_id: The originating run trace.
            tenant_id: Tenant scope for the knowledge promotion.

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
            base_asset = knowledge_store.get_by_trace(trace_id, tenant_id=tenant_id)
            if base_asset is None:
                return None
            revised = self.knowledge_builder.with_feedback(base_asset, events[-1])
            knowledge_store.register_version(revised, tenant_id=tenant_id)
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

    def rollback(self, snapshot_id: str, *, tenant_id: str = "default") -> dict[str, Any]:
        """Roll back a previously persisted snapshot via its connector.

        Loads the snapshot from ``snapshot_store``, resolves the connector that
        produced it (by ``snapshot.connector_name``), and delegates to the
        connector's ``rollback`` to restore the captured pre-execution state.

        Args:
            snapshot_id: The id of the snapshot to roll back.
            tenant_id: Tenant scope for the snapshot lookup.

        Returns:
            The connector's rollback result (contains a ``status`` key).

        Raises:
            KeyError: If no snapshot with ``snapshot_id`` is registered.
        """
        snapshot = self.snapshot_store.get(snapshot_id, tenant_id=tenant_id)
        if snapshot is None:
            raise KeyError(f"No snapshot registered with id '{snapshot_id}'.")
        connector = self.connector_registry.get(snapshot.connector_name)
        return connector.rollback(snapshot)

    def _parse_intent(
        self,
        question: str,
        nl_result: Any | None = None,
        *,
        tenant_id: str = "default",
    ) -> BusinessIntent:
        # Prefer NLQueryEngine's matched metric when it resolves confidently;
        # otherwise fall back to the legacy IntentParser.
        nl_metric_name: str | None = None
        if nl_result is not None and nl_result.matched_metric is not None:
            nl_metric_name = nl_result.matched_metric.metric_name

        parsed = self.intent_parser.parse(question, tenant_id=tenant_id)
        metric_name = nl_metric_name or parsed.metric_name
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

    def _execute_governed_operation(
        self,
        *,
        operation: OperationContract,
        action_parameters: dict[str, Any],
        evidence_chain: EvidenceChain,
        proposal_id: str,
        operation_trace: OperationTrace,
        trace: Any | None,
        tenant_id: str = "default",
    ) -> tuple[OperationContract, OperationTrace, StateSnapshot | None, dict[str, object]]:
        """Run the shared governed branch: dry-run, snapshot, connector execute."""
        self._assert_grounded(evidence_chain.sql_safety, evidence_chain)
        operation = self._with_idempotency_key(
            operation=operation,
            evidence_chain=evidence_chain,
            proposal_id=proposal_id,
        )
        connector = self.connector_registry.get(operation.connector_name)

        if operation.dry_run_required:
            dry_run = connector.dry_run(operation, action_parameters)
            if trace is not None:
                trace.record(
                    "connector_dry_run",
                    {
                        "connector_name": operation.connector_name,
                        "action_type": operation.action_type,
                        "status": dry_run.get("status"),
                        "idempotency_key": operation.idempotency_key,
                    },
                )
            operation_trace = self.operation_trace_builder.update_trace(
                operation_trace,
                OperationState.APPROVED,
                {
                    "step": "connector_dry_run",
                    "connector_name": operation.connector_name,
                    "action_type": operation.action_type,
                    "status": dry_run.get("status"),
                    "idempotency_key": operation.idempotency_key,
                },
            )
            if dry_run.get("status") != "dry_run":
                raise ValueError(
                    "dry-run failed: "
                    f"connector '{operation.connector_name}' returned status "
                    f"'{dry_run.get('status')}'"
                )

        state_snapshot: StateSnapshot | None = None
        current_state = OperationState.APPROVED
        if self.action_governance.should_snapshot(operation):
            self.state_machine.transition(OperationState.APPROVED, OperationState.SNAPSHOTTING)
            current_state = OperationState.SNAPSHOTTING
            state_snapshot = connector.take_snapshot(operation)
            if state_snapshot is not None:
                self.snapshot_store.save(state_snapshot, tenant_id=tenant_id)
            if trace is not None:
                trace.record(
                    "state_snapshot",
                    {
                        "connector_name": operation.connector_name,
                        "has_snapshot": state_snapshot is not None,
                        "snapshot_id": state_snapshot.snapshot_id
                        if state_snapshot is not None
                        else None,
                    },
                )
            operation_trace = self.operation_trace_builder.update_trace(
                operation_trace,
                OperationState.SNAPSHOTTING,
                {
                    "step": "state_snapshot",
                    "connector_name": operation.connector_name,
                    "has_snapshot": state_snapshot is not None,
                    "snapshot_id": (
                        state_snapshot.snapshot_id if state_snapshot is not None else None
                    ),
                },
            )
            if state_snapshot is None:
                raise ValueError(
                    "required snapshot missing: "
                    f"connector '{operation.connector_name}' returned no snapshot "
                    f"for operation '{operation.operation_id}'"
                )

        self.state_machine.transition(current_state, OperationState.EXECUTED)
        try:
            action_result = connector.execute(operation, action_parameters)
        except Exception as exc:
            audit_event = self._connector_uncertain_audit_event(exc)
            if audit_event is not None and trace is not None:
                trace.record(
                    audit_event["step"],
                    {key: value for key, value in audit_event.items() if key != "step"},
                )
            if audit_event is not None:
                setattr(
                    exc,
                    "_operation_trace",
                    self.operation_trace_builder.update_trace(
                        operation_trace,
                        OperationState.FAILED,
                        audit_event,
                    ),
                )
            raise
        execute_event: dict[str, Any] = {
            "step": "connector_executed",
            "connector_name": operation.connector_name,
            "action_type": operation.action_type,
            "status": action_result.get("status"),
            "idempotency_key": operation.idempotency_key,
        }
        for safe_field in (
            "record_id",
            "external_request_id",
            "durability_scope",
            "replay_status",
            "external_ack_status",
            "ledger_status",
            "execution_certainty",
            "ack_status",
            "uncertain_execution_count",
        ):
            if safe_field in action_result:
                execute_event[safe_field] = action_result[safe_field]
        execution_semantics = self.connector_registry.get_execution_semantics(
            operation.connector_name
        )
        for key, value in execution_semantics.audit_defaults().items():
            execute_event.setdefault(key, value)
        if "external_ack_status" not in execute_event and (
            execute_event.get("durability_scope") == "external_connector"
            or "external_request_id" in execute_event
        ):
            execute_event["external_ack_status"] = "unknown"
        if trace is not None:
            trace.record(
                "connector_execute",
                {key: value for key, value in execute_event.items() if key != "step"},
            )
        operation_trace = self.operation_trace_builder.update_trace(
            operation_trace,
            OperationState.EXECUTED,
            execute_event,
        )
        return operation, operation_trace, state_snapshot, action_result

    @staticmethod
    def _connector_uncertain_audit_event(exc: Exception) -> dict[str, Any] | None:
        audit_event = getattr(exc, "audit_event", None)
        if not callable(audit_event):
            return None
        event = audit_event()
        if not isinstance(event, dict):
            return None
        if event.get("step") != "connector_execution_uncertain":
            return None
        safe_event = {
            key: value
            for key, value in event.items()
            if key
            in {
                "step",
                "connector_name",
                "action_type",
                "status",
                "record_id",
                "external_request_id",
                "durability_scope",
                "replay_status",
                "external_ack_status",
                "ledger_status",
                "operation_id",
                "idempotency_key",
                "reason_code",
                "error_type",
                "ack_status",
                "execution_certainty",
            }
        }
        if "external_ack_status" not in safe_event and (
            safe_event.get("durability_scope") == "external_connector"
            or "external_request_id" in safe_event
        ):
            safe_event["external_ack_status"] = "unknown"
        return safe_event

    @staticmethod
    def _with_idempotency_key(
        *,
        operation: OperationContract,
        evidence_chain: EvidenceChain,
        proposal_id: str,
    ) -> OperationContract:
        if operation.idempotency_key:
            return operation
        return replace(
            operation,
            idempotency_key=(
                f"{evidence_chain.trace_id}:{evidence_chain.evidence_chain_id}:"
                f"{proposal_id}:{operation.connector_name}:{operation.action_type}"
            ),
        )

    @staticmethod
    def _approval_fingerprint(
        *,
        operation: OperationContract,
        action_parameters: dict[str, Any],
        evidence_chain_id: str,
    ) -> str:
        payload = {
            "evidence_chain_id": evidence_chain_id,
            "operation_id": operation.operation_id,
            "name": operation.name,
            "target_connector": operation.target_connector,
            "connector_name": operation.connector_name,
            "action_type": operation.action_type,
            "risk_level": operation.risk_level,
            "approval_required": operation.approval_required,
            "dry_run_required": operation.dry_run_required,
            "rollback_supported": operation.rollback_supported,
            "snapshot_required": operation.snapshot_required,
            "compensating_action": operation.compensating_action,
            "idempotency_key": operation.idempotency_key,
            "action_parameters": action_parameters,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    def _persist_approved_operation_trace(
        self,
        *,
        run_trace_id: str,
        approval_id: str,
        operation_trace: OperationTrace,
        tenant_id: str = "default",
    ) -> None:
        existing = self.trace_store.get(run_trace_id, tenant_id=tenant_id)
        if existing is None:
            return
        appended_events = tuple(
            TraceEvent(
                trace_id=run_trace_id,
                step="approved_operation_trace",
                payload={
                    "approval_id": approval_id,
                    "operation_trace_id": operation_trace.trace_id,
                    "operation_state": operation_trace.state.value,
                    "operation_event": event,
                },
            )
            for event in operation_trace.events
        )
        self.trace_store.save(
            replace(existing, events=existing.events + appended_events),
            tenant_id=tenant_id,
        )

    def _rank_related_knowledge_by_context_quality(
        self,
        related_knowledge: tuple[RetrievalResult, ...],
        *,
        tenant_id: str = "default",
    ) -> tuple[tuple[RetrievalResult, ...], list[dict[str, Any]]]:
        if not related_knowledge:
            return related_knowledge, []

        asset_ids = {result.asset.asset_id for result in related_knowledge}
        usage_quality = {
            asset_id: {
                "outcome_correction_count": 0,
                "adoption_correction_count": 0,
            }
            for asset_id in asset_ids
        }
        for run_trace in self.trace_store.all_traces(tenant_id=tenant_id):
            for event in run_trace.events:
                payload = event.payload
                refs = payload.get("knowledge_context_refs")
                if not isinstance(refs, list):
                    continue
                referenced_asset_ids = asset_ids.intersection(
                    ref for ref in refs if isinstance(ref, str)
                )
                if not referenced_asset_ids or event.step != "agent_runtime.tool_succeeded":
                    continue
                tool_name = payload.get("tool_name")
                if tool_name == _RECORD_OUTCOME_TOOL_NAME:
                    counter = "outcome_correction_count"
                elif tool_name == _ATTEST_ADOPTION_TOOL_NAME:
                    counter = "adoption_correction_count"
                else:
                    continue
                for asset_id in referenced_asset_ids:
                    usage_quality[asset_id][counter] += 1

        ranked: list[RetrievalResult] = []
        quality_boosts: list[dict[str, Any]] = []
        for result in related_knowledge:
            counts = usage_quality[result.asset.asset_id]
            quality_boost = min(
                _MAX_CONTEXT_QUALITY_BOOST,
                counts["outcome_correction_count"] * _OUTCOME_CONTEXT_QUALITY_BOOST
                + counts["adoption_correction_count"] * _ADOPTION_CONTEXT_QUALITY_BOOST,
            )
            if quality_boost:
                quality_boosts.append(
                    {
                        "asset_id": result.asset.asset_id,
                        "outcome_correction_count": counts["outcome_correction_count"],
                        "adoption_correction_count": counts["adoption_correction_count"],
                        "quality_boost": quality_boost,
                    }
                )
            score_breakdown = dict(result.score_breakdown)
            score_breakdown["context_quality_boost"] = quality_boost
            score_breakdown["total"] = result.score + quality_boost
            ranked.append(
                replace(
                    result,
                    score=result.score + quality_boost,
                    score_breakdown=score_breakdown,
                )
            )

        ranked.sort(key=lambda result: result.score, reverse=True)
        quality_boosts.sort(key=lambda item: item["quality_boost"], reverse=True)
        return tuple(ranked), quality_boosts
