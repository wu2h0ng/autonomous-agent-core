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
import json
import logging
import os
import secrets
import time
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse

from agent_os_contracts import CausalAttributionMethod, CausalOutcomeAttribution, QuotaExceeded
from agent_os_core import (
    Dashboard,
    DashboardCard,
    DashboardStorePort,
    InMemoryDashboardStore,
    InMemoryTenantStore,
    QuotaGate,
)
from agent_os_core.agent_runtime import (
    AgentRunContext,
    AgentToolCall,
    AgentTraceWriter,
    TrustedLoopApprovalExecutionRuntimeAdapter,
    TrustedLoopAgentRuntimeAdapter,
)

from agent_os_core.conversation import (
    ContextResolver,
    InMemoryConversationStore,
)
from agent_os_core.nl_query import NLQueryEngine
from agent_os_core.semantic_runtime import SemanticRegistry
from .outcome_service import (
    InMemoryReportSnapshotStore,
    TrustedLoopCorrectionRuntimeAdapter,
    _knowledge_context_refs_from_output,
    _persist_agent_runtime_appended_trace,
    _persist_agent_runtime_terminal_trace,
    approval_execution_response_payload,
    knowledge_asset_catalog_service,
    knowledge_asset_decision_quality_service,
    knowledge_asset_detail_service,
    knowledge_asset_lifecycle_events_service,
    knowledge_asset_quality_summary_service,
    knowledge_asset_usage_events_service,
    knowledge_deprecate_service,
    knowledge_publish_service,
    knowledge_review_action_service,
    knowledge_review_queue_service,
    report_snapshot_service,
    run_service,
    search_service,
    trace_service,
)
from .runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig
from . import staged_out_service

API_KEY_ENV = "AGENT_OS_API_KEY"
EXTERNAL_API_KEY_ENV = "AGENT_OS_EXTERNAL_API_KEY"
OPERATOR_API_KEY_ENV = "AGENT_OS_OPERATOR_API_KEY"
VIEWER_API_KEY_ENV = "AGENT_OS_VIEWER_API_KEY"
API_KEY_HEADER = "X-API-Key"
OPERATOR_API_KEY_HEADER = "X-Operator-Key"
SESSION_ID_HEADER = "X-Session-Id"
APPROVAL_EXECUTE_PATH = "/approvals/{approval_id}/execute"
KNOWLEDGE_QUALITY_STATUS_VALUES = [
    "unused",
    "proposal_only",
    "outcome_observed",
    "adoption_observed",
]
KNOWLEDGE_REVIEW_PRIORITY_VALUES = ["high", "medium", "low"]
KNOWLEDGE_RECOMMENDED_REVIEW_ACTION_VALUES = [
    "review_or_reject",
    "collect_outcome_feedback",
    "monitor_for_adoption",
    "consider_publish",
]
KNOWLEDGE_REVIEW_RATIONALE_CODE_VALUES = [
    "unused_context_candidate",
    "proposal_context_needs_outcome",
    "outcome_supported_context",
    "adoption_supported_context",
]
KNOWLEDGE_CATALOG_ORDER_BY_VALUES = [
    "quality_status",
    "recommended_review_action",
    "review_priority",
    "review_rationale_code",
]
KNOWLEDGE_REVIEW_QUEUE_ORDER_BY_VALUES = ["review_priority", "review_rationale_code"]
KNOWLEDGE_QUALITY_SUMMARY_ORDER_BY_VALUES = ["review_priority"]

API_LOGGER = logging.getLogger("agent_os.api")


class MetricsCollector:
    """Thread-safe (GIL-backed) counters for the Prometheus /metrics endpoint."""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, str, int], int] = {}

    def record(self, method: str, path: str, status_code: int) -> None:
        key = (method.upper(), path, status_code)
        self._counters[key] = self._counters.get(key, 0) + 1

    def render(self) -> str:
        lines = ["# HELP agent_os_http_requests_total Total HTTP requests"]
        lines.append("# TYPE agent_os_http_requests_total counter")
        for (method, path, status), count in sorted(self._counters.items()):
            safe_path = path.replace('"', '\\"')
            lines.append(
                f'agent_os_http_requests_total{{method="{method}",path="{safe_path}",status="{status}"}} {count}'
            )
        return "\n".join(lines)


class StructuredAccessLogMiddleware(BaseHTTPMiddleware):
    """Emit one JSON access log line per request with trust/observability fields."""

    def __init__(self, app: Any, collector: MetricsCollector) -> None:
        super().__init__(app)
        self._collector = collector

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        request_id = request.headers.get("X-Request-Id") or uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            self._emit(request, 500, duration_ms)
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        self._emit(request, response.status_code, duration_ms)
        response.headers["X-Request-Id"] = request_id
        return response

    def _emit(self, request: Request, status_code: int, duration_ms: float) -> None:
        principal = getattr(request.state, "principal", None)
        route = request.scope.get("route")
        path = getattr(route, "path", None) or request.url.path
        self._collector.record(request.method, path, status_code)
        log = {
            "event": "http_access",
            "request_id": getattr(request.state, "request_id", None),
            "tenant_id": request.headers.get("X-Tenant-Id") or "default",
            "principal_kind": principal.kind if principal is not None else "anonymous",
            "method": request.method,
            "path": path,
            "status": status_code,
            "duration_ms": round(duration_ms, 3),
        }
        API_LOGGER.info(json.dumps(log, default=str))


API_SCOPE_RUN_INTERNAL = "runs:internal"
API_SCOPE_RUN_EXTERNAL = "runs:external"
API_SCOPE_OUTCOME_WRITE = "outcomes:write"
API_SCOPE_ADOPTION_WRITE = "adoptions:write"
API_SCOPE_KNOWLEDGE_SEARCH = "knowledge:search"
API_SCOPE_KNOWLEDGE_REVIEW = "knowledge:review"
API_SCOPE_TRACE_READ = "traces:read"
API_SCOPE_REPORT_READ = "reports:read"
API_SCOPE_APPROVAL_EXECUTE = "approvals:execute"
API_SCOPE_APPROVAL_READ = "approvals:read"
API_SCOPE_RUNTIME_RESUME = "runtime:resume"
API_SCOPE_TENANT_MANAGE = "tenants:manage"


@dataclass(frozen=True)
class ApiPrincipal:
    kind: Literal["internal", "external_report", "operator", "viewer"]
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
            API_SCOPE_KNOWLEDGE_REVIEW,
            API_SCOPE_TRACE_READ,
            API_SCOPE_REPORT_READ,
            API_SCOPE_APPROVAL_READ,
            API_SCOPE_APPROVAL_EXECUTE,
            API_SCOPE_RUNTIME_RESUME,
            API_SCOPE_TENANT_MANAGE,
        }
    ),
    audience_ceiling="internal",
)
API_PRINCIPAL_EXTERNAL_REPORT = ApiPrincipal(
    kind="external_report",
    scopes=frozenset({API_SCOPE_RUN_EXTERNAL, API_SCOPE_REPORT_READ}),
    audience_ceiling="external",
)
# Operator key principal: used only on the X-Operator-Key channel for approval
# execution. It intentionally has no audience_ceiling because it does not drive
# projection selection; the caller's X-API-Key principal controls that.
API_PRINCIPAL_OPERATOR = ApiPrincipal(
    kind="operator",
    scopes=frozenset({API_SCOPE_APPROVAL_EXECUTE}),
    audience_ceiling=None,
)
API_PRINCIPAL_VIEWER = ApiPrincipal(
    kind="viewer",
    scopes=frozenset(
        {
            API_SCOPE_RUN_INTERNAL,
            API_SCOPE_RUN_EXTERNAL,
            API_SCOPE_KNOWLEDGE_SEARCH,
            API_SCOPE_TRACE_READ,
            API_SCOPE_REPORT_READ,
            API_SCOPE_APPROVAL_READ,
        }
    ),
    audience_ceiling="internal",
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
    viewer_api_key: str | None,
) -> None:
    configured = [
        ("api_key", api_key),
        ("external_api_key", external_api_key),
        ("operator_api_key", operator_api_key),
        ("viewer_api_key", viewer_api_key),
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
    projected["runtime_checkpoint_ref"] = None
    return projected


def _external_block_projection(block: dict[str, Any]) -> dict[str, Any]:
    projected = dict(block)
    projected["details"] = []
    projected["trace_id"] = None
    return projected


def _runtime_checkpoint_ref(context: AgentRunContext, *, tool_name: str) -> dict[str, str]:
    return {
        "run_id": context.run_id,
        "trace_id": context.trace_id,
        "tool_name": tool_name,
        "call_id": f"{tool_name}:{context.run_id or context.trace_id}",
    }


def _runtime_checkpoint_ref_if_persisted(
    checkpoint_store: Any | None,
    context: AgentRunContext,
    *,
    tool_name: str,
) -> dict[str, str] | None:
    if checkpoint_store is None or not context.run_id:
        return None
    try:
        snapshot = checkpoint_store.get(context.run_id)
    except Exception:  # noqa: BLE001 - ref projection must not expose backend details
        return None
    if snapshot is None or snapshot.last_result is None:
        return None
    if snapshot.trace_id != context.trace_id:
        return None
    if snapshot.metadata.get("tool_name") != tool_name:
        return None
    return _runtime_checkpoint_ref(context, tool_name=tool_name)


def _runtime_resume_output_ref(output: Any) -> dict[str, Any]:
    """Project a checkpointed tool output without exposing raw tool output."""
    if isinstance(output, dict) and output.get("type") == "TrustedLoopOutcome":
        result = output.get("result")
        if isinstance(result, dict):
            return {
                "kind": "trusted_loop_outcome",
                "business_trace_id": result.get("trace_id"),
                "evidence_chain_id": result.get("evidence_chain_id"),
                "row_count": result.get("row_count"),
                "blocked": False,
            }
        block = output.get("block")
        if isinstance(block, dict):
            return {
                "kind": "trusted_loop_outcome",
                "business_trace_id": block.get("trace_id"),
                "blocked": True,
                "block_code": block.get("code"),
            }

    if output.__class__.__name__ == "TrustedLoopOutcome":
        result = getattr(output, "result", None)
        if result is not None:
            evidence = result.evidence_chain
            return {
                "kind": "trusted_loop_outcome",
                "business_trace_id": evidence.trace_id,
                "evidence_chain_id": evidence.evidence_chain_id,
                "row_count": evidence.query_result.row_count,
                "blocked": False,
            }
        block = getattr(output, "block", None)
        if block is not None:
            return {
                "kind": "trusted_loop_outcome",
                "business_trace_id": block.trace_id,
                "blocked": True,
                "block_code": block.code.value,
            }

    return {"kind": output.__class__.__name__ if output is not None else "none"}


def _runtime_resume_error_detail(agent_result: Any, *, runtime_run_id: str) -> dict[str, Any]:
    return {
        "code": agent_result.error_code or agent_result.status,
        "message": agent_result.error_message or "Agent Runtime refused checkpoint resume.",
        "stage": "agent_runtime",
        "runtime_run_id": runtime_run_id,
        "runtime_trace_id": agent_result.trace_id,
    }


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


class NLParseRequest(BaseModel):
    question: str = Field(..., min_length=1)


class NLParseResponse(BaseModel):
    metric_keyword: str
    matched_metric: str | None = None
    parameters: dict[str, str]
    confidence: float
    dimensions: list[str] = Field(default_factory=list)
    raw_question: str


class NLBuildRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_id: str | None = None


class NLBuildResponse(BaseModel):
    metric_keyword: str
    matched_metric: str | None = None
    display_name: str | None = None
    parameters: dict[str, str]
    dimensions: list[str] = Field(default_factory=list)
    confidence: float
    suggested_chart_type: str
    raw_question: str


class MetricCatalogItem(BaseModel):
    metric_name: str
    display_name: str
    definition: str
    unit: str
    dimensions: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)


class MetricCatalogResponse(BaseModel):
    items: list[MetricCatalogItem] = Field(default_factory=list)
    total: int


class DashboardCreateCard(BaseModel):
    title: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    metric_name: str = Field(..., min_length=1)
    chart_type: str = Field(default="table")


class DashboardCreateRequest(BaseModel):
    title: str = Field(..., min_length=1)
    cards: list[DashboardCreateCard] = Field(default_factory=list)


class DashboardResponse(BaseModel):
    dashboard_id: str
    tenant_id: str
    title: str
    created_at: str
    cards: list[dict[str, str]] = Field(default_factory=list)


class DashboardListResponse(BaseModel):
    items: list[DashboardResponse] = Field(default_factory=list)
    total: int


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


class KnowledgeContextRationaleItem(BaseModel):
    asset_id: str
    score: float
    context_quality_boost: float
    reason_code: Literal[
        "retrieved_reviewed_context",
        "prior_outcome_or_adoption_context",
    ]


class UserResultRedaction(BaseModel):
    audience: Literal["internal", "external"]
    applied: bool
    data_classification: str
    redacted_fields: list[str]
    reason: str | None = None


class ActionAlternativeItem(BaseModel):
    """A human-facing candidate action in the approval choice set (ADR-0014).

    Rendered in a stable neutral order (lexical by action) with the recommendation
    flagged — never reordered to the top — so approver position bias is not
    exploitable by the proposer.
    """

    action: str
    rationale: str
    risk_level: str | None = None
    recommended: bool = False


class UserResultDecision(BaseModel):
    recommendation: str
    reason: str
    expected_impact: str
    risk_level: str
    approval_required: bool
    approver_role: str | None = None
    action_proposal_id: str
    confidence: float
    knowledge_context_refs: list[str] = Field(default_factory=list)
    knowledge_context_rationale: list[KnowledgeContextRationaleItem]
    alternatives: list[ActionAlternativeItem] = Field(default_factory=list)
    single_option_rationale: str | None = None


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


class RuntimeCheckpointRef(BaseModel):
    run_id: str
    trace_id: str
    tool_name: str
    call_id: str


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
    runtime_checkpoint_ref: RuntimeCheckpointRef | None = None


class RunReportResponse(BaseModel):
    trace_id: str
    audience: Literal["internal", "external"]
    user_result: UserResultArtifact


class TenantCreateRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=256)
    status: Literal["active", "inactive", "suspended"] = "active"
    config: dict[str, Any] = Field(default_factory=dict)


class TenantResponse(BaseModel):
    tenant_id: str
    display_name: str
    status: str
    created_at: str
    updated_at: str
    config: dict[str, Any]


class RuntimeResumeRequest(BaseModel):
    runtime_trace_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class RuntimeResumeOutputRef(BaseModel):
    kind: str
    business_trace_id: str | None = None
    evidence_chain_id: str | None = None
    row_count: int | None = None
    blocked: bool = False
    block_code: str | None = None


class RuntimeResumeResponse(BaseModel):
    runtime_run_id: str
    runtime_trace_id: str
    tool_name: str
    status: str
    resumed: bool
    error_code: str | None = None
    output_ref: RuntimeResumeOutputRef | None = None


class RuntimeResumeErrorDetail(BaseModel):
    code: str
    message: str
    stage: str
    runtime_run_id: str
    runtime_trace_id: str | None = None


class RuntimeResumeErrorResponse(BaseModel):
    detail: RuntimeResumeErrorDetail


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
    knowledge_context_refs: list[str] = Field(default_factory=list)
    knowledge_context_rationale: list[KnowledgeContextRationaleItem]


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
    knowledge_context_refs: list[str] = Field(default_factory=list)
    knowledge_context_rationale: list[KnowledgeContextRationaleItem]


class KnowledgeReviewQueueItem(BaseModel):
    asset_id: str
    title: str
    asset_type: str
    source_trace_id: str | None = None
    owner: str
    state: str
    outcome: str | None = None
    result_weight: float
    knowledge_version: int
    latest_usage_event: KnowledgeAssetUsageEventSummary | None
    proposal_usage_count: int
    correction_usage_count: int
    outcome_correction_count: int
    adoption_correction_count: int
    distinct_usage_trace_count: int
    quality_status: Literal[
        "unused",
        "proposal_only",
        "outcome_observed",
        "adoption_observed",
    ]
    review_priority: Literal["high", "medium", "low"]
    recommended_review_action: Literal[
        "review_or_reject",
        "collect_outcome_feedback",
        "monitor_for_adoption",
        "consider_publish",
    ]
    review_rationale_codes: list[
        Literal[
            "unused_context_candidate",
            "proposal_context_needs_outcome",
            "outcome_supported_context",
            "adoption_supported_context",
        ]
    ]


class KnowledgeReviewQueueResponse(BaseModel):
    status: str
    review_state: str
    quality_status_filter: (
        Literal[
            "unused",
            "proposal_only",
            "outcome_observed",
            "adoption_observed",
        ]
        | None
    )
    review_priority_filter: Literal["high", "medium", "low"] | None
    recommended_review_action_filter: (
        Literal[
            "review_or_reject",
            "collect_outcome_feedback",
            "monitor_for_adoption",
            "consider_publish",
        ]
        | None
    )
    review_rationale_code_filter: (
        Literal[
            "unused_context_candidate",
            "proposal_context_needs_outcome",
            "outcome_supported_context",
            "adoption_supported_context",
        ]
        | None
    )
    order_by: Literal["review_priority", "review_rationale_code"] | None
    limit: int | None
    offset: int
    total_count: int
    has_more: bool
    quality_status_counts: dict[str, int]
    review_priority_counts: dict[str, int]
    recommended_review_action_counts: dict[str, int]
    review_rationale_code_counts: dict[str, int]
    count: int
    items: list[KnowledgeReviewQueueItem] = Field(default_factory=list)


class KnowledgeAssetLifecycleEventSummary(BaseModel):
    trace_id: str
    step: str
    asset_id: str
    action: str | None = None
    previous_state: str | None = None
    state: str | None = None
    knowledge_version: int | None = None
    reason_present: bool


class KnowledgeAssetUsageEventSummary(BaseModel):
    trace_id: str
    step: Literal["action_proposal", "agent_runtime.tool_succeeded"]
    usage_kind: Literal["proposal_context", "correction_context"]
    asset_id: str
    knowledge_context_refs: list[str] = Field(default_factory=list)


class KnowledgeAssetCatalogItem(BaseModel):
    asset_id: str
    title: str
    asset_type: str
    source_trace_id: str | None = None
    owner: str
    state: str
    outcome: str | None = None
    result_weight: float
    knowledge_version: int
    lifecycle_event_count: int
    latest_lifecycle_event: KnowledgeAssetLifecycleEventSummary | None
    latest_usage_event: KnowledgeAssetUsageEventSummary | None
    proposal_usage_count: int
    correction_usage_count: int
    outcome_correction_count: int
    adoption_correction_count: int
    distinct_usage_trace_count: int
    quality_status: Literal[
        "unused",
        "proposal_only",
        "outcome_observed",
        "adoption_observed",
    ]
    review_priority: Literal["high", "medium", "low"]
    recommended_review_action: Literal[
        "review_or_reject",
        "collect_outcome_feedback",
        "monitor_for_adoption",
        "consider_publish",
    ]
    review_rationale_codes: list[
        Literal[
            "unused_context_candidate",
            "proposal_context_needs_outcome",
            "outcome_supported_context",
            "adoption_supported_context",
        ]
    ]


class KnowledgeAssetCatalogResponse(BaseModel):
    status: str
    catalog_state: str
    quality_status_filter: (
        Literal[
            "unused",
            "proposal_only",
            "outcome_observed",
            "adoption_observed",
        ]
        | None
    )
    review_priority_filter: Literal["high", "medium", "low"] | None
    recommended_review_action_filter: (
        Literal[
            "review_or_reject",
            "collect_outcome_feedback",
            "monitor_for_adoption",
            "consider_publish",
        ]
        | None
    )
    review_rationale_code_filter: (
        Literal[
            "unused_context_candidate",
            "proposal_context_needs_outcome",
            "outcome_supported_context",
            "adoption_supported_context",
        ]
        | None
    )
    order_by: (
        Literal[
            "quality_status",
            "recommended_review_action",
            "review_priority",
            "review_rationale_code",
        ]
        | None
    )
    limit: int | None
    offset: int
    total_count: int
    has_more: bool
    count: int
    quality_status_counts: dict[str, int]
    review_priority_counts: dict[str, int]
    recommended_review_action_counts: dict[str, int]
    review_rationale_code_counts: dict[str, int]
    items: list[KnowledgeAssetCatalogItem] = Field(default_factory=list)


class KnowledgeAssetDetailResponse(KnowledgeAssetCatalogItem):
    status: str
    has_source_trace: bool
    lifecycle_event_count: int
    latest_lifecycle_event: KnowledgeAssetLifecycleEventSummary | None
    latest_usage_event: KnowledgeAssetUsageEventSummary | None
    proposal_usage_count: int
    correction_usage_count: int
    outcome_correction_count: int
    adoption_correction_count: int
    distinct_usage_trace_count: int
    quality_status: Literal[
        "unused",
        "proposal_only",
        "outcome_observed",
        "adoption_observed",
    ]
    review_priority: Literal["high", "medium", "low"]
    recommended_review_action: Literal[
        "review_or_reject",
        "collect_outcome_feedback",
        "monitor_for_adoption",
        "consider_publish",
    ]
    review_rationale_codes: list[
        Literal[
            "unused_context_candidate",
            "proposal_context_needs_outcome",
            "outcome_supported_context",
            "adoption_supported_context",
        ]
    ]


class KnowledgeAssetLifecycleEvent(BaseModel):
    trace_id: str
    step: Literal[
        "knowledge_review_decision",
        "knowledge_publish_decision",
        "knowledge_deprecate_decision",
    ]
    asset_id: str
    action: str
    previous_state: str | None = None
    state: str
    reviewer: str | None = None
    knowledge_version: int
    reason_present: bool


class KnowledgeAssetLifecycleEventsResponse(BaseModel):
    status: str
    asset_id: str
    source_trace_id: str | None = None
    has_source_trace: bool
    count: int
    total_count: int
    has_more: bool
    limit: int | None
    offset: int
    events: list[KnowledgeAssetLifecycleEvent] = Field(default_factory=list)


class KnowledgeAssetUsageEventItem(BaseModel):
    trace_id: str
    step: Literal["action_proposal", "agent_runtime.tool_succeeded"]
    usage_kind: Literal["proposal_context", "correction_context"]
    asset_id: str
    knowledge_context_refs: list[str] = Field(default_factory=list)
    knowledge_context_rationale: list[KnowledgeContextRationaleItem] = Field(default_factory=list)
    tool_name: str | None = None


class KnowledgeAssetUsageEventsResponse(BaseModel):
    status: str
    asset_id: str
    source_trace_id: str | None = None
    count: int
    total_count: int
    has_more: bool
    limit: int | None
    offset: int
    events: list[KnowledgeAssetUsageEventItem] = Field(default_factory=list)


class KnowledgeAssetDecisionQualityResponse(BaseModel):
    status: str
    asset_id: str
    source_trace_id: str | None = None
    proposal_usage_count: int
    correction_usage_count: int
    outcome_correction_count: int
    adoption_correction_count: int
    distinct_usage_trace_count: int
    usage_trace_ids: list[str] = Field(default_factory=list)


class KnowledgeAssetQualitySummaryItem(BaseModel):
    asset_id: str
    source_trace_id: str | None = None
    state: str
    lifecycle_event_count: int
    latest_usage_event: KnowledgeAssetUsageEventSummary | None
    proposal_usage_count: int
    correction_usage_count: int
    outcome_correction_count: int
    adoption_correction_count: int
    distinct_usage_trace_count: int
    quality_status: Literal[
        "unused",
        "proposal_only",
        "outcome_observed",
        "adoption_observed",
    ]
    review_priority: Literal["high", "medium", "low"]
    recommended_review_action: Literal[
        "review_or_reject",
        "collect_outcome_feedback",
        "monitor_for_adoption",
        "consider_publish",
    ]
    review_rationale_codes: list[
        Literal[
            "unused_context_candidate",
            "proposal_context_needs_outcome",
            "outcome_supported_context",
            "adoption_supported_context",
        ]
    ]


class KnowledgeAssetQualitySummaryResponse(BaseModel):
    status: str
    quality_status_filter: (
        Literal[
            "unused",
            "proposal_only",
            "outcome_observed",
            "adoption_observed",
        ]
        | None
    )
    review_priority_filter: Literal["high", "medium", "low"] | None
    recommended_review_action_filter: (
        Literal[
            "review_or_reject",
            "collect_outcome_feedback",
            "monitor_for_adoption",
            "consider_publish",
        ]
        | None
    )
    review_rationale_code_filter: (
        Literal[
            "unused_context_candidate",
            "proposal_context_needs_outcome",
            "outcome_supported_context",
            "adoption_supported_context",
        ]
        | None
    )
    order_by: Literal["review_priority"] | None
    limit: int | None
    offset: int
    total_count: int
    has_more: bool
    quality_status_counts: dict[str, int]
    review_priority_counts: dict[str, int]
    recommended_review_action_counts: dict[str, int]
    review_rationale_code_counts: dict[str, int]
    count: int
    items: list[KnowledgeAssetQualitySummaryItem]


class KnowledgeReviewActionRequest(BaseModel):
    action: Literal["approve", "reject"]
    reviewer: str = Field(..., min_length=1)
    reason: str | None = None


class KnowledgePublishRequest(BaseModel):
    reviewer: str = Field(..., min_length=1)
    reason: str | None = None


class KnowledgeReviewActionResponse(BaseModel):
    status: str
    asset_id: str
    source_trace_id: str | None = None
    action: str
    previous_state: str
    state: str
    reviewer: str
    reason: str | None = None
    knowledge_version: int
    result_weight: float
    outcome: str | None = None


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


class ApprovalListItem(BaseModel):
    approval_id: str
    proposal_id: str
    status: str
    approver_role: str | None = None
    approved_by: str | None = None
    reason: str | None = None


class ApprovalDetailResponse(ApprovalListItem):
    """Approval detail with the ADR-0014 choice set the approver decides between.

    ``alternatives`` come from the pending approval context (empty once the
    operation has executed and the context is consumed); ``single_option_rationale``
    explains why only one option was surfaced when no alternatives exist.
    """

    alternatives: list[ActionAlternativeItem] = Field(default_factory=list)
    single_option_rationale: str | None = None


class ApprovalListResponse(BaseModel):
    items: list[ApprovalListItem] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


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


def _cors_origins_from_env() -> list[str]:
    raw = os.environ.get("AGENT_OS_CORS_ORIGINS", "")
    if raw.strip():
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3099",
        "http://127.0.0.1:3099",
    ]


def create_app(
    runtime: Any | None = None,
    *,
    retriever: Any | None = None,
    agent_checkpoint_store: Any | None = None,
    api_key: str | None = None,
    external_api_key: str | None = None,
    operator_api_key: str | None = None,
    viewer_api_key: str | None = None,
    adoption_ingest: Any | None = None,
    report_store: Any | None = None,
    usage_store: Any | None = None,
    tenant_store: Any | None = None,
    dashboard_store: DashboardStorePort | None = None,
    quota_gate: QuotaGate | None = None,
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
        viewer_api_key: Optional read-only ``X-API-Key`` value. Falls back to
            ``AGENT_OS_VIEWER_API_KEY``.
        usage_store: Optional ``UsageStorePort`` for quota accounting. Defaults
            to the factory-selected backend when ``runtime`` is also defaulted;
            otherwise an in-memory store is used.
        tenant_store: Optional ``TenantStorePort`` for tenant provisioning.
            Defaults to the factory-selected backend when ``runtime`` is also
            defaulted; otherwise an in-memory store is used.
        dashboard_store: Optional ``DashboardStorePort`` for the NL Data Product
            Workspace. Defaults to the factory-selected backend when ``runtime``
            is also defaulted; otherwise an in-memory store is used.
        quota_gate: Optional ``QuotaGate``. Defaults to a gate over the
            configured ``usage_store`` with the built-in generous limits.
    """
    if runtime is None:
        factory = _build_default_factory()
        shared_runtime = factory.build()
        shared_factory = factory
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
        default_usage_store = factory.build_usage_store()
        default_tenant_store = factory.build_tenant_store()
        default_dashboard_store = factory.build_dashboard_store()
    else:
        shared_runtime = runtime
        shared_factory = None
        shared_retriever = retriever
        shared_agent_checkpoint_store = agent_checkpoint_store
        shared_adoption_ingest = adoption_ingest
        default_report_store = None
        default_usage_store = None
        default_tenant_store = None
        default_dashboard_store = None
    configured_key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)
    configured_external_key = (
        external_api_key if external_api_key is not None else os.environ.get(EXTERNAL_API_KEY_ENV)
    )
    configured_operator_key = (
        operator_api_key if operator_api_key is not None else os.environ.get(OPERATOR_API_KEY_ENV)
    )
    configured_viewer_key = (
        viewer_api_key if viewer_api_key is not None else os.environ.get(VIEWER_API_KEY_ENV)
    )
    _validate_distinct_configured_keys(
        api_key=configured_key,
        external_api_key=configured_external_key,
        operator_api_key=configured_operator_key,
        viewer_api_key=configured_viewer_key,
    )
    app = FastAPI(title="Agent OS API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins_from_env(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    metrics_collector = MetricsCollector()
    app.add_middleware(StructuredAccessLogMiddleware, collector=metrics_collector)
    app.state.metrics_collector = metrics_collector
    app.state.runtime = shared_runtime
    app.state.factory = shared_factory
    app.state.agent_runtime_trace_writer = AgentTraceWriter()
    app.state.agent_checkpoint_store = shared_agent_checkpoint_store
    app.state.retriever = shared_retriever
    app.state.api_key = configured_key
    app.state.external_api_key = configured_external_key
    app.state.operator_api_key = configured_operator_key
    app.state.viewer_api_key = configured_viewer_key
    app.state.adoption_ingest = shared_adoption_ingest
    app.state.report_store = (
        report_store
        if report_store is not None
        else default_report_store
        if default_report_store is not None
        else InMemoryReportSnapshotStore()
    )
    app.state.usage_store = usage_store if usage_store is not None else default_usage_store
    app.state.tenant_store = (
        tenant_store
        if tenant_store is not None
        else default_tenant_store
        if default_tenant_store is not None
        else InMemoryTenantStore()
    )
    app.state.dashboard_store = (
        dashboard_store
        if dashboard_store is not None
        else default_dashboard_store
        if default_dashboard_store is not None
        else InMemoryDashboardStore()
    )
    app.state.quota_gate = (
        quota_gate
        if quota_gate is not None
        else QuotaGate(app.state.usage_store)
        if app.state.usage_store is not None
        else None
    )
    app.state.conversation_store = InMemoryConversationStore()
    nl_registry = getattr(shared_runtime, "semantic_registry", None)
    if nl_registry is None:
        nl_registry = SemanticRegistry()
    app.state.nl_query_engine = NLQueryEngine(metric_registry=nl_registry)

    def authenticate_api_key(
        request: Request,
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
            request.state.principal = API_PRINCIPAL_INTERNAL
            return API_PRINCIPAL_INTERNAL
        if _key_matches(x_api_key, app.state.external_api_key):
            request.state.principal = API_PRINCIPAL_EXTERNAL_REPORT
            return API_PRINCIPAL_EXTERNAL_REPORT
        if _key_matches(x_api_key, app.state.viewer_api_key):
            request.state.principal = API_PRINCIPAL_VIEWER
            return API_PRINCIPAL_VIEWER
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")

    def require_api_scope(required_scope: str):
        def dependency(
            request: Request,
            principal: ApiPrincipal = Depends(authenticate_api_key),
        ) -> ApiPrincipal:
            authorize_principal_scope(principal, required_scope)
            request.state.principal = principal
            return principal

        return dependency

    def require_operator_api_key(
        request: Request,
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
        # Defense-in-depth: if the caller also presents an X-API-Key, that principal
        # must independently carry the approval-execute scope. This keeps the operator
        # channel standalone while preventing a viewer/external key from piggybacking
        # on a stolen or shared operator key.
        x_api_key = request.headers.get(API_KEY_HEADER)
        if x_api_key:
            if _key_matches(x_api_key, app.state.api_key):
                api_principal = API_PRINCIPAL_INTERNAL
            elif _key_matches(x_api_key, app.state.external_api_key):
                api_principal = API_PRINCIPAL_EXTERNAL_REPORT
            elif _key_matches(x_api_key, app.state.viewer_api_key):
                api_principal = API_PRINCIPAL_VIEWER
            else:
                raise HTTPException(status_code=401, detail="Invalid or missing API key.")
            authorize_principal_scope(api_principal, API_SCOPE_APPROVAL_EXECUTE)
        authorize_principal_scope(API_PRINCIPAL_OPERATOR, API_SCOPE_APPROVAL_EXECUTE)
        request.state.principal = API_PRINCIPAL_OPERATOR
        return API_PRINCIPAL_OPERATOR

    def require_tenant_id(
        x_tenant_id: Annotated[str | None, Header(name="X-Tenant-Id")] = None,
    ) -> str:
        return x_tenant_id or "default"

    def _check_quota(tenant_id: str, operation: str, trace_id: str) -> None:
        gate = app.state.quota_gate
        if gate is None:
            return
        try:
            gate.record_and_check(tenant_id, operation, trace_id)
        except QuotaExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

    def _check_database_health() -> dict[str, Any]:
        store = app.state.usage_store
        bind = getattr(store, "_bind", None)
        if bind is None:
            return {"status": "ok", "backend": "memory"}
        try:
            from sqlalchemy import text

            if hasattr(bind, "connect"):
                with bind.connect() as conn:
                    conn.execute(text("SELECT 1"))
            else:
                bind.execute(text("SELECT 1"))
            return {"status": "ok", "backend": "postgres"}
        except Exception as exc:  # noqa: BLE001 - health endpoint must surface safe status
            return {"status": "error", "backend": "postgres", "error": type(exc).__name__}

    def _raise_for_staged_out_result(result: dict[str, Any]) -> None:
        status = result.get("status")
        if status == "not_found":
            raise HTTPException(status_code=404, detail=result)
        if status != "error":
            return
        code = result.get("code")
        if code in {"FEATURE_DISABLED", "RUNTIME_UNAVAILABLE", "STORE_UNAVAILABLE"}:
            raise HTTPException(status_code=503, detail=result)
        if code == "INVALID_WORKFLOW_STATE":
            raise HTTPException(status_code=409, detail=result)
        raise HTTPException(status_code=400, detail=result)

    @app.get("/health")
    def get_health() -> dict[str, Any]:
        """Public health probe for orchestrators and load balancers."""
        runtime_ready = app.state.runtime is not None
        db_health = _check_database_health()
        healthy = runtime_ready and db_health["status"] == "ok"
        return {
            "status": "healthy" if healthy else "unhealthy",
            "runtime_ready": runtime_ready,
            "database": db_health,
        }

    @app.get("/metrics")
    def get_metrics(
        request: Request,
        q: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> Any:
        """Prometheus-compatible metrics, OR JSON metric catalog via content negotiation.

        Observability scrapers call this with ``Accept: text/plain`` (or no explicit
        Accept header) and receive Prometheus text. The NL Data Product Workspace
        requests ``Accept: application/json`` and receives the authenticated metric
        catalog.
        """
        accept = (request.headers.get("accept") or "").lower()
        wants_json = "application/json" in accept
        if not wants_json:
            return PlainTextResponse(app.state.metrics_collector.render())

        api_key_header = request.headers.get(API_KEY_HEADER)
        principal = authenticate_api_key(request, x_api_key=api_key_header)
        authorize_principal_scope(principal, API_SCOPE_RUN_INTERNAL)
        require_tenant_id(request.headers.get("X-Tenant-Id"))
        registry = app.state.nl_query_engine._registry
        if q:
            matches = registry.search_metrics(q, limit=1000)
        else:
            matches = tuple(
                registry.resolve_metric(name) for name in sorted(registry.metric_names())
            )
        total = len(matches)
        page = matches[offset : offset + limit]
        aliases_by_metric: dict[str, set[str]] = {}
        from agent_os_core._metric_aliases import DISPLAY_TO_METRIC

        for alias, metric_name in DISPLAY_TO_METRIC.items():
            aliases_by_metric.setdefault(metric_name, set()).add(alias)
        items = [
            MetricCatalogItem(
                metric_name=metric.metric_name,
                display_name=metric.display_name,
                definition=metric.definition,
                unit=metric.unit,
                dimensions=list(metric.dimensions),
                aliases=sorted(
                    aliases_by_metric.get(metric.metric_name, set())
                    - {metric.metric_name, metric.display_name.lower()}
                ),
            )
            for metric in page
        ]
        return MetricCatalogResponse(items=items, total=total)

    @app.post("/tenants", response_model=TenantResponse)
    def post_tenant(
        body: TenantCreateRequest,
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TENANT_MANAGE)),
    ) -> dict[str, Any]:
        """Provision a new tenant (internal principal only)."""
        del principal
        try:
            tenant = app.state.tenant_store.create(
                body.tenant_id,
                display_name=body.display_name,
                status=body.status,
                config=body.config,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return tenant.to_dict()

    @app.get("/tenants/{tenant_id}", response_model=TenantResponse)
    def get_tenant(
        tenant_id: str,
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TENANT_MANAGE)),
    ) -> dict[str, Any]:
        """Retrieve tenant metadata (internal principal only)."""
        del principal
        tenant = app.state.tenant_store.get(tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail=f"Tenant {tenant_id!r} not found.")
        return tenant.to_dict()

    @app.put("/tenants/{tenant_id}/auto-execution-policy")
    def put_auto_execution_policy(
        tenant_id: str,
        body: dict[str, Any],
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TENANT_MANAGE)),
    ) -> dict[str, Any]:
        del principal
        factory = getattr(app.state, "factory", None)
        if factory is None:
            raise HTTPException(status_code=503, detail="factory not configured")
        result = staged_out_service.register_auto_execution_policy(
            policy_engine=factory.build_policy_engine(),
            policy_store=factory.build_auto_execution_policy_store(),
            flags=factory._runtime_feature_flags(),
            tenant_id=tenant_id,
            body=body,
        )
        if result.get("status") == "error":
            raise HTTPException(status_code=503, detail=result)
        return result

    @app.get("/tenants/{tenant_id}/auto-execution-policy")
    def get_auto_execution_policy(
        tenant_id: str,
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TENANT_MANAGE)),
    ) -> dict[str, Any]:
        del principal
        factory = getattr(app.state, "factory", None)
        if factory is None:
            raise HTTPException(status_code=503, detail="factory not configured")
        result = staged_out_service.get_auto_execution_policy(
            policy_store=factory.build_auto_execution_policy_store(),
            flags=factory._runtime_feature_flags(),
            tenant_id=tenant_id,
        )
        if result.get("status") == "error":
            raise HTTPException(status_code=503, detail=result)
        if result.get("status") == "not_found":
            raise HTTPException(status_code=404, detail=result)
        return result

    @app.post("/workflows")
    def post_workflow(
        body: dict[str, Any],
        tenant_id: str = Depends(require_tenant_id),
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TENANT_MANAGE)),
    ) -> dict[str, Any]:
        del principal
        factory = getattr(app.state, "factory", None)
        if factory is None:
            raise HTTPException(status_code=503, detail="factory not configured")
        result = staged_out_service.register_workflow(
            workflow_runtime=factory.build_workflow_runtime(),
            flags=factory._runtime_feature_flags(),
            tenant_id=tenant_id,
            body=body,
        )
        _raise_for_staged_out_result(result)
        return result

    @app.get("/workflows")
    def get_workflows(
        tenant_id: str = Depends(require_tenant_id),
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TENANT_MANAGE)),
    ) -> dict[str, Any]:
        del principal
        factory = getattr(app.state, "factory", None)
        if factory is None:
            raise HTTPException(status_code=503, detail="factory not configured")
        result = staged_out_service.list_workflows(
            workflow_store=factory.build_workflow_store(),
            flags=factory._runtime_feature_flags(),
            tenant_id=tenant_id,
        )
        _raise_for_staged_out_result(result)
        return result

    @app.post("/workflows/{workflow_id}/instances")
    def post_workflow_instance(
        workflow_id: str,
        body: dict[str, Any],
        tenant_id: str = Depends(require_tenant_id),
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TENANT_MANAGE)),
    ) -> dict[str, Any]:
        del principal
        factory = getattr(app.state, "factory", None)
        if factory is None:
            raise HTTPException(status_code=503, detail="factory not configured")
        result = staged_out_service.start_workflow_instance(
            workflow_runtime=factory.build_workflow_runtime(),
            flags=factory._runtime_feature_flags(),
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            body=body,
        )
        _raise_for_staged_out_result(result)
        return result

    @app.get("/workflow-instances/{instance_id}")
    def get_workflow_instance(
        instance_id: str,
        tenant_id: str = Depends(require_tenant_id),
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TENANT_MANAGE)),
    ) -> dict[str, Any]:
        del principal
        factory = getattr(app.state, "factory", None)
        if factory is None:
            raise HTTPException(status_code=503, detail="factory not configured")
        result = staged_out_service.get_workflow_instance(
            workflow_runtime=factory.build_workflow_runtime(),
            flags=factory._runtime_feature_flags(),
            tenant_id=tenant_id,
            instance_id=instance_id,
        )
        _raise_for_staged_out_result(result)
        return result

    @app.post("/workflow-instances/{instance_id}/approve")
    def post_workflow_instance_approve(
        instance_id: str,
        body: dict[str, Any],
        tenant_id: str = Depends(require_tenant_id),
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TENANT_MANAGE)),
    ) -> dict[str, Any]:
        del principal
        factory = getattr(app.state, "factory", None)
        if factory is None:
            raise HTTPException(status_code=503, detail="factory not configured")
        result = staged_out_service.workflow_instance_operation(
            workflow_runtime=factory.build_workflow_runtime(),
            flags=factory._runtime_feature_flags(),
            tenant_id=tenant_id,
            instance_id=instance_id,
            operation="approve",
            body=body,
        )
        _raise_for_staged_out_result(result)
        return result

    @app.post("/workflow-instances/{instance_id}/reject")
    def post_workflow_instance_reject(
        instance_id: str,
        body: dict[str, Any],
        tenant_id: str = Depends(require_tenant_id),
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TENANT_MANAGE)),
    ) -> dict[str, Any]:
        del principal
        factory = getattr(app.state, "factory", None)
        if factory is None:
            raise HTTPException(status_code=503, detail="factory not configured")
        result = staged_out_service.workflow_instance_operation(
            workflow_runtime=factory.build_workflow_runtime(),
            flags=factory._runtime_feature_flags(),
            tenant_id=tenant_id,
            instance_id=instance_id,
            operation="reject",
            body=body,
        )
        _raise_for_staged_out_result(result)
        return result

    @app.post("/workflow-instances/{instance_id}/delegate")
    def post_workflow_instance_delegate(
        instance_id: str,
        body: dict[str, Any],
        tenant_id: str = Depends(require_tenant_id),
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TENANT_MANAGE)),
    ) -> dict[str, Any]:
        del principal
        factory = getattr(app.state, "factory", None)
        if factory is None:
            raise HTTPException(status_code=503, detail="factory not configured")
        result = staged_out_service.workflow_instance_operation(
            workflow_runtime=factory.build_workflow_runtime(),
            flags=factory._runtime_feature_flags(),
            tenant_id=tenant_id,
            instance_id=instance_id,
            operation="delegate",
            body=body,
        )
        _raise_for_staged_out_result(result)
        return result

    @app.post("/workflow-instances/{instance_id}/timeout-check")
    def post_workflow_instance_timeout_check(
        instance_id: str,
        body: dict[str, Any],
        tenant_id: str = Depends(require_tenant_id),
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TENANT_MANAGE)),
    ) -> dict[str, Any]:
        del principal
        factory = getattr(app.state, "factory", None)
        if factory is None:
            raise HTTPException(status_code=503, detail="factory not configured")
        result = staged_out_service.workflow_instance_operation(
            workflow_runtime=factory.build_workflow_runtime(),
            flags=factory._runtime_feature_flags(),
            tenant_id=tenant_id,
            instance_id=instance_id,
            operation="timeout_check",
            body=body,
        )
        _raise_for_staged_out_result(result)
        return result

    @app.post("/mcp/servers")
    def post_mcp_server(
        body: dict[str, Any],
        tenant_id: str = Depends(require_tenant_id),
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TENANT_MANAGE)),
    ) -> dict[str, Any]:
        del principal
        factory = getattr(app.state, "factory", None)
        if factory is None:
            raise HTTPException(status_code=503, detail="factory not configured")
        result = staged_out_service.register_mcp_server(
            registry=factory.mcp_registry(),
            flags=factory._runtime_feature_flags(),
            tenant_id=tenant_id,
            body=body,
        )
        if result.get("status") == "error":
            raise HTTPException(status_code=503, detail=result)
        return result

    @app.post("/mcp/servers/{server_id}/tools")
    def post_mcp_tool(
        server_id: str,
        body: dict[str, Any],
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TENANT_MANAGE)),
    ) -> dict[str, Any]:
        del principal
        factory = getattr(app.state, "factory", None)
        if factory is None:
            raise HTTPException(status_code=503, detail="factory not configured")
        result = staged_out_service.register_mcp_tool(
            registry=factory.mcp_registry(),
            flags=factory._runtime_feature_flags(),
            server_id=server_id,
            body=body,
        )
        if result.get("status") == "error":
            raise HTTPException(status_code=503, detail=result)
        return result

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
        tenant_id: str = Depends(require_tenant_id),
        x_session_id: str | None = Header(default=None, alias=SESSION_ID_HEADER),
    ) -> dict[str, Any]:
        audience = "external" if principal.audience_ceiling == "external" else body.audience
        required_scope = (
            API_SCOPE_RUN_INTERNAL if audience == "internal" else API_SCOPE_RUN_EXTERNAL
        )
        authorize_principal_scope(principal, required_scope)

        question = body.question
        parameters = dict(body.parameters)

        if x_session_id:
            session = app.state.conversation_store.get_or_create(x_session_id)
            resolver = ContextResolver()
            question = resolver.resolve(question, session)

        agent_runtime_trace_writer = AgentTraceWriter()
        if app.state.factory is not None:
            agent_runtime_adapter = app.state.factory.build_agent_runtime_adapter(
                app.state.runtime,
                checkpoint_store=app.state.agent_checkpoint_store,
                trace_writer=agent_runtime_trace_writer,
            )
        else:
            agent_runtime_adapter = TrustedLoopAgentRuntimeAdapter(
                app.state.runtime,
                checkpoint_store=app.state.agent_checkpoint_store,
                shell_view=getattr(app.state.runtime, "shell_view", None),
                trace_writer=agent_runtime_trace_writer,
            )
        agent_context = AgentRunContext(
            tenant_id=tenant_id,
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
        _check_quota(tenant_id, "run", agent_context.trace_id)
        try:
            result = run_service(
                app.state.runtime,
                question=question,
                parameters=parameters,
                audience=audience,
                tenant_id=tenant_id,
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
        result["runtime_checkpoint_ref"] = _runtime_checkpoint_ref_if_persisted(
            app.state.agent_checkpoint_store,
            agent_context,
            tool_name=TrustedLoopAgentRuntimeAdapter.TOOL_NAME,
        )
        if x_session_id and result.get("status") == "ok":
            session = app.state.conversation_store.get_or_create(x_session_id)
            query_plan = result.get("query_plan", {})
            metric_name = query_plan.get("metric_name") or result.get("intent")
            parameters = query_plan.get("parameters", {})
            start_date = parameters.get("start_date")
            end_date = parameters.get("end_date")
            time_range = (
                (str(start_date), str(end_date))
                if start_date is not None and end_date is not None
                else None
            )
            session.current_metric = metric_name
            session.current_time_range = time_range
            session.history.append(
                (
                    question,
                    result.get("evidence_chain_id", ""),
                    metric_name,
                    time_range,
                )
            )
            app.state.conversation_store.save(session)
        if principal.audience_ceiling == "external":
            return _external_run_response_projection(result)
        return result

    @app.post("/nl-parse", response_model=NLParseResponse)
    def nl_parse(
        body: NLParseRequest,
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_RUN_INTERNAL)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> NLParseResponse:
        del tenant_id
        result = app.state.nl_query_engine.query(body.question)
        return NLParseResponse(
            metric_keyword=(
                result.matched_metric.metric_name if result.matched_metric else "unknown"
            ),
            matched_metric=(result.matched_metric.metric_name if result.matched_metric else None),
            parameters=result.parameters,
            confidence=result.confidence,
            dimensions=list(result.dimensions),
            raw_question=body.question,
        )

    @app.post("/nl-build", response_model=NLBuildResponse)
    def nl_build(
        body: NLBuildRequest,
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_RUN_INTERNAL)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> NLBuildResponse:
        del principal, tenant_id
        result = app.state.nl_query_engine.query(body.question)
        if result.matched_metric is None:
            raise HTTPException(status_code=422, detail="Unknown metric")
        return NLBuildResponse(
            metric_keyword=result.matched_metric.metric_name,
            matched_metric=result.matched_metric.metric_name,
            display_name=result.matched_metric.display_name,
            parameters=result.parameters,
            dimensions=list(result.dimensions),
            confidence=result.confidence,
            suggested_chart_type=result.chart_type,
            raw_question=body.question,
        )

    @app.post("/dashboards", response_model=DashboardResponse)
    def create_dashboard(
        body: DashboardCreateRequest,
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_RUN_INTERNAL)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> DashboardResponse:
        del principal
        dashboard_id = f"dash-{uuid4().hex[:12]}"
        cards = tuple(
            DashboardCard(
                card_id=f"card-{uuid4().hex[:12]}",
                title=card.title,
                question=card.question,
                metric_name=card.metric_name,
                chart_type=card.chart_type,
            )
            for card in body.cards
        )
        from agent_os_core.dashboard import _utc_now_iso

        dashboard = Dashboard(
            dashboard_id=dashboard_id,
            tenant_id=tenant_id,
            title=body.title,
            cards=cards,
            created_at=_utc_now_iso(),
        )
        app.state.dashboard_store.save(dashboard)
        return _dashboard_to_response(dashboard)

    @app.get("/dashboards/{dashboard_id}", response_model=DashboardResponse)
    def get_dashboard(
        dashboard_id: str,
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_RUN_INTERNAL)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> DashboardResponse:
        del principal
        dashboard = app.state.dashboard_store.get(dashboard_id, tenant_id)
        if dashboard is None:
            raise HTTPException(status_code=404, detail=f"Dashboard {dashboard_id!r} not found.")
        return _dashboard_to_response(dashboard)

    @app.get("/dashboards", response_model=DashboardListResponse)
    def list_dashboards(
        limit: int = Query(default=20, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_RUN_INTERNAL)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> DashboardListResponse:
        del principal
        dashboards = app.state.dashboard_store.list(tenant_id, limit=limit, offset=offset)
        # Total requires a separate count; for the in-memory store we can iterate.
        total = len(app.state.dashboard_store.list(tenant_id, limit=10_000_000, offset=0))
        return DashboardListResponse(
            items=[_dashboard_to_response(d) for d in dashboards],
            total=total,
        )

    def _dashboard_to_response(dashboard: Dashboard) -> DashboardResponse:
        return DashboardResponse(
            dashboard_id=dashboard.dashboard_id,
            tenant_id=dashboard.tenant_id,
            title=dashboard.title,
            created_at=dashboard.created_at,
            cards=[
                {
                    "card_id": card.card_id,
                    "title": card.title,
                    "question": card.question,
                    "metric_name": card.metric_name,
                    "chart_type": card.chart_type,
                }
                for card in dashboard.cards
            ],
        )

    @app.get("/runs/{trace_id}/report", response_model=RunReportResponse)
    def get_run_report(
        trace_id: str,
        audience: Literal["internal", "external"] = Query(default="internal"),
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_REPORT_READ)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        projected_audience = "external" if principal.audience_ceiling == "external" else audience
        payload = report_snapshot_service(
            app.state.report_store,
            trace_id=trace_id,
            audience=projected_audience,
            tenant_id=tenant_id,
        )
        if payload is None:
            raise HTTPException(status_code=404, detail=f"No report snapshot for {trace_id!r}.")
        return payload

    @app.post(
        "/agent-runtime/runs/{runtime_run_id}/resume",
        response_model=RuntimeResumeResponse,
        responses={
            404: {
                "model": RuntimeResumeErrorResponse,
                "description": "Agent Runtime checkpoint not found.",
            },
            409: {
                "model": RuntimeResumeErrorResponse,
                "description": "Agent Runtime checkpoint mismatch or policy denial.",
            },
            500: {
                "model": RuntimeResumeErrorResponse,
                "description": "Agent Runtime checkpoint resume failed internally.",
            },
            503: {
                "model": RuntimeResumeErrorResponse,
                "description": "Agent Runtime checkpoint store is not configured.",
            },
        },
    )
    def post_agent_runtime_resume(
        runtime_run_id: str,
        body: RuntimeResumeRequest,
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_RUNTIME_RESUME)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        # Resume returns only a safe reference to the checkpointed result. It never
        # re-runs the Trusted Loop body and never exposes raw args or tool output.
        checkpoint_store = app.state.agent_checkpoint_store
        if checkpoint_store is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "CHECKPOINT_NOT_AVAILABLE",
                    "message": "Agent Runtime checkpoint store is not configured.",
                    "stage": "agent_runtime",
                    "runtime_run_id": runtime_run_id,
                    "runtime_trace_id": None,
                },
            )
        try:
            snapshot = checkpoint_store.get(runtime_run_id)
        except Exception:  # noqa: BLE001 - checkpoint backend details must stay internal
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "CHECKPOINT_READ_FAILED",
                    "message": "Agent Runtime checkpoint read failed.",
                    "stage": "agent_runtime",
                    "runtime_run_id": runtime_run_id,
                    "runtime_trace_id": None,
                },
            ) from None
        if snapshot is None or snapshot.last_result is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "CHECKPOINT_NOT_FOUND",
                    "message": f"checkpoint not found for run_id: {runtime_run_id}",
                    "stage": "agent_runtime",
                    "runtime_run_id": runtime_run_id,
                    "runtime_trace_id": None,
                },
            )
        if body.runtime_trace_id != snapshot.trace_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "CHECKPOINT_MISMATCH",
                    "message": "checkpoint mismatch: runtime_trace_id",
                    "stage": "agent_runtime",
                    "runtime_run_id": runtime_run_id,
                    "runtime_trace_id": None,
                },
            )
        agent_runtime_trace_writer = AgentTraceWriter()
        if app.state.factory is not None:
            agent_runtime_adapter = app.state.factory.build_agent_runtime_adapter(
                app.state.runtime,
                checkpoint_store=checkpoint_store,
                trace_writer=agent_runtime_trace_writer,
            )
        else:
            agent_runtime_adapter = TrustedLoopAgentRuntimeAdapter(
                app.state.runtime,
                checkpoint_store=checkpoint_store,
                shell_view=getattr(app.state.runtime, "shell_view", None),
                trace_writer=agent_runtime_trace_writer,
            )
        agent_context = AgentRunContext(
            tenant_id=tenant_id,
            workspace_id="default",
            principal_id=principal.kind,
            principal_role=principal.kind,
            run_id=runtime_run_id,
            trace_id=snapshot.trace_id,
            policy_scope=frozenset({"trusted_loop:evaluate"}),
            metadata={
                "surface": "POST /agent-runtime/runs/{runtime_run_id}/resume",
                "principal_kind": principal.kind,
            },
        )
        agent_call = AgentToolCall(
            call_id=f"{TrustedLoopAgentRuntimeAdapter.TOOL_NAME}:{runtime_run_id}",
            tool_name=TrustedLoopAgentRuntimeAdapter.TOOL_NAME,
            args={"question": body.question, "parameters": body.parameters},
        )
        try:
            agent_result = agent_runtime_adapter.runtime.resume_from_checkpoint(
                agent_call,
                agent_context,
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
                tenant_id=tenant_id,
            )
            status_code = 404 if agent_result.error_code == "CHECKPOINT_NOT_FOUND" else 409
            if agent_result.status in {"tool_error", "checkpoint_error"}:
                status_code = 500
            raise HTTPException(
                status_code=status_code,
                detail=_runtime_resume_error_detail(agent_result, runtime_run_id=runtime_run_id),
            )

        output_ref = _runtime_resume_output_ref(agent_result.output)
        business_trace_id = output_ref.get("business_trace_id")
        if isinstance(business_trace_id, str) and business_trace_id:
            _persist_agent_runtime_appended_trace(
                app.state.runtime,
                trace_id=business_trace_id,
                agent_runtime_adapter=agent_runtime_adapter,
                tenant_id=tenant_id,
            )
        return {
            "runtime_run_id": runtime_run_id,
            "runtime_trace_id": snapshot.trace_id,
            "tool_name": agent_result.tool_name,
            "status": agent_result.status,
            "resumed": True,
            "error_code": None,
            "output_ref": output_ref,
        }

    @app.post("/outcomes", response_model=OutcomeResponse)
    def post_outcome(
        body: OutcomeRequest,
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_OUTCOME_WRITE)),
        tenant_id: str = Depends(require_tenant_id),
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
            tenant_id=tenant_id,
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
        _check_quota(tenant_id, "outcome_record", body.trace_id)
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
                tenant_id=tenant_id,
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
            knowledge_context_refs=_knowledge_context_refs_from_output(agent_result.output),
            tenant_id=tenant_id,
        )
        return agent_result.output if isinstance(agent_result.output, dict) else {}

    @app.post("/adoptions", response_model=AdoptionResponse)
    def post_adoption(
        body: AdoptionRequest,
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_ADOPTION_WRITE)),
        tenant_id: str = Depends(require_tenant_id),
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
            tenant_id=tenant_id,
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
        _check_quota(tenant_id, "adoption_record", body.trace_id)
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
                tenant_id=tenant_id,
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
            knowledge_context_refs=_knowledge_context_refs_from_output(agent_result.output),
            tenant_id=tenant_id,
        )
        return agent_result.output if isinstance(agent_result.output, dict) else {}

    @app.get("/approvals", response_model=ApprovalListResponse)
    def list_approvals(
        status: str | None = None,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_APPROVAL_READ)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        records = app.state.runtime.approval_runtime.list(
            status=status, limit=limit, offset=offset, tenant_id=tenant_id
        )
        return {
            "items": [
                {
                    "approval_id": r.approval_id,
                    "proposal_id": r.proposal_id,
                    "status": r.status,
                    "approver_role": r.approver_role,
                    "approved_by": r.approved_by,
                    "reason": r.reason,
                }
                for r in records
            ],
            "total": len(records),
            "limit": limit,
            "offset": offset,
        }

    @app.get(
        "/approvals/{approval_id}",
        response_model=ApprovalDetailResponse,
        responses={
            404: {
                "model": ApprovalExecuteErrorResponse,
                "description": "Approval not found.",
            },
        },
    )
    def get_approval(
        approval_id: str,
        principal: ApiPrincipal = Depends(require_api_scope(API_SCOPE_APPROVAL_READ)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        try:
            record = app.state.runtime.approval_runtime.get(approval_id, tenant_id=tenant_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "APPROVAL_NOT_FOUND",
                    "message": str(exc),
                    "approval_id": approval_id,
                },
            ) from exc
        # ADR-0014: render the choice set snapshotted at proposal time. Stable
        # neutral order (lexical by action), recommendation flagged, never
        # reordered to the top. The approvals surface is internal/viewer-scoped
        # (no external principal holds approvals:read), so no audience redaction
        # ceiling applies here beyond the scope gate itself.
        #
        # Durability (defect 2 fix): prefer the choice set persisted on the ApprovalRecord.
        # It survives the approval-resume context deletion after execution, so a post-execution
        # audit still shows WHAT was decided between. Fall back to the live approval-resume
        # context only for legacy records created before the durable snapshot existed.
        record_alternatives = tuple(getattr(record, "alternatives", ()) or ())
        record_rationale = getattr(record, "single_option_rationale", None)
        if record_alternatives or record_rationale:
            source_alternatives = record_alternatives
            single_option_rationale = record_rationale
        else:
            context_store = getattr(app.state.runtime, "approval_context_store", None)
            context = (
                context_store.get(approval_id, tenant_id=tenant_id)
                if context_store is not None
                else None
            )
            source_alternatives = tuple(getattr(context, "alternatives", ()) or ())
            single_option_rationale = getattr(context, "single_option_rationale", None)
        alternatives = sorted(
            source_alternatives,
            key=lambda alternative: alternative.action,
        )
        return {
            "approval_id": record.approval_id,
            "proposal_id": record.proposal_id,
            "status": record.status,
            "approver_role": record.approver_role,
            "approved_by": record.approved_by,
            "reason": record.reason,
            "alternatives": [
                {
                    "action": alternative.action,
                    "rationale": alternative.rationale,
                    "risk_level": (
                        alternative.risk_level.value if alternative.risk_level is not None else None
                    ),
                    "recommended": alternative.recommended,
                }
                for alternative in alternatives
            ],
            "single_option_rationale": single_option_rationale,
        }

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
        operator_principal: ApiPrincipal = Depends(require_operator_api_key),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        # Approval-bound action execution: approve then execute the exact pending
        # context captured by the prior /runs call. No automatic R4/R5 execution.
        # The operator key channel is the ONLY auth surface for this endpoint;
        # require_operator_api_key already enforces the approvals:execute scope.
        agent_runtime_trace_writer = AgentTraceWriter()
        agent_runtime_adapter = TrustedLoopApprovalExecutionRuntimeAdapter(
            app.state.runtime,
            checkpoint_store=app.state.agent_checkpoint_store,
            shell_view=getattr(app.state.runtime, "shell_view", None),
            trace_writer=agent_runtime_trace_writer,
        )
        agent_context = AgentRunContext(
            tenant_id=tenant_id,
            workspace_id="default",
            principal_id=operator_principal.kind,
            principal_role=operator_principal.kind,
            run_id=f"http-approval-execute-{uuid4().hex[:12]}",
            trace_id=f"agent-trace-{uuid4().hex[:12]}",
            policy_scope=frozenset({"trusted_loop:approval_execute"}),
            risk_ceiling="R3",
            approval_id=approval_id,
            metadata={
                "surface": "POST /approvals/{approval_id}/execute",
                "principal_kind": operator_principal.kind,
            },
        )
        _check_quota(tenant_id, "approval_execute", approval_id)
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

    @app.get("/knowledge/review-queue", response_model=KnowledgeReviewQueueResponse)
    def get_knowledge_review_queue(
        quality_status: str | None = Query(
            default=None,
            description="safe quality status filter",
            enum=KNOWLEDGE_QUALITY_STATUS_VALUES,
        ),
        review_priority: str | None = Query(
            default=None,
            description="safe review priority filter: high|medium|low",
            enum=KNOWLEDGE_REVIEW_PRIORITY_VALUES,
        ),
        recommended_review_action: str | None = Query(
            default=None,
            description="safe recommended review action filter",
            enum=KNOWLEDGE_RECOMMENDED_REVIEW_ACTION_VALUES,
        ),
        review_rationale_code: str | None = Query(
            default=None,
            description="safe review rationale filter",
            enum=KNOWLEDGE_REVIEW_RATIONALE_CODE_VALUES,
        ),
        order_by: str | None = Query(
            default=None,
            description="optional deterministic review-queue ordering",
            json_schema_extra={"enum": KNOWLEDGE_REVIEW_QUEUE_ORDER_BY_VALUES},
        ),
        limit: int | None = Query(
            default=None,
            description="maximum number of review-queue items to return",
        ),
        offset: int | None = Query(
            default=None,
            description="zero-based review-queue item offset",
        ),
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_KNOWLEDGE_REVIEW)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        # P1-05 review queue is read-only: it lists DRAFT candidates that the
        # Trusted Loop already produced. It does not promote or publish assets.
        try:
            return knowledge_review_queue_service(
                app.state.runtime,
                quality_status=quality_status,
                review_priority=review_priority,
                recommended_review_action=recommended_review_action,
                review_rationale_code=review_rationale_code,
                order_by=order_by,
                limit=limit,
                offset=offset,
                tenant_id=tenant_id,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "KNOWLEDGE_REVIEW_QUEUE_INVALID_REQUEST",
                    "message": str(exc),
                },
            ) from exc

    @app.get("/knowledge/assets", response_model=KnowledgeAssetCatalogResponse)
    def get_knowledge_assets(
        state: str | None = Query(
            default=None,
            description="lifecycle filter: draft|active|published|deprecated|all",
        ),
        quality_status: str | None = Query(
            default=None,
            description="safe quality status filter",
            enum=KNOWLEDGE_QUALITY_STATUS_VALUES,
        ),
        review_priority: str | None = Query(
            default=None,
            description="safe review priority filter: high|medium|low",
            enum=KNOWLEDGE_REVIEW_PRIORITY_VALUES,
        ),
        recommended_review_action: str | None = Query(
            default=None,
            description="safe recommended review action filter",
            enum=KNOWLEDGE_RECOMMENDED_REVIEW_ACTION_VALUES,
        ),
        review_rationale_code: str | None = Query(
            default=None,
            description="safe review rationale filter",
            enum=KNOWLEDGE_REVIEW_RATIONALE_CODE_VALUES,
        ),
        order_by: str | None = Query(
            default=None,
            description="optional deterministic catalog ordering",
            json_schema_extra={"enum": KNOWLEDGE_CATALOG_ORDER_BY_VALUES},
        ),
        limit: int | None = Query(
            default=None,
            description="maximum number of catalog items to return",
        ),
        offset: int | None = Query(
            default=None,
            description="zero-based catalog item offset",
        ),
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_KNOWLEDGE_REVIEW)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        try:
            return knowledge_asset_catalog_service(
                app.state.runtime,
                lifecycle_state=state,
                quality_status=quality_status,
                review_priority=review_priority,
                recommended_review_action=recommended_review_action,
                review_rationale_code=review_rationale_code,
                order_by=order_by,
                limit=limit,
                offset=offset,
                tenant_id=tenant_id,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "KNOWLEDGE_CATALOG_INVALID_REQUEST",
                    "message": str(exc),
                },
            ) from exc

    @app.get(
        "/knowledge/assets/quality-summary",
        response_model=KnowledgeAssetQualitySummaryResponse,
        responses={400: {"description": "Invalid quality_status filter"}},
    )
    def get_knowledge_asset_quality_summary(
        quality_status: str | None = Query(
            default=None,
            description="optional quality status filter",
            json_schema_extra={"enum": KNOWLEDGE_QUALITY_STATUS_VALUES},
        ),
        review_priority: str | None = Query(
            default=None,
            description="optional reviewer priority filter",
            json_schema_extra={"enum": KNOWLEDGE_REVIEW_PRIORITY_VALUES},
        ),
        recommended_review_action: str | None = Query(
            default=None,
            description="optional recommended review action filter",
            json_schema_extra={"enum": KNOWLEDGE_RECOMMENDED_REVIEW_ACTION_VALUES},
        ),
        review_rationale_code: str | None = Query(
            default=None,
            description="optional review rationale code filter",
            json_schema_extra={"enum": KNOWLEDGE_REVIEW_RATIONALE_CODE_VALUES},
        ),
        order_by: str | None = Query(
            default=None,
            description="optional deterministic quality summary ordering",
            json_schema_extra={"enum": KNOWLEDGE_QUALITY_SUMMARY_ORDER_BY_VALUES},
        ),
        limit: int | None = Query(
            default=None,
            description="optional bounded page size for quality summary items",
            json_schema_extra={"minimum": 1, "maximum": 100},
        ),
        offset: int | None = Query(
            default=None,
            description="optional zero-based page offset for quality summary items",
            json_schema_extra={"minimum": 0},
        ),
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_KNOWLEDGE_REVIEW)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        try:
            return knowledge_asset_quality_summary_service(
                app.state.runtime,
                quality_status=quality_status,
                review_priority=review_priority,
                recommended_review_action=recommended_review_action,
                review_rationale_code=review_rationale_code,
                order_by=order_by,
                limit=limit,
                offset=offset,
                tenant_id=tenant_id,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "KNOWLEDGE_QUALITY_SUMMARY_INVALID_REQUEST",
                    "message": str(exc),
                },
            ) from exc

    @app.get("/knowledge/assets/{asset_id}", response_model=KnowledgeAssetDetailResponse)
    def get_knowledge_asset_detail(
        asset_id: str,
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_KNOWLEDGE_REVIEW)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        try:
            return knowledge_asset_detail_service(
                app.state.runtime, asset_id=asset_id, tenant_id=tenant_id
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "KNOWLEDGE_ASSET_NOT_FOUND",
                    "message": "KnowledgeAsset was not found.",
                    "asset_id": asset_id,
                },
            ) from exc

    @app.get(
        "/knowledge/assets/{asset_id}/lifecycle-events",
        response_model=KnowledgeAssetLifecycleEventsResponse,
    )
    def get_knowledge_asset_lifecycle_events(
        asset_id: str,
        limit: int | None = Query(
            default=None,
            description="optional bounded page size for lifecycle events",
            json_schema_extra={"minimum": 1, "maximum": 100},
        ),
        offset: int | None = Query(
            default=None,
            description="optional zero-based page offset for lifecycle events",
            json_schema_extra={"minimum": 0},
        ),
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_KNOWLEDGE_REVIEW)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        try:
            return knowledge_asset_lifecycle_events_service(
                app.state.runtime,
                asset_id=asset_id,
                limit=limit,
                offset=offset,
                tenant_id=tenant_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "KNOWLEDGE_ASSET_NOT_FOUND",
                    "message": "KnowledgeAsset was not found.",
                    "asset_id": asset_id,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "KNOWLEDGE_LIFECYCLE_EVENTS_INVALID_REQUEST",
                    "message": str(exc),
                },
            ) from exc

    @app.get(
        "/knowledge/assets/{asset_id}/usage-events",
        response_model=KnowledgeAssetUsageEventsResponse,
    )
    def get_knowledge_asset_usage_events(
        asset_id: str,
        limit: int | None = Query(
            default=None,
            description="optional bounded page size for usage events",
            json_schema_extra={"minimum": 1, "maximum": 100},
        ),
        offset: int | None = Query(
            default=None,
            description="optional zero-based page offset for usage events",
            json_schema_extra={"minimum": 0},
        ),
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_KNOWLEDGE_REVIEW)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        try:
            return knowledge_asset_usage_events_service(
                app.state.runtime,
                asset_id=asset_id,
                limit=limit,
                offset=offset,
                tenant_id=tenant_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "KNOWLEDGE_ASSET_NOT_FOUND",
                    "message": "KnowledgeAsset was not found.",
                    "asset_id": asset_id,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "KNOWLEDGE_USAGE_EVENTS_INVALID_REQUEST",
                    "message": str(exc),
                },
            ) from exc

    @app.get(
        "/knowledge/assets/{asset_id}/decision-quality",
        response_model=KnowledgeAssetDecisionQualityResponse,
    )
    def get_knowledge_asset_decision_quality(
        asset_id: str,
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_KNOWLEDGE_REVIEW)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        try:
            return knowledge_asset_decision_quality_service(
                app.state.runtime,
                asset_id=asset_id,
                tenant_id=tenant_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "KNOWLEDGE_ASSET_NOT_FOUND",
                    "message": "KnowledgeAsset was not found.",
                    "asset_id": asset_id,
                },
            ) from exc

    @app.post(
        "/knowledge/review-queue/{asset_id}/decision",
        response_model=KnowledgeReviewActionResponse,
    )
    def post_knowledge_review_decision(
        asset_id: str,
        request: KnowledgeReviewActionRequest,
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_KNOWLEDGE_REVIEW)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        try:
            return knowledge_review_action_service(
                app.state.runtime,
                asset_id=asset_id,
                action=request.action,
                reviewer=request.reviewer,
                reason=request.reason,
                tenant_id=tenant_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "KNOWLEDGE_ASSET_NOT_FOUND",
                    "message": "KnowledgeAsset was not found.",
                    "asset_id": asset_id,
                },
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "KNOWLEDGE_ASSET_NOT_DRAFT",
                    "message": str(exc),
                    "asset_id": asset_id,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "KNOWLEDGE_REVIEW_INVALID_REQUEST",
                    "message": str(exc),
                    "asset_id": asset_id,
                },
            ) from exc

    @app.post(
        "/knowledge/assets/{asset_id}/publish",
        response_model=KnowledgeReviewActionResponse,
    )
    def post_knowledge_publish(
        asset_id: str,
        request: KnowledgePublishRequest,
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_KNOWLEDGE_REVIEW)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        try:
            return knowledge_publish_service(
                app.state.runtime,
                asset_id=asset_id,
                reviewer=request.reviewer,
                reason=request.reason,
                tenant_id=tenant_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "KNOWLEDGE_ASSET_NOT_FOUND",
                    "message": "KnowledgeAsset was not found.",
                    "asset_id": asset_id,
                },
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "KNOWLEDGE_ASSET_NOT_ACTIVE",
                    "message": str(exc),
                    "asset_id": asset_id,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "KNOWLEDGE_PUBLISH_INVALID_REQUEST",
                    "message": str(exc),
                    "asset_id": asset_id,
                },
            ) from exc

    @app.post(
        "/knowledge/assets/{asset_id}/deprecate",
        response_model=KnowledgeReviewActionResponse,
    )
    def post_knowledge_deprecate(
        asset_id: str,
        request: KnowledgePublishRequest,
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_KNOWLEDGE_REVIEW)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        try:
            return knowledge_deprecate_service(
                app.state.runtime,
                asset_id=asset_id,
                reviewer=request.reviewer,
                reason=request.reason,
                tenant_id=tenant_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "KNOWLEDGE_ASSET_NOT_FOUND",
                    "message": "KnowledgeAsset was not found.",
                    "asset_id": asset_id,
                },
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "KNOWLEDGE_ASSET_NOT_DEPRECATABLE",
                    "message": str(exc),
                    "asset_id": asset_id,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "KNOWLEDGE_DEPRECATE_INVALID_REQUEST",
                    "message": str(exc),
                    "asset_id": asset_id,
                },
            ) from exc

    @app.get("/knowledge/search", response_model=SearchResponse)
    def get_knowledge_search(
        q: str = Query(..., min_length=1, description="free-text question"),
        metric: str | None = Query(default=None, description="filter: exact metric name"),
        owner: str | None = Query(default=None, description="filter: exact owner"),
        k: int = Query(default=5, ge=1, le=50),
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_KNOWLEDGE_SEARCH)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        if app.state.retriever is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Knowledge retriever is not configured. Pass retriever= to create_app "
                    "(e.g. factory.build_knowledge_retriever()) to enable this endpoint."
                ),
            )
        return search_service(
            app.state.retriever, text=q, metric_name=metric, owner=owner, k=k, tenant_id=tenant_id
        )

    @app.get("/traces/{trace_id}", response_model=TraceResponse)
    def get_trace(
        trace_id: str,
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_TRACE_READ)),
        tenant_id: str = Depends(require_tenant_id),
    ) -> dict[str, Any]:
        payload = trace_service(
            app.state.runtime.trace_store, trace_id=trace_id, tenant_id=tenant_id
        )
        if payload is None:
            raise HTTPException(status_code=404, detail=f"No run trace for {trace_id!r}.")
        return payload

    _install_openapi_contract_hardening(app)
    return app
