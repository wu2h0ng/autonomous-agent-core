"""SPINE-1: Data Agent domain contracts (ported from the donor `agent_os_contracts`).

Proves the ported contract types import and behave (EvidenceChain completeness / typed completeness).
"""

from __future__ import annotations

from domain_packs.data_agent.domain_contracts import (
    ActionProposal,
    BusinessIntent,
    Claim,
    ConfidenceScore,
    ConsequencePreview,
    DataProductCandidate,
    EvalBinding,
    EvidenceChain,
    MetricContract,
    ProviderContract,
    ProviderKind,
    QueryPlan,
    QueryResult,
    QueryResultSummary,
    RiskLevel,
    SQLSafetyResult,
    SQLTemplate,
    SemanticObject,
    StateSnapshot,
)


def _metric() -> MetricContract:
    return MetricContract(
        metric_name="gmv",
        display_name="GMV",
        definition="Gross merchandise value",
        owner="revenue_ops",
        unit="CNY",
        allowed_schemas=("sales",),
        version="v1",
        verified_queries=(
            SQLTemplate(template_id="t", metric_name="gmv", sql="SELECT 1 FROM sales.orders LIMIT 1"),
        ),
    )


def _chain(*, allowed: bool = True, typed: bool = False) -> EvidenceChain:
    kwargs = {}
    if typed:
        kwargs = dict(
            metric_contract_refs=("gmv:v1",),
            provider_contract_refs=("pg",),
            query_result_summary=QueryResultSummary(row_count=1, column_names=("gmv",)),
            claims=(Claim(statement="GMV=1"),),
            confidence_score=ConfidenceScore(score=0.9),
            eval_bindings=(EvalBinding(eval_case_id="trace-1", dimension="evidence"),),
        )
    return EvidenceChain(
        evidence_chain_id="ec-1",
        intent=BusinessIntent(intent_id="i-1", question="GMV?", metric_name="gmv"),
        metric_contract=_metric(),
        query_plan=QueryPlan("gmv", "SELECT 1 FROM sales.orders LIMIT 1", {}),
        sql_safety=SQLSafetyResult(allowed=allowed, reasons=(), checked_schemas=("sales",)),
        query_result=QueryResult(rows=({"gmv": 1},), row_count=1),
        conclusion="GMV=1",
        confidence=0.9,
        limitations=(),
        trace_id="trace-1",
        **kwargs,
    )


def test_evidence_chain_is_complete_only_when_sql_allowed() -> None:
    assert _chain(allowed=True).is_complete() is True
    assert _chain(allowed=False).is_complete() is False


def test_evidence_chain_typed_completeness_requires_structured_fields() -> None:
    assert _chain(typed=False).is_typed_complete() is False
    assert _chain(typed=True).is_typed_complete() is True


def test_domain_objects_construct() -> None:
    provider = ProviderContract(
        provider_id="pg",
        kind=ProviderKind.WAREHOUSE,
        name="pg",
        owner="data",
        allowed_schemas=("sales",),
    )
    candidate = DataProductCandidate(
        data_product_id="dp-1",
        requirement_id="req-1",
        name="GMV product",
        owner="revenue_ops",
        query_plan_id=None,
        lineage_snapshot_id=None,
    )
    semantic = SemanticObject(
        object_id="o-1",
        name="GMV",
        object_type="metric",
        description="gross merchandise value",
        owner="revenue_ops",
        related_metrics=("gmv",),
    )
    proposal = ActionProposal(
        proposal_id="p-1",
        evidence_chain_id="ec-1",
        target_object="gmv",
        recommended_action="investigate",
        reason="drop detected",
        risk_level=RiskLevel.R2,
        expected_impact="recovery",
        approval_required=True,
        approver_role="operator",
    )
    snapshot = StateSnapshot(
        snapshot_id="s-1",
        operation_id="op-1",
        connector_name="action_record",
        snapshot_type="pre_write",
        state_payload={"k": "v"},
        created_at="2026-09-15T00:00:00+00:00",
    )

    assert provider.provider_id == "pg"
    assert candidate.data_product_id == "dp-1"
    assert semantic.related_metrics == ("gmv",)
    assert proposal.risk_level is RiskLevel.R2
    assert proposal.approval_required is True
    assert snapshot.state_payload == {"k": "v"}


def test_consequence_preview_defaults_to_unavailable() -> None:
    preview = ConsequencePreview(action_type="execute")

    assert preview.available is False
    assert preview.prior_executions == 0
