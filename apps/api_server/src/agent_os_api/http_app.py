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
    AgentToolCall,
    AgentTraceWriter,
    TrustedLoopApprovalExecutionRuntimeAdapter,
    TrustedLoopAgentRuntimeAdapter,
)

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

API_KEY_ENV = "AGENT_OS_API_KEY"
EXTERNAL_API_KEY_ENV = "AGENT_OS_EXTERNAL_API_KEY"
OPERATOR_API_KEY_ENV = "AGENT_OS_OPERATOR_API_KEY"
API_KEY_HEADER = "X-API-Key"
OPERATOR_API_KEY_HEADER = "X-Operator-Key"
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
KNOWLEDGE_QUALITY_SUMMARY_ORDER_BY_VALUES = ["review_priority"]
API_SCOPE_RUN_INTERNAL = "runs:internal"
API_SCOPE_RUN_EXTERNAL = "runs:external"
API_SCOPE_OUTCOME_WRITE = "outcomes:write"
API_SCOPE_ADOPTION_WRITE = "adoptions:write"
API_SCOPE_KNOWLEDGE_SEARCH = "knowledge:search"
API_SCOPE_KNOWLEDGE_REVIEW = "knowledge:review"
API_SCOPE_TRACE_READ = "traces:read"
API_SCOPE_REPORT_READ = "reports:read"
API_SCOPE_APPROVAL_EXECUTE = "approvals:execute"
API_SCOPE_RUNTIME_RESUME = "runtime:resume"


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
            API_SCOPE_KNOWLEDGE_REVIEW,
            API_SCOPE_TRACE_READ,
            API_SCOPE_REPORT_READ,
            API_SCOPE_RUNTIME_RESUME,
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


class KnowledgeReviewQueueResponse(BaseModel):
    status: str
    review_state: str
    count: int
    items: list[KnowledgeReviewQueueItem] = Field(default_factory=list)


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
    events: list[KnowledgeAssetLifecycleEvent] = Field(default_factory=list)


class KnowledgeAssetUsageEventItem(BaseModel):
    trace_id: str
    step: Literal["action_proposal", "agent_runtime.tool_succeeded"]
    usage_kind: Literal["proposal_context", "correction_context"]
    asset_id: str
    knowledge_context_refs: list[str] = Field(default_factory=list)
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
        result["runtime_checkpoint_ref"] = _runtime_checkpoint_ref_if_persisted(
            app.state.agent_checkpoint_store,
            agent_context,
            tool_name=TrustedLoopAgentRuntimeAdapter.TOOL_NAME,
        )
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
        agent_runtime_adapter = TrustedLoopAgentRuntimeAdapter(
            app.state.runtime,
            checkpoint_store=checkpoint_store,
            shell_view=getattr(app.state.runtime, "shell_view", None),
            trace_writer=agent_runtime_trace_writer,
        )
        agent_context = AgentRunContext(
            tenant_id="default",
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
            knowledge_context_refs=_knowledge_context_refs_from_output(agent_result.output),
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
            knowledge_context_refs=_knowledge_context_refs_from_output(agent_result.output),
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

    @app.get("/knowledge/review-queue", response_model=KnowledgeReviewQueueResponse)
    def get_knowledge_review_queue(
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_KNOWLEDGE_REVIEW)),
    ) -> dict[str, Any]:
        # P1-05 review queue is read-only: it lists DRAFT candidates that the
        # Trusted Loop already produced. It does not promote or publish assets.
        return knowledge_review_queue_service(app.state.runtime)

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
    ) -> dict[str, Any]:
        try:
            return knowledge_asset_detail_service(app.state.runtime, asset_id=asset_id)
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
        _: ApiPrincipal = Depends(require_api_scope(API_SCOPE_KNOWLEDGE_REVIEW)),
    ) -> dict[str, Any]:
        try:
            return knowledge_asset_lifecycle_events_service(
                app.state.runtime,
                asset_id=asset_id,
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
    ) -> dict[str, Any]:
        try:
            return knowledge_asset_usage_events_service(
                app.state.runtime,
                asset_id=asset_id,
                limit=limit,
                offset=offset,
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
    ) -> dict[str, Any]:
        try:
            return knowledge_asset_decision_quality_service(
                app.state.runtime,
                asset_id=asset_id,
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
    ) -> dict[str, Any]:
        try:
            return knowledge_review_action_service(
                app.state.runtime,
                asset_id=asset_id,
                action=request.action,
                reviewer=request.reviewer,
                reason=request.reason,
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
    ) -> dict[str, Any]:
        try:
            return knowledge_publish_service(
                app.state.runtime,
                asset_id=asset_id,
                reviewer=request.reviewer,
                reason=request.reason,
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
    ) -> dict[str, Any]:
        try:
            return knowledge_deprecate_service(
                app.state.runtime,
                asset_id=asset_id,
                reviewer=request.reviewer,
                reason=request.reason,
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
