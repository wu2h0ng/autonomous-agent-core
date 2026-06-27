"""FastAPI HTTP surface for the Trusted Loop.

This is the only module in the package that imports FastAPI. ``__init__.py`` and
``cli.py`` deliberately do NOT import it, so non-HTTP users do not need fastapi
installed. Local ``make ci`` includes the OpenAPI contract drift gate and therefore
requires the dev/http/postgres extras from ``make bootstrap-dev`` or an equivalent
``PYTHON=...`` environment.

The app holds ONE shared ``TrustedLoopRuntime`` for its lifetime so the
in-memory knowledge/feedback stores persist across requests: a ``POST /runs``
and a later ``POST /outcomes`` for the same trace see the same state.

Auth boundary: every protected route requires an ``X-API-Key`` header matching
the configured internal key (``create_app(api_key=...)`` or env
``AGENT_OS_API_KEY``). ``POST /runs`` may also accept a report-only external key,
but that key is capped to the external ``user_result`` projection and cannot use
the management surfaces. If no internal key is configured the protected routes
reject with 503 rather than silently allowing access; a wrong/missing key returns
401.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import secrets
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from agent_os_contracts import CausalAttributionMethod, CausalOutcomeAttribution
from agent_os_core.agent_runtime import (
    AgentRunContext,
    AgentTraceWriter,
    TrustedLoopApprovalExecutionRuntimeAdapter,
    TrustedLoopAgentRuntimeAdapter,
)

from .outcome_service import (
    InMemoryReportSnapshotStore,
    TrustedLoopCorrectionRuntimeAdapter,
    _persist_agent_runtime_appended_trace,
    _persist_agent_runtime_terminal_trace,
    approval_execution_response_payload,
    report_snapshot_service,
    run_service,
    search_service,
    trace_service,
)
from .runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

API_KEY_ENV = "AGENT_OS_API_KEY"
EXTERNAL_API_KEY_ENV = "AGENT_OS_EXTERNAL_API_KEY"
OPERATOR_API_KEY_ENV = "AGENT_OS_OPERATOR_API_KEY"
API_KEY_HEADER = "X-API-Key"
OPERATOR_API_KEY_HEADER = "X-Operator-Key"
APPROVAL_EXECUTE_PATH = "/approvals/{approval_id}/execute"
API_SCOPE_RUN_INTERNAL = "runs:internal"
API_SCOPE_RUN_EXTERNAL = "runs:external"
API_SCOPE_OUTCOME_WRITE = "outcomes:write"
API_SCOPE_ADOPTION_WRITE = "adoptions:write"
API_SCOPE_KNOWLEDGE_SEARCH = "knowledge:search"
API_SCOPE_TRACE_READ = "traces:read"
API_SCOPE_REPORT_READ = "reports:read"
API_SCOPE_APPROVAL_EXECUTE = "approvals:execute"


@dataclass(frozen=True)
class ApiPrincipal:
    kind: Literal["internal", "external_report", "operator"]
    scopes: frozenset[str]
    audience_ceiling: Literal["internal", "external"] | None = None

    def allows(self, scope: str) -> bool:
        return scope in self.scopes


API_PRINCIPAL_INTERNAL = ApiPrincipal(
    kind="internal",
    scopes=frozenset(
        {
            API_SCOPE_RUN_INTERNAL,
            API_SCOPE_RUN_EXTERNAL,
            API_SCOPE_OUTCOME_WRITE,
            API_SCOPE_ADOPTION_WRITE,
            API_SCOPE_KNOWLEDGE_SEARCH,
            API_SCOPE_TRACE_READ,
            API_SCOPE_REPORT_READ,
        }
    ),
    audience_ceiling="internal",
)
API_PRINCIPAL_EXTERNAL_REPORT = ApiPrincipal(
    kind="external_report",
    scopes=frozenset({API_SCOPE_RUN_EXTERNAL, API_SCOPE_REPORT_READ}),
    audience_ceiling="external",
)
API_PRINCIPAL_OPERATOR = ApiPrincipal(
    kind="operator",
    scopes=frozenset({API_SCOPE_APPROVAL_EXECUTE}),
)


def authorize_principal_scope(principal: ApiPrincipal, required_scope: str) -> None:
    if not principal.allows(required_scope):
        raise HTTPException(
            status_code=403,
            detail=f"Principal {principal.kind} lacks required scope {required_scope}.",
        )


def _key_matches(candidate: str | None, configured: str | None) -> bool:
    return bool(candidate and configured and secrets.compare_digest(candidate, configured))


def _validate_distinct_configured_keys(
    *,
    api_key: str | None,
    external_api_key: str | None,
    operator_api_key: str | None,
) -> None:
    configured = [
        ("api_key", api_key),
        ("external_api_key", external_api_key),
        ("operator_api_key", operator_api_key),
    ]
    seen: dict[str, str] = {}
    for name, value in configured:
        if not value:
            continue
        prior = seen.get(value)
        if prior is not None:
            raise ValueError(f"Configured auth keys must be distinct: {prior} equals {name}.")
        seen[value] = name


def _external_run_response_projection(result: dict[str, Any]) -> dict[str, Any]:
    projected = dict(result)
    projected["provider_id"] = None
    projected["trace_steps"] = []
    projected["knowledge_asset_id"] = None
    projected["related_knowledge"] = []
    return projected


def _external_block_projection(block: dict[str, Any]) -> dict[str, Any]:
    projected = dict(block)
    projected["details"] = []
    projected["trace_id"] = None
    return projected


def _require_operator_key_in_openapi(openapi_schema: dict[str, Any]) -> None:
    """Advertise the operator key as required without changing 401 auth behavior."""
    try:
        parameters = openapi_schema["paths"][APPROVAL_EXECUTE_PATH]["post"]["parameters"]
    except KeyError as exc:
        raise RuntimeError("Approval execution route missing from OpenAPI schema.") from exc

    for parameter in parameters:
        if parameter.get("in") == "header" and parameter.get("name") == OPERATOR_API_KEY_HEADER:
            parameter["required"] = True
            parameter["schema"] = {"title": OPERATOR_API_KEY_HEADER, "type": "string"}
            return
    raise RuntimeError("Operator key header missing from approval execution OpenAPI schema.")


def _install_openapi_contract_hardening(app: FastAPI) -> None:
    default_openapi = app.openapi

    def hardened_openapi() -> dict[str, Any]:
        schema = default_openapi()
        _require_operator_key_in_openapi(schema)
        return schema

    app.openapi = hardened_openapi  # type: ignore[method-assign]


class RunRequest(BaseModel):
    question: str = Field(..., min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    audience: Literal["internal", "external"] = "internal"


class RelatedKnowledgeItem(BaseModel):
    """Prior organizational knowledge recalled for this run (AR-20260611)."""

    asset_id: str
    title: str
    score: float


class UserResultAnalysis(BaseModel):
    summary: str
    confidence: float
    limitations: list[str] = Field(default_factory=list)
    row_count: int
    evidence_chain_id: str


class UserResultReportSection(BaseModel):
    heading: str
    body: str | None = None
    items: list[str] = Field(default_factory=list)


class MetricContractEvidenceCard(BaseModel):
    card_id: Literal["metric_contract"]
    type: Literal["metric_contract"]
    title: str
    evidence_chain_id: str
    trace_id: str
    derived_from: list[str]
    redacted_fields: list[str] = Field(default_factory=list)
    metric_name: str
    metric_version: str
    display_name: str
    owner: str
    unit: str
    dimensions: list[str]
    data_classification: str


class SQLSafetyEvidenceCard(BaseModel):
    card_id: Literal["sql_safety"]
    type: Literal["sql_safety"]
    title: str
    evidence_chain_id: str
    trace_id: str
    derived_from: list[str]
    redacted_fields: list[str] = Field(default_factory=list)
    query_metric_name: str
    sql_safety_allowed: bool
    checked_schemas: list[str]
    checked_tables: list[str]
    bound_parameter_names: list[str]
    limit_value: int | None
    sql_fingerprint: str | None


class QueryResultEvidenceCard(BaseModel):
    card_id: Literal["query_result"]
    type: Literal["query_result"]
    title: str
    evidence_chain_id: str
    trace_id: str
    derived_from: list[str]
    redacted_fields: list[str] = Field(default_factory=list)
    row_count: int
    columns: list[str]
    preview_row_count: int


UserResultEvidenceCard = Annotated[
    MetricContractEvidenceCard | SQLSafetyEvidenceCard | QueryResultEvidenceCard,
    Field(discriminator="type"),
]


class UserResultReport(BaseModel):
    title: str
    evidence_cards: list[UserResultEvidenceCard]
    sections: list[UserResultReportSection] = Field(default_factory=list)


class UserResultDashboardWidget(BaseModel):
    widget_id: str
    type: str
    title: str
    evidence_chain_id: str
    value: Any | None = None
    unit: str | None = None
    row_count: int | None = None
    columns: list[str] = Field(default_factory=list)
    preview_rows: list[dict[str, Any]] = Field(default_factory=list)
    x_field: str | None = None
    y_field: str | None = None
    redacted_fields: list[str] = Field(default_factory=list)


class UserResultDashboard(BaseModel):
    title: str
    widgets: list[UserResultDashboardWidget] = Field(default_factory=list)


class UserResultRedaction(BaseModel):
    audience: Literal["internal", "external"]
    applied: bool
    data_classification: str
    redacted_fields: list[str]
    reason: str | None = None


class UserResultDecision(BaseModel):
    recommendation: str
    reason: str
    expected_impact: str
    risk_level: str
    approval_required: bool
    approver_role: str | None = None
    action_proposal_id: str
    confidence: float


class UserResultBusinessAction(BaseModel):
    connector_name: str
    action_type: str
    risk_level: str
    approval_required: bool
    approver_role: str | None = None
    status: str
    operation_id: str | None = None
    approval_id: str | None = None
    evidence_chain_id: str
    trace_id: str
    row_count: int


class UserResultArtifact(BaseModel):
    artifact_id: str
    kind: str
    title: str
    trace_id: str
    evidence_chain_id: str
    action_proposal_id: str
    question: str
    metric_name: str
    audience: Literal["internal", "external"]
    redaction: UserResultRedaction
    analysis: UserResultAnalysis
    report: UserResultReport
    dashboard: UserResultDashboard
    decision: UserResultDecision
    business_action: UserResultBusinessAction


class RunResponse(BaseModel):
    trace_id: str
    intent: str
    provider_id: str | None = None
    evidence_chain_id: str
    action_proposal_id: str
    row_count: int
    trace_steps: list[str] = Field(default_factory=list)
    knowledge_asset_id: str | None = None
    knowledge_version: int
    related_knowledge: list[RelatedKnowledgeItem] = Field(default_factory=list)
    user_result: UserResultArtifact


class RunReportResponse(BaseModel):
    trace_id: str
    audience: Literal["internal", "external"]
    user_result: UserResultArtifact


class AgentRuntimeErrorDetail(BaseModel):
    code: str
    message: str
    stage: str
    trace_id: str | None = None


class AgentRuntimeErrorResponse(BaseModel):
    detail: AgentRuntimeErrorDetail


class OutcomeRequest(BaseModel):
    trace_id: str = Field(..., min_length=1)
    outcome: str = Field(..., min_length=1)
    reviewer: str | None = None
    metric_deltas: dict[str, Any] | None = None


class OutcomeResponse(BaseModel):
    feedback_id: str
    trace_id: str
    outcome: str
    reviewer: str | None = None
    knowledge_asset_id: str | None = None
    knowledge_version: int


class CausalAttributionRequest(BaseModel):
    metric_name: str = Field(..., min_length=1)
    observed_value: float
    counterfactual_value: float
    delta_absolute: float
    delta_percent: float | None = None
    method: CausalAttributionMethod
    comparison_ref: str = Field(..., min_length=1)
    window_start: str = Field(..., min_length=1)
    window_end: str = Field(..., min_length=1)
    confidence: float
    notes: str | None = None

    def to_contract(self) -> CausalOutcomeAttribution:
        return CausalOutcomeAttribution(
            metric_name=self.metric_name,
            observed_value=self.observed_value,
            counterfactual_value=self.counterfactual_value,
            delta_absolute=self.delta_absolute,
            delta_percent=self.delta_percent,
            method=self.method,
            comparison_ref=self.comparison_ref,
            window_start=self.window_start,
            window_end=self.window_end,
            confidence=self.confidence,
            notes=self.notes,
        )


class AdoptionRequest(BaseModel):
    trace_id: str = Field(..., min_length=1)
    outcome: str = Field(..., min_length=1)
    reviewer: str | None = None
    metric_deltas: dict[str, Any] | None = None
    causal_attribution: CausalAttributionRequest | None = None


class AdoptionResponse(BaseModel):
    adoption_id: str
    trace_id: str
    outcome: str
    reviewer: str | None = None
    knowledge_asset_id: str | None = None
    knowledge_version: int
    result_weight: float | None = None


class ApprovalExecuteRequest(BaseModel):
    reason: str = Field(..., min_length=1)
    approved_by: str = Field(..., min_length=1)


class ApprovalExecutionAudit(BaseModel):
    durability_scope: str = "connector_response"
    execution_outcome: str | None = None
    replay_status: str = "not_replayed"
    external_ack_status: str = "unknown"
    ledger_status: str = "not_reported"
    record_id: str | None = None
    external_request_id: str | None = None
    execution_certainty: str | None = None
    ack_status: str | None = None


class ApprovalExecuteResponse(BaseModel):
    approval_id: str
    approval_status: str
    approved_by: str | None = None
    proposal_id: str
    operation_trace_id: str
    operation_id: str | None = None
    state: str
    evidence_chain_id: str
    connector_name: str | None = None
    action_type: str | None = None
    action_result_status: str | None = None
    idempotency_key: str | None = None
    execution_audit: ApprovalExecutionAudit = Field(default_factory=ApprovalExecutionAudit)
    events: list[dict[str, Any]] = Field(default_factory=list)


class ApprovalExecuteError(BaseModel):
    code: str
    message: str
    approval_id: str | None = None


class ApprovalExecuteErrorResponse(BaseModel):
    detail: ApprovalExecuteError


class SearchResultItem(BaseModel):
    asset_id: str
    title: str
    score: float
    score_breakdown: dict[str, float]


class SearchResponse(BaseModel):
    results: list[SearchResultItem] = Field(default_factory=list)


class BlockDetail(BaseModel):
    """The unified business-block contract (AR-20260606-unified-block-outcome).

    Returned as the 422 ``detail`` when the Trusted Loop refuses to answer
    (unsafe SQL, unknown metric, no template, no provider, ...). ``trace_id``
    references the persisted RunTrace of the refusal (AR-20260611).
    """

    code: str
    message: str
    stage: str
    details: list[str] = Field(default_factory=list)
    trace_id: str | None = None


class BlockedResponse(BaseModel):
    detail: BlockDetail


class TraceEventItem(BaseModel):
    step: str
    payload: dict[str, Any]


class TelemetryItem(BaseModel):
    dimension: str
    name: str
    value: float
    unit: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class TraceResponse(BaseModel):
    """The persisted, queryable trace of one run — answers AND refusals."""

    trace_id: str
    status: str
    events: list[TraceEventItem] = Field(default_factory=list)
    telemetry: list[TelemetryItem] = Field(default_factory=list)


def _build_default_factory() -> ContentCommerceRuntimeFactory:
    # 12-factor: the deployed surface selects real backends via environment variables
    # (AGENT_OS_EXECUTOR / AGENT_OS_STORE_BACKEND / AGENT_OS_DATABASE_URL /
    # AGENT_OS_DOMAIN_PACK); defaults preserve the in-memory demo behavior.
    return ContentCommerceRuntimeFactory(RuntimeFactoryConfig.from_env())


def create_app(
    runtime: Any | None = None,
    *,
    retriever: Any | None = None,
    agent_checkpoint_store: Any | None = None,
    api_key: str | None = None,
    external_api_key: str | None = None,
    operator_api_key: str | None = None,
    adoption_ingest: Any | None = None,
    report_store: Any | None = None,
) -> FastAPI:
    """Build a FastAPI app bound to a single shared runtime.

    Args:
        runtime: A pre-built ``TrustedLoopRuntime``. If ``None``, one is built
            via :class:`ContentCommerceRuntimeFactory` so server state persists
            for the app's lifetime.
        retriever: A pre-built ``KnowledgeRetriever`` for ``/knowledge/search``.
            Defaults to the factory-built retriever when ``runtime`` is also
            defaulted; if a runtime is injected WITHOUT a retriever, the search
            route rejects with 503 (the app cannot know the runtime's backend).
        agent_checkpoint_store: Optional Agent Runtime checkpoint store for
            request-scoped runtime adapters. Defaults to the factory-selected
            backend when ``runtime`` is also defaulted.
        api_key: The required ``X-API-Key`` value. Falls back to the
            ``AGENT_OS_API_KEY`` environment variable. If neither is set, the
            protected routes reject with 503.
        external_api_key: Optional report-only ``X-API-Key`` value for
            ``POST /runs``. Falls back to ``AGENT_OS_EXTERNAL_API_KEY``. It can
            only receive the external read-side projection.
    """
    if runtime is None:
        factory = _build_default_factory()
        shared_runtime = factory.build()
        shared_retriever = (
            retriever if retriever is not None else factory.build_knowledge_retriever()
        )
        shared_agent_checkpoint_store = (
            agent_checkpoint_store
            if agent_checkpoint_store is not None
            else factory.build_agent_checkpoint_store()
        )
        # Operator value channel over the SAME ledger the runtime reads (P5.1a):
        # the default app can promote knowledge from realized adoption out of the box.
        shared_adoption_ingest = (
            adoption_ingest if adoption_ingest is not None else factory.adoption_ingest()
        )
        default_report_store = factory.build_report_snapshot_store()
    else:
        shared_runtime = runtime
        shared_retriever = retriever
        shared_agent_checkpoint_store = agent_checkpoint_store
        shared_adoption_ingest = adoption_ingest
        default_report_store = None
    configured_key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)
    configured_external_key = (
        external_api_key if external_api_key is not None else os.environ.get(EXTERNAL_API_KEY_ENV)
    )
    configured_operator_key = (
        operator_api_key if operator_api_key is not None else os.environ.get(OPERATOR_API_KEY_ENV)
    )
    _validate_distinct_configured_keys(
        api_key=configured_key,
        external_api_key=configured_external_key,
        operator_api_key=configured_operator_key,
    )
    app = FastAPI(title="Agent OS API", version="0.1.0")
    app.state.runtime = shared_runtime
    app.state.agent_runtime_trace_writer = AgentTraceWriter()
    app.state.agent_checkpoint_store = shared_agent_checkpoint_store
    app.state.retriever = shared_retriever
    app.state.api_key = configured_key
    app.state.external_api_key = configured_external_key
    app.state.operator_api_key = configured_operator_key
    app.state.adoption_ingest = shared_adoption_ingest
    app.state.report_store = (
        report_store
        if report_store is not None
        else default_report_store
        if default_report_store is not None
        else InMemoryReportSnapshotStore()
    )

    def authenticate_api_key(
        x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    ) -> ApiPrincipal:
        if not app.state.api_key:
            raise HTTPException(
                status_code=503,
                detail=(
                    "API key is not configured. Set the AGENT_OS_API_KEY environment "
                    "variable (or pass api_key to create_app) to enable this endpoint."
                ),
            )
        if _key_matches(x_api_key, app.state.api_key):
            return API_PRINCIPAL_INTERNAL
        if _key_matches(x_api_key, app.state.external_api_key):
            return API_PRINCIPAL_EXTERNAL_REPORT
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")

    def require_api_scope(required_scope: str):
        def dependency(principal: ApiPrincipal = Depends(authenticate_api_key)) -> ApiPrincipal:
            authorize_principal_scope(principal, required_scope)
            return principal

        return dependency

    def require_operator_api_key(
        x_operator_key: str | None = Header(default=None, alias=OPERATOR_API_KEY_HEADER),
    ) -> ApiPrincipal:
        if not app.state.operator_api_key:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Operator API key is not configured. Set the "
                    "AGENT_OS_OPERATOR_API_KEY environment variable (or pass "
                    "operator_api_key to create_app) to enable approval execution."
                ),
            )
        if not _key_matches(x_operator_key, app.state.operator_api_key):
            raise HTTPException(status_code=401, detail="Invalid or missing operator key.")
        authorize_principal_scope(API_PRINCIPAL_OPERATOR, API_SCOPE_APPROVAL_EXECUTE)
        return API_PRINCIPAL_OPERATOR

    @app.post(
        "/runs",
        response_model=RunResponse,
        responses={
            422: {
                "model": BlockedResponse,
                "description": (
                    "Expected business block (unified block contract): the request was "
                    "understood but the Trusted Loop refused to answer."
                ),
            },
            500: {
                "model": AgentRuntimeErrorResponse,
                "description": (
                    "Sanitized Agent Runtime failure before a trusted result was produced."
                ),
            },
        },
    )
    def post_run(
        body: RunRequest,
        principal: ApiPrincipal = Depends(authenticate_api_key),
    ) -> dict[str, Any]:
        audience = "external" if principal.audience_ceiling == "external" else body.audience
        required_scope = (
            API_SCOPE_RUN_INTERNAL if audience == "internal" else API_SCOPE_RUN_EXTERNAL
        )
        authorize_principal_scope(principal, required_scope)
        agent_runtime_trace_writer = AgentTraceWriter()
        agent_runtime_adapter = TrustedLoopAgentRuntimeAdapter(
            app.state.runtime,
            checkpoint_store=app.state.agent_checkpoint_store,
            shell_view=getattr(app.state.runtime, "shell_view", None),
            trace_writer=agent_runtime_trace_writer,
        )
        agent_context = AgentRunContext(
            tenant_id="default",
            workspace_id="default",
            principal_id=principal.kind,
            principal_role=principal.kind,
            run_id=f"http-run-{uuid4().hex[:12]}",
            trace_id=f"agent-trace-{uuid4().hex[:12]}",
            policy_scope=frozenset({"trusted_loop:evaluate"}),
            metadata={
                "surface": "POST /runs",
                "audience": audience,
                "principal_kind": principal.kind,
            },
        )
        try:
            result = run_service(
                app.state.runtime,
                question=body.question,
                parameters=body.parameters,
                audience=audience,
                agent_runtime_adapter=agent_runtime_adapter,
                agent_context=agent_context,
                report_store=app.state.report_store,
            )
        finally:
            app.state.agent_runtime_trace_writer = agent_runtime_trace_writer
        if result.get("status") == "error":
            detail = dict(result["error"])
            if principal.audience_ceiling == "external":
                detail["trace_id"] = None
            raise HTTPException(status_code=500, detail=detail)
        if result.get("status") == "blocked":
            block = (
                _external_block_projection(result["block"])
                if principal.audience_ceiling == "external"
                else result["block"]
            )
            # Expected business block (unsafe SQL, unknown metric, ...) -> 422,
            # not a 500: the request was understood but the loop refused to answer.
            raise HTTPException(status_code=422, detail=block)
        if principal.audience_ceiling == "external":
            return _external_run_response_projection(result)
        return result

    @app.get("/runs/{trace_id}/report", response_model=RunReportResponse)
    def get_run_report(
        trace_id: str,
        audience: Literal["internal", "external"] = Query(default="internal"),
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_REPORT_READ)),
    ) -> dict[str, Any]:
        projected_audience = "external" if principal.audience_ceiling == "external" else audience
        payload = report_snapshot_service(
            app.state.report_store,
            trace_id=trace_id,
            audience=projected_audience,
        )
        if payload is None:
            raise HTTPException(status_code=404, detail=f"No report snapshot for {trace_id!r}.")
        return payload

    @app.post("/outcomes", response_model=OutcomeResponse)
    def post_outcome(
        body: OutcomeRequest,
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_OUTCOME_WRITE)),
    ) -> dict[str, Any]:
        # Self-report only (P5.1b): records feedback, does NOT promote knowledge.
        agent_runtime_trace_writer = AgentTraceWriter()
        agent_runtime_adapter = TrustedLoopCorrectionRuntimeAdapter(
            app.state.runtime,
            checkpoint_store=app.state.agent_checkpoint_store,
            shell_view=getattr(app.state.runtime, "shell_view", None),
            trace_writer=agent_runtime_trace_writer,
        )
        agent_context = AgentRunContext(
            tenant_id="default",
            workspace_id="default",
            principal_id=principal.kind,
            principal_role=principal.kind,
            run_id=f"http-outcome-{uuid4().hex[:12]}",
            trace_id=body.trace_id,
            policy_scope=frozenset({"trusted_loop:record_outcome"}),
            risk_ceiling="R1",
            metadata={
                "surface": "POST /outcomes",
                "principal_kind": principal.kind,
            },
        )
        try:
            agent_result = agent_runtime_adapter.record_outcome(
                context=agent_context,
                trace_id=body.trace_id,
                outcome=body.outcome,
                reviewer=body.reviewer,
                metric_deltas=body.metric_deltas,
            )
        finally:
            app.state.agent_runtime_trace_writer = agent_runtime_trace_writer

        if agent_result.status != "ok":
            _persist_agent_runtime_terminal_trace(
                app.state.runtime,
                agent_result=agent_result,
                agent_context=agent_context,
                status="blocked",
                block_message=agent_result.error_message,
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": agent_result.error_code or agent_result.status,
                    "message": agent_result.error_message or "Agent Runtime refused correction.",
                    "stage": "agent_runtime",
                    "trace_id": body.trace_id,
                },
            )
        _persist_agent_runtime_appended_trace(
            app.state.runtime,
            trace_id=body.trace_id,
            agent_runtime_adapter=agent_runtime_adapter,
        )
        return agent_result.output if isinstance(agent_result.output, dict) else {}

    @app.post("/adoptions", response_model=AdoptionResponse)
    def post_adoption(
        body: AdoptionRequest,
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_ADOPTION_WRITE)),
    ) -> dict[str, Any]:
        # The operator value channel (P5.1b): attest realized external value and
        # promote the trace's knowledge. The only surface that drives promotion.
        if app.state.adoption_ingest is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Adoption value channel is not configured. Build the app from the default "
                    "factory, or pass adoption_ingest= to create_app to enable this endpoint."
                ),
            )
        agent_runtime_trace_writer = AgentTraceWriter()
        agent_runtime_adapter = TrustedLoopCorrectionRuntimeAdapter(
            app.state.runtime,
            adoption_ingest=app.state.adoption_ingest,
            checkpoint_store=app.state.agent_checkpoint_store,
            shell_view=getattr(app.state.runtime, "shell_view", None),
            trace_writer=agent_runtime_trace_writer,
        )
        agent_context = AgentRunContext(
            tenant_id="default",
            workspace_id="default",
            principal_id=principal.kind,
            principal_role=principal.kind,
            run_id=f"http-adoption-{uuid4().hex[:12]}",
            trace_id=body.trace_id,
            policy_scope=frozenset({"trusted_loop:attest_adoption"}),
            risk_ceiling="R2",
            metadata={
                "surface": "POST /adoptions",
                "principal_kind": principal.kind,
            },
        )
        try:
            agent_result = agent_runtime_adapter.attest_adoption(
                context=agent_context,
                trace_id=body.trace_id,
                outcome=body.outcome,
                reviewer=body.reviewer,
                metric_deltas=body.metric_deltas,
                causal_attribution=(
                    body.causal_attribution.to_contract()
                    if body.causal_attribution is not None
                    else None
                ),
            )
        finally:
            app.state.agent_runtime_trace_writer = agent_runtime_trace_writer

        if agent_result.status != "ok":
            _persist_agent_runtime_terminal_trace(
                app.state.runtime,
                agent_result=agent_result,
                agent_context=agent_context,
                status="blocked",
                block_message=agent_result.error_message,
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": agent_result.error_code or agent_result.status,
                    "message": agent_result.error_message or "Agent Runtime refused correction.",
                    "stage": "agent_runtime",
                    "trace_id": body.trace_id,
                },
            )
        _persist_agent_runtime_appended_trace(
            app.state.runtime,
            trace_id=body.trace_id,
            agent_runtime_adapter=agent_runtime_adapter,
        )
        return agent_result.output if isinstance(agent_result.output, dict) else {}

    @app.post(
        "/approvals/{approval_id}/execute",
        response_model=ApprovalExecuteResponse,
        responses={
            404: {
                "model": ApprovalExecuteErrorResponse,
                "description": "Approval context not found.",
            },
            409: {
                "model": ApprovalExecuteErrorResponse,
                "description": "Approval execution conflict.",
            },
        },
    )
    def post_approval_execute(
        approval_id: str,
        body: ApprovalExecuteRequest,
        principal: ApiPrincipal = Depends(require_operator_api_key),
    ) -> dict[str, Any]:
        # Approval-bound action execution: approve then execute the exact pending
        # context captured by the prior /runs call. No automatic R4/R5 execution.
        agent_runtime_trace_writer = AgentTraceWriter()
        agent_runtime_adapter = TrustedLoopApprovalExecutionRuntimeAdapter(
            app.state.runtime,
            checkpoint_store=app.state.agent_checkpoint_store,
            shell_view=getattr(app.state.runtime, "shell_view", None),
            trace_writer=agent_runtime_trace_writer,
        )
        agent_context = AgentRunContext(
            tenant_id="default",
            workspace_id="default",
            principal_id=principal.kind,
            principal_role=principal.kind,
            run_id=f"http-approval-execute-{uuid4().hex[:12]}",
            trace_id=f"agent-trace-{uuid4().hex[:12]}",
            policy_scope=frozenset({"trusted_loop:approval_execute"}),
            risk_ceiling="R3",
            approval_id=approval_id,
            metadata={
                "surface": "POST /approvals/{approval_id}/execute",
                "principal_kind": principal.kind,
            },
        )
        try:
            agent_result = agent_runtime_adapter.execute(
                context=agent_context,
                approval_id=approval_id,
                reason=body.reason,
                approved_by=body.approved_by,
            )
        finally:
            app.state.agent_runtime_trace_writer = agent_runtime_trace_writer

        if agent_result.status != "ok":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": agent_result.error_code or agent_result.status,
                    "message": agent_result.error_message or "Agent Runtime refused execution.",
                    "approval_id": approval_id,
                },
            )

        output = agent_result.output if isinstance(agent_result.output, dict) else {}
        output_status = output.get("status")
        if output_status == "ok":
            return approval_execution_response_payload(
                output["approval"],
                output["operation_trace"],
            )
        if output_status == "not_found":
            raise HTTPException(
                status_code=404,
                detail={
                    "code": output["code"],
                    "message": output["message"],
                    "approval_id": approval_id,
                },
            )
        if output_status == "conflict":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": output["code"],
                    "message": output["message"],
                    "approval_id": approval_id,
                },
            )
        raise HTTPException(
            status_code=500,
            detail={
                "code": "AGENT_RUNTIME_APPROVAL_EXECUTE_ERROR",
                "message": "Agent Runtime approval execution returned an invalid result.",
                "approval_id": approval_id,
            },
        )

    @app.get("/knowledge/search", response_model=SearchResponse)
    def get_knowledge_search(
        q: str = Query(..., min_length=1, description="free-text question"),
        metric: str | None = Query(default=None, description="filter: exact metric name"),
        owner: str | None = Query(default=None, description="filter: exact owner"),
        k: int = Query(default=5, ge=1, le=50),
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_KNOWLEDGE_SEARCH)),
    ) -> dict[str, Any]:
        if app.state.retriever is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Knowledge retriever is not configured. Pass retriever= to create_app "
                    "(e.g. factory.build_knowledge_retriever()) to enable this endpoint."
                ),
            )
        return search_service(app.state.retriever, text=q, metric_name=metric, owner=owner, k=k)

    @app.get("/traces/{trace_id}", response_model=TraceResponse)
    def get_trace(
        trace_id: str,
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TRACE_READ)),
    ) -> dict[str, Any]:
        payload = trace_service(app.state.runtime.trace_store, trace_id=trace_id)
        if payload is None:
            raise HTTPException(status_code=404, detail=f"No run trace for {trace_id!r}.")
        return payload

    _install_openapi_contract_hardening(app)
    return app
