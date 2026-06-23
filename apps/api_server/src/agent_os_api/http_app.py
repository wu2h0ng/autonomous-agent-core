"""FastAPI HTTP surface for the Trusted Loop.

This is the only module in the package that imports FastAPI. ``__init__.py`` and
``cli.py`` deliberately do NOT import it, so non-HTTP users (and the canonical
bare-env ``make ci``) never need fastapi installed.

The app holds ONE shared ``TrustedLoopRuntime`` for its lifetime so the
in-memory knowledge/feedback stores persist across requests: a ``POST /runs``
and a later ``POST /outcomes`` for the same trace see the same state.

Auth boundary: every protected route requires an ``X-API-Key`` header matching
the configured key (``create_app(api_key=...)`` or env ``AGENT_OS_API_KEY``).
If no key is configured the protected routes reject with 503 rather than
silently allowing access; a wrong/missing key returns 401.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from agent_os_contracts import CausalAttributionMethod, CausalOutcomeAttribution

from .outcome_service import (
    approve_and_execute_service,
    attest_adoption_service,
    record_outcome_service,
    run_service,
    search_service,
    trace_service,
)
from .runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

API_KEY_ENV = "AGENT_OS_API_KEY"
OPERATOR_API_KEY_ENV = "AGENT_OS_OPERATOR_API_KEY"
API_KEY_HEADER = "X-API-Key"
OPERATOR_API_KEY_HEADER = "X-Operator-Key"


class RunRequest(BaseModel):
    question: str = Field(..., min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


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


class UserResultReport(BaseModel):
    title: str
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


class UserResultDashboard(BaseModel):
    title: str
    widgets: list[UserResultDashboardWidget] = Field(default_factory=list)


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
    api_key: str | None = None,
    operator_api_key: str | None = None,
    adoption_ingest: Any | None = None,
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
        api_key: The required ``X-API-Key`` value. Falls back to the
            ``AGENT_OS_API_KEY`` environment variable. If neither is set, the
            protected routes reject with 503.
    """
    if runtime is None:
        factory = _build_default_factory()
        shared_runtime = factory.build()
        shared_retriever = (
            retriever if retriever is not None else factory.build_knowledge_retriever()
        )
        # Operator value channel over the SAME ledger the runtime reads (P5.1a):
        # the default app can promote knowledge from realized adoption out of the box.
        shared_adoption_ingest = (
            adoption_ingest if adoption_ingest is not None else factory.adoption_ingest()
        )
    else:
        shared_runtime = runtime
        shared_retriever = retriever
        shared_adoption_ingest = adoption_ingest
    configured_key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)
    configured_operator_key = (
        operator_api_key if operator_api_key is not None else os.environ.get(OPERATOR_API_KEY_ENV)
    )

    app = FastAPI(title="Agent OS API", version="0.1.0")
    app.state.runtime = shared_runtime
    app.state.retriever = shared_retriever
    app.state.api_key = configured_key
    app.state.operator_api_key = configured_operator_key
    app.state.adoption_ingest = shared_adoption_ingest

    def require_api_key(x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER)) -> None:
        if not app.state.api_key:
            raise HTTPException(
                status_code=503,
                detail=(
                    "API key is not configured. Set the AGENT_OS_API_KEY environment "
                    "variable (or pass api_key to create_app) to enable this endpoint."
                ),
            )
        if x_api_key != app.state.api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key.")

    def require_operator_api_key(
        x_operator_key: str | None = Header(default=None, alias=OPERATOR_API_KEY_HEADER),
    ) -> None:
        if not app.state.operator_api_key:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Operator API key is not configured. Set the "
                    "AGENT_OS_OPERATOR_API_KEY environment variable (or pass "
                    "operator_api_key to create_app) to enable approval execution."
                ),
            )
        if x_operator_key != app.state.operator_api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing operator key.")

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
            }
        },
    )
    def post_run(body: RunRequest, _: None = Depends(require_api_key)) -> dict[str, Any]:
        result = run_service(
            app.state.runtime,
            question=body.question,
            parameters=body.parameters,
        )
        if result.get("status") == "blocked":
            # Expected business block (unsafe SQL, unknown metric, ...) -> 422,
            # not a 500: the request was understood but the loop refused to answer.
            raise HTTPException(status_code=422, detail=result["block"])
        return result

    @app.post("/outcomes", response_model=OutcomeResponse)
    def post_outcome(body: OutcomeRequest, _: None = Depends(require_api_key)) -> dict[str, Any]:
        # Self-report only (P5.1b): records feedback, does NOT promote knowledge.
        return record_outcome_service(
            app.state.runtime,
            trace_id=body.trace_id,
            outcome=body.outcome,
            reviewer=body.reviewer,
            metric_deltas=body.metric_deltas,
        )

    @app.post("/adoptions", response_model=AdoptionResponse)
    def post_adoption(body: AdoptionRequest, _: None = Depends(require_api_key)) -> dict[str, Any]:
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
        return attest_adoption_service(
            app.state.runtime,
            app.state.adoption_ingest,
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
        _: None = Depends(require_operator_api_key),
    ) -> dict[str, Any]:
        # Approval-bound action execution: approve then execute the exact pending
        # context captured by the prior /runs call. No automatic R4/R5 execution.
        try:
            return approve_and_execute_service(
                app.state.runtime,
                approval_id=approval_id,
                reason=body.reason,
                approved_by=body.approved_by,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "approval_context_not_found",
                    "message": str(exc).strip("'"),
                    "approval_id": approval_id,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "approval_execution_conflict",
                    "message": str(exc),
                    "approval_id": approval_id,
                },
            ) from exc

    @app.get("/knowledge/search", response_model=SearchResponse)
    def get_knowledge_search(
        q: str = Query(..., min_length=1, description="free-text question"),
        metric: str | None = Query(default=None, description="filter: exact metric name"),
        owner: str | None = Query(default=None, description="filter: exact owner"),
        k: int = Query(default=5, ge=1, le=50),
        _: None = Depends(require_api_key),
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
    def get_trace(trace_id: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
        payload = trace_service(app.state.runtime.trace_store, trace_id=trace_id)
        if payload is None:
            raise HTTPException(status_code=404, detail=f"No run trace for {trace_id!r}.")
        return payload

    return app
