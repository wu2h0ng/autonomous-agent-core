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

from .outcome_service import record_outcome_service, run_service, search_service
from .runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

API_KEY_ENV = "AGENT_OS_API_KEY"
API_KEY_HEADER = "X-API-Key"


class RunRequest(BaseModel):
    question: str = Field(..., min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class RelatedKnowledgeItem(BaseModel):
    """Prior organizational knowledge recalled for this run (AR-20260611)."""

    asset_id: str
    title: str
    score: float


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
    (unsafe SQL, unknown metric, no template, no provider, ...).
    """

    code: str
    message: str
    stage: str
    details: list[str] = Field(default_factory=list)


class BlockedResponse(BaseModel):
    detail: BlockDetail


def _build_default_factory() -> ContentCommerceRuntimeFactory:
    # 12-factor: the deployed surface selects real backends via environment variables
    # (AGENT_OS_EXECUTOR / AGENT_OS_STORE_BACKEND / AGENT_OS_DATABASE_URL /
    # AGENT_OS_DOMAIN_PACK); defaults preserve the in-memory demo behavior.
    return ContentCommerceRuntimeFactory(RuntimeFactoryConfig.from_env())


def create_app(
    runtime: Any | None = None, *, retriever: Any | None = None, api_key: str | None = None
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
    else:
        shared_runtime = runtime
        shared_retriever = retriever
    configured_key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)

    app = FastAPI(title="Agent OS API", version="0.1.0")
    app.state.runtime = shared_runtime
    app.state.retriever = shared_retriever
    app.state.api_key = configured_key

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
        return record_outcome_service(
            app.state.runtime,
            trace_id=body.trace_id,
            outcome=body.outcome,
            reviewer=body.reviewer,
            metric_deltas=body.metric_deltas,
        )

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

    return app
