"""Data Agent domain contracts (extracted from the donor `agent_os_contracts` package).

Faithful port of the donor domain contract dataclasses (observability + architecture + trusted_loop)
into the domain pack. These carry Metric / SemanticObject / DataProduct / SQL / EvidenceChain /
business-action semantics and therefore must NOT enter `packages/os_core` or `packages/contracts`.
`metric_contracts.py` re-exports the subset it owns so existing domain-pack imports keep working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TelemetryDimension(StrEnum):
    BUSINESS = "business"
    QUALITY = "quality"
    COST = "cost"
    SYSTEM = "system"


@dataclass(frozen=True)
class TelemetryEvent:
    trace_id: str
    dimension: TelemetryDimension
    name: str
    value: float
    unit: str
    attributes: dict[str, Any] = field(default_factory=dict)


class LifecycleState(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


class ProviderKind(StrEnum):
    WAREHOUSE = "warehouse"
    FILE = "file"
    API = "api"
    BROWSER = "browser"
    EVENT = "event"
    MANUAL = "manual"


class DataProductState(StrEnum):
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    PUBLISHED = "published"


class OperationState(StrEnum):
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    OBSERVED = "observed"
    SNAPSHOTTING = "snapshotting"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    COMPENSATING = "compensating"
    FAILED = "failed"
    # ADR-0012 §3.4: policy-evaluation states for R4/R5 auto-execution trace.
    POLICY_EVALUATED = "policy_evaluated"
    POLICY_PRE_APPROVED = "policy_pre_approved"


@dataclass(frozen=True)
class ObjectProperty:
    """A typed field on a SemanticObject, bound to a real data column."""

    name: str
    data_type: str  # "string" | "decimal" | "integer" | "datetime" | "boolean" | ...
    required: bool = False
    description: str = ""
    bound_column: str | None = None


@dataclass(frozen=True)
class LinkType:
    """A named, typed relation between two object types (Palantir Ontology link type).

    Source and target object types must differ (no self-loops at the type level).
    """

    link_type_id: str
    name: str
    source_object_type: str
    target_object_type: str
    description: str = ""
    state: LifecycleState = LifecycleState.DRAFT

    def __post_init__(self) -> None:
        if self.source_object_type == self.target_object_type:
            raise ValueError(
                f"LinkType {self.link_type_id!r} source and target object types "
                f"must differ: {self.source_object_type!r}"
            )


@dataclass(frozen=True)
class ObjectLink:
    """A concrete instance of a LinkType between two registered objects."""

    link_id: str
    link_type_id: str
    source_object_id: str
    target_object_id: str


@dataclass(frozen=True)
class SemanticObject:
    object_id: str
    name: str
    object_type: str
    description: str
    owner: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    related_metrics: tuple[str, ...] = field(default_factory=tuple)
    properties: tuple[ObjectProperty, ...] = field(default_factory=tuple)
    state: LifecycleState = LifecycleState.DRAFT


@dataclass(frozen=True)
class ProviderConnection:
    """Connection specification for a ProviderContract.

    This is a deliberately flat, optional bag of connection fields.  Only the
    fields relevant to ``connection_type`` are populated; the executor/factory
    ignores the rest.  Keeping it inside the contract makes provider selection
    traceable and reviewable without requiring out-of-band secrets in the loop.
    """

    connection_type: str  # postgresql | mysql | clickhouse | feishu | csv | sqlite
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    # Secret-bearing fields are typed as str for tests/local use only; production
    # deployments must inject them via environment/runtime secret resolution.
    password: str | None = None
    api_token: str | None = None
    app_token: str | None = None
    table_id: str | None = None
    path: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderContract:
    provider_id: str
    kind: ProviderKind
    name: str
    owner: str
    allowed_schemas: tuple[str, ...] = field(default_factory=tuple)
    data_classification: str = "internal"
    supports_query: bool = True
    supports_write: bool = False
    cost_hint: str | None = None
    lineage_hint: str | None = None
    connection: ProviderConnection | None = None
    state: LifecycleState = LifecycleState.DRAFT


@dataclass(frozen=True)
class DataRequirement:
    requirement_id: str
    intent_id: str
    metric_names: tuple[str, ...]
    dimensions: tuple[str, ...]
    time_window: dict[str, Any]
    freshness: str | None = None
    provider_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LineageSnapshot:
    lineage_id: str
    provider_id: str
    source_objects: tuple[str, ...]
    generated_by: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DataProductCandidate:
    data_product_id: str
    requirement_id: str
    name: str
    owner: str
    query_plan_id: str | None
    lineage_snapshot_id: str | None
    quality_status: str = "unknown"
    state: DataProductState = DataProductState.CANDIDATE
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LogicalView:
    view_id: str
    name: str
    source_providers: tuple[str, ...]
    owner: str
    view_sql: str | None = None


@dataclass(frozen=True)
class MaterializationHint:
    hint_id: str
    data_product_id: str
    strategy: str  # "view" | "table" | "none"
    refresh_policy: str | None = None


@dataclass(frozen=True)
class FederatedQueryPlan:
    plan_id: str
    sub_queries: tuple[QueryPlan, ...]
    combine_strategy: str
    estimated_cost_hint: str | None = None


@dataclass(frozen=True)
class OperationContract:
    operation_id: str
    name: str
    target_connector: str  # ⚠️ deprecated, retained for backward compat
    risk_level: str
    approval_required: bool
    dry_run_required: bool = True
    rollback_supported: bool = False
    snapshot_required: bool = False
    snapshot_id: str | None = None
    compensating_action: str | None = None
    connector_name: str = "manual_review"
    action_type: str = "propose"
    idempotency_key: str | None = None
    auto_executable: bool = False
    required_policy_guardrails: tuple[str, ...] = ()


@dataclass(frozen=True)
class OperationTrace:
    trace_id: str
    proposal_id: str
    operation_id: str | None
    state: OperationState
    evidence_chain_id: str
    events: tuple[dict[str, Any], ...] = field(default_factory=tuple)


class FeedbackSource:
    """Provenance of a feedback signal (P5.1a, ADR-0001).

    The two channels are schema-separated and must never be co-aggregated:

    - ``RUNTIME_SELF_REPORT``: written by the runtime about its own execution.
      The runtime MAY emit this. It is NOT realized external value.
    - ``EXTERNAL_ADOPTION``: an external attestation that a result was adopted /
      produced business value. This is the signal a self-evolving credit
      mechanism would feed on, so the runtime must NOT be able to mint it — it
      enters only through the operator-exclusive adoption ingest.
    """

    RUNTIME_SELF_REPORT = "runtime_self_report"
    EXTERNAL_ADOPTION = "external_adoption"


class CausalAttributionMethod(StrEnum):
    HOLDOUT = "holdout"
    COUNTERFACTUAL = "counterfactual"
    BEFORE_AFTER = "before_after"
    OPERATOR_ATTESTED = "operator_attested"


@dataclass(frozen=True)
class CausalOutcomeAttribution:
    metric_name: str
    observed_value: float
    counterfactual_value: float
    delta_absolute: float
    delta_percent: float | None
    method: CausalAttributionMethod
    comparison_ref: str
    window_start: str
    window_end: str
    confidence: float
    notes: str | None = None


@dataclass(frozen=True)
class FeedbackEvent:
    feedback_id: str
    trace_id: str
    outcome: str
    metrics: dict[str, Any] = field(default_factory=dict)
    reviewer: str | None = None
    # Provenance channel (P5.1a). Defaults to the safe channel: a bare
    # construction is a runtime self-report, never realized external value.
    source: str = FeedbackSource.RUNTIME_SELF_REPORT
    causal_attribution: CausalOutcomeAttribution | None = None


@dataclass(frozen=True)
class KnowledgeAsset:
    asset_id: str
    title: str
    asset_type: str
    source_trace_id: str | None
    owner: str
    state: LifecycleState = LifecycleState.DRAFT
    # Observed feedback outcome folded in via KnowledgeAssetBuilder.with_feedback
    # (e.g. "adopted"/"rejected"); None until an outcome is recorded. Carries the
    # feedback signal so retrieval projection/weighting can use it.
    outcome: str | None = None
    result_weight: float = 0.0


@dataclass(frozen=True)
class KnowledgeQuery:
    """A retrieval request over the KnowledgeAsset memory.

    ``text`` drives vector + lexical matching; the optional structured fields are
    exact filters (resolved against projected/indexed columns, never JSON scans).
    """

    text: str
    metric_name: str | None = None
    owner: str | None = None
    risk_level: str | None = None
    lifecycle_state: LifecycleState | None = None
    outcome: str | None = None
    k: int = 5


@dataclass(frozen=True)
class RetrievalResult:
    """A retrieved asset plus an explainable score breakdown (the "why").

    ``score_breakdown`` carries the component contributions (vector, lexical,
    fusion, outcome/recency boosts) so every result is auditable.
    """

    asset: KnowledgeAsset
    score: float
    score_breakdown: dict[str, float]


@dataclass(frozen=True)
class StateSnapshot:
    snapshot_id: str
    operation_id: str
    connector_name: str
    snapshot_type: str
    state_payload: dict[str, Any]
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectorExecutionSemantics:
    """Declared execution-audit semantics for a connector.

    These are contract-level defaults, not proof of external success. They let
    the runtime project connector execution consistently without inferring ACKs
    or copying raw connector payloads.
    """

    durability_scope: str = "connector_response"
    replay_status: str = "not_replayed"
    external_ack_status: str = "unknown"
    ledger_status: str = "not_reported"
    supports_idempotency: bool = False
    supports_reconciliation: bool = False

    def audit_defaults(self) -> dict[str, str]:
        return {
            "durability_scope": self.durability_scope,
            "replay_status": self.replay_status,
            "external_ack_status": self.external_ack_status,
            "ledger_status": self.ledger_status,
        }


@dataclass(frozen=True)
class ActionConnectorContract:
    connector_name: str
    display_name: str
    supported_action_types: tuple[str, ...]
    supports_snapshot: bool
    supports_rollback: bool
    compensating_action_description: str | None
    risk_ceiling: str
    owner: str
    execution_semantics: ConnectorExecutionSemantics = field(
        default_factory=ConnectorExecutionSemantics
    )


@dataclass(frozen=True)
class ConnectorExecutionAudit:
    """Safe connector execution projection for traces and operator APIs.

    This contract records connector-reported execution semantics without
    claiming external exactly-once or copying raw action parameters.
    """

    durability_scope: str = "connector_response"
    execution_outcome: str | None = None
    replay_status: str = "not_replayed"
    external_ack_status: str = "unknown"
    ledger_status: str = "not_reported"
    record_id: str | None = None
    external_request_id: str | None = None
    execution_certainty: str | None = None
    ack_status: str | None = None

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> "ConnectorExecutionAudit":
        status = event.get("status")
        replay_status = event.get("replay_status")
        if replay_status is None:
            replay_status = "idempotent_replay" if status == "idempotent_replay" else "not_replayed"
        record_id = event.get("record_id")
        ledger_status = event.get("ledger_status")
        if ledger_status is None:
            ledger_status = "recorded" if record_id else "not_reported"
        return cls(
            durability_scope=event.get("durability_scope", "connector_response"),
            execution_outcome=status,
            replay_status=replay_status,
            external_ack_status=event.get("external_ack_status", "unknown"),
            ledger_status=ledger_status,
            record_id=record_id,
            external_request_id=event.get("external_request_id"),
            execution_certainty=event.get("execution_certainty"),
            ack_status=event.get("ack_status"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "durability_scope": self.durability_scope,
            "execution_outcome": self.execution_outcome,
            "replay_status": self.replay_status,
            "external_ack_status": self.external_ack_status,
            "ledger_status": self.ledger_status,
            "record_id": self.record_id,
            "external_request_id": self.external_request_id,
            "execution_certainty": self.execution_certainty,
            "ack_status": self.ack_status,
        }


class RiskLevel(StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


@dataclass(frozen=True)
class BusinessIntent:
    intent_id: str
    question: str
    metric_name: str
    tenant_id: str = "default"
    workspace_id: str = "default"


@dataclass(frozen=True)
class QualityContract:
    """Quality expectations for a MetricContract."""

    freshness: str | None = None
    null_rate: str | None = None
    owner: str | None = None


@dataclass(frozen=True)
class ActionCandidate:
    """A business action that may be proposed when a metric pattern is observed."""

    action_id: str
    trigger: str | None = None
    risk_level: RiskLevel = RiskLevel.R2
    description: str = ""


@dataclass(frozen=True)
class MetricContract:
    metric_name: str
    display_name: str
    definition: str
    owner: str
    unit: str
    allowed_schemas: tuple[str, ...]
    version: str = "v1"
    dimensions: tuple[str, ...] = field(default_factory=tuple)
    data_classification: DataClassification = DataClassification.INTERNAL
    verified_queries: tuple[SQLTemplate, ...] = field(default_factory=tuple)
    quality_contract: QualityContract | None = None
    action_candidates: tuple[ActionCandidate, ...] = field(default_factory=tuple)
    feedback_metric: str | None = None


@dataclass(frozen=True)
class SQLTemplate:
    template_id: str
    metric_name: str
    sql: str
    required_parameters: tuple[str, ...] = field(default_factory=tuple)
    required_time_parameters: tuple[str, ...] = ("start_date", "end_date")
    default_limit: int = 100
    max_limit: int = 1000
    allow_select_star: bool = False


@dataclass(frozen=True)
class QueryPlan:
    metric_name: str
    sql: str
    parameters: dict[str, Any]
    source_template: SQLTemplate | None = None


@dataclass(frozen=True)
class SQLSafetyIssue:
    code: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class SQLSafetyResult:
    allowed: bool
    reasons: tuple[str, ...]
    checked_schemas: tuple[str, ...]
    checked_tables: tuple[str, ...] = field(default_factory=tuple)
    bound_parameters: tuple[str, ...] = field(default_factory=tuple)
    limit_value: int | None = None
    issues: tuple[SQLSafetyIssue, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class QueryResult:
    rows: tuple[dict[str, Any], ...]
    row_count: int
    # P2-C (ADR-0017): actual recency of the underlying data at query time, in seconds since the
    # source was last refreshed, as reported by the provider/executor. ``None`` = the provider did
    # not report freshness — the EvidenceChain then CAPS and flags confidence as ``freshness_unknown``
    # and never treats the answer as fresh. This is the observable the confidence-derivation rule
    # reads for the DataProduct -> EvidenceChain freshness / tau-consistency factor (never a default
    # high confidence when unknown).
    source_age_seconds: float | None = None


@dataclass(frozen=True)
class MetricContractRef:
    """Lightweight reference to a MetricContract used by an EvidenceChain."""

    metric_name: str
    contract_version: str = "v1"
    ref: str = ""


@dataclass(frozen=True)
class ProviderContractRef:
    """Lightweight reference to a ProviderContract used by an EvidenceChain."""

    provider_id: str
    ref: str = ""


@dataclass(frozen=True)
class QueryResultSummary:
    """Safe summary of a query result for evidence/audit purposes."""

    row_count: int
    column_names: tuple[str, ...] = field(default_factory=tuple)
    sample_fingerprint: str = ""


@dataclass(frozen=True)
class Claim:
    """A typed claim supported by evidence references."""

    statement: str
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    confidence: str = "medium"  # high / medium / low
    scope: str = "in-scope"  # in-scope / out-of-scope


@dataclass(frozen=True)
class Limitation:
    """A limitation of the evidence or conclusion."""

    description: str
    impact: str = ""
    mitigation: str = ""


@dataclass(frozen=True)
class ConfidenceInputs:
    """The observable inputs a :class:`ConfidenceScore` was DERIVED from (P2-C, ADR-0017).

    Records the raw inputs to the transparent bounded rule
    ``f(source_freshness, row_count, template_verified)`` PLUS the per-input bounded
    factors and any caps/floors that fired, so the scalar ``score`` is explainable and
    auditable — earned from observable inputs, never asserted as a constant. Every
    ``*_factor`` is in ``[0, 1]``; ``flags`` names each cap/floor that applied, e.g.
    ``freshness_unknown``, ``tau_inconsistency``, ``stale``, ``no_rows``,
    ``unverified_template``. Calibration stays ``rule_based``: these are deterministic
    rule inputs, not a learned or statistical model. The recorded ``source_age_seconds``,
    ``freshness_tau_seconds``, ``row_count`` and ``template_verified`` are sufficient to
    RECOMPUTE ``score`` via the same rule (the eval bypass-check does exactly that).
    """

    row_count: int
    template_verified: bool
    freshness_known: bool
    freshness_within_tau: bool
    source_age_seconds: float | None = None
    freshness_tau_seconds: float | None = None
    freshness_factor: float = 1.0
    row_count_factor: float = 1.0
    template_factor: float = 1.0
    flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ConfidenceScore:
    """Typed confidence score with calibration label."""

    score: float
    calibration: str = "rule_based"
    # P2-C (ADR-0017): the observable inputs the score was DERIVED from, so the number is
    # explainable/auditable rather than an asserted constant. ``None`` only for legacy or
    # hand-built scores that predate derivation.
    inputs: ConfidenceInputs | None = None


@dataclass(frozen=True)
class EvalBinding:
    """Link between an evidence chain and an eval case/dimension."""

    eval_case_id: str
    dimension: str
    status: str = "pass"  # pass / fail / skip


@dataclass(frozen=True)
class EvidenceSemanticObjectRef:
    """A reference to a SemanticObject in the evidence chain (lineage audit)."""

    object_id: str
    object_type: str
    name: str


@dataclass(frozen=True)
class EvidenceObjectLinkRef:
    """A reference to an ObjectLink in the evidence chain (lineage path audit)."""

    link_id: str
    link_type_id: str
    source_object_id: str
    target_object_id: str


@dataclass(frozen=True)
class EvidenceChain:
    evidence_chain_id: str
    intent: BusinessIntent
    metric_contract: MetricContract
    query_plan: QueryPlan
    sql_safety: SQLSafetyResult
    query_result: QueryResult
    conclusion: str
    confidence: float
    limitations: tuple[str, ...]
    trace_id: str
    # Typed evidence fields (goal: structured audit object, not just text)
    metric_contract_refs: tuple[MetricContractRef, ...] = field(default_factory=tuple)
    provider_contract_refs: tuple[ProviderContractRef, ...] = field(default_factory=tuple)
    query_result_summary: QueryResultSummary | None = None
    claims: tuple[Claim, ...] = field(default_factory=tuple)
    limitation_objects: tuple[Limitation, ...] = field(default_factory=tuple)
    confidence_score: ConfidenceScore | None = None
    eval_bindings: tuple[EvalBinding, ...] = field(default_factory=tuple)
    semantic_object_refs: tuple[EvidenceSemanticObjectRef, ...] = field(default_factory=tuple)
    semantic_lineage: tuple[EvidenceObjectLinkRef, ...] = field(default_factory=tuple)
    # P2-B (ADR-0016): the action's own governed history, attached AS EVIDENCE about the action
    # (not decorative free text), so the consequence preview is auditable alongside the rest of the
    # chain. Optional/None when no history port is wired; the derivation never blocks the evidence path.
    consequence_preview: ConsequencePreview | None = None

    def is_complete(self) -> bool:
        """Legacy completeness check: required fields for the Trusted Loop."""
        return bool(
            self.evidence_chain_id
            and self.intent.question
            and self.metric_contract.definition
            and self.query_plan.sql
            and self.sql_safety.allowed
            and self.trace_id
        )

    def is_typed_complete(self) -> bool:
        """Typed-evidence completeness check: new structured fields are populated."""
        return bool(
            self.is_complete()
            and self.metric_contract_refs
            and self.provider_contract_refs
            and self.query_result_summary is not None
            and self.claims
            and self.confidence_score is not None
            and self.eval_bindings
        )


@dataclass(frozen=True)
class ConsequencePreview:
    """An evidence-bound SYMBOLIC preview of an action's OWN governed history (P2-B, ADR-0016).

    Before an approver decides, this surfaces the action's own prior track record derived live
    from the durable ``action_records`` ledger — "this ``action_type`` has ``prior_executions``
    prior executions, ``resolved_intended`` of which resolved to the intended (clean) execution
    outcome". It STRENGTHENS the ADR-0008 outcome moat (governed action closed to measured outcome
    + compounding per-tenant history) by turning the approval surface from "decide blind" into
    "decide with the action's track record".

    It is an HONEST COUNT the human reads, NOT a prediction, learned model, or probability — the
    disposer/human still decides; predictive consequence modelling is a future, separately-gated
    capability. ``available`` is False when there is no prior history OR the ledger could not be
    read: a novel action reports ``available=False`` with zero counts so the surface can render
    "no prior history" HONESTLY, never a fabricated ``0/0 resolved`` dressed as real data. Counts
    are derived live from the ledger; there is deliberately no parallel cached counter to drift.
    """

    action_type: str
    prior_executions: int = 0
    resolved_intended: int = 0
    resolved_other: int = 0
    last_outcomes: tuple[str, ...] = field(default_factory=tuple)
    available: bool = False


@dataclass(frozen=True)
class ActionAlternative:
    """A human-facing candidate action in the approval choice set (ADR-0014).

    Unlike the seam-facing ``candidate_actions`` labels (ADR-0009), an alternative
    carries the deliberation record the approver needs to exercise informed choice:
    what else was considered, why it is or is not the recommendation, and its risk.
    """

    action: str
    rationale: str
    risk_level: RiskLevel | None = None
    recommended: bool = False  # exactly one True when alternatives non-empty


@dataclass(frozen=True)
class ActionProposal:
    proposal_id: str
    evidence_chain_id: str
    target_object: str
    recommended_action: str
    reason: str
    risk_level: RiskLevel
    expected_impact: str
    approval_required: bool
    approver_role: str | None
    connector_name: str = "manual_review"
    action_type: str = "propose"
    action_parameters: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    knowledge_context_refs: tuple[str, ...] = field(default_factory=tuple)
    # S5 (RR-0048 Option 2): enumerated candidate interventions for governed causal SELECTION. When
    # non-empty, the governed-decision seam is consulted over ALL of them and returns the causally-chosen
    # one; empty (the default) preserves single-recommendation behavior. These are labels the interventional
    # verifier scores; enumeration source is the proposer/domain, not open-world self-generation.
    candidate_actions: tuple[str, ...] = field(default_factory=tuple)
    # Causal discovery integration: the discovered DAG and its confidence, attached by
    # the TrustedLoop when a causal_discovery_client is configured (RR-0032 seam).
    causal_dag: list[tuple[int, int]] = field(default_factory=list)
    causal_confidence: float = 0.0
    execution_mode: str = "proposal_only"  # ADR-0012: proposal_only | policy_pre_approved
    # ADR-0014 (anti-rubber-stamp): the human-facing deliberation record. When approval is
    # required, the runtime proposal step enforces that the proposal carries either >=2
    # alternatives (exactly one recommended, bound to recommended_action, covering every
    # candidate_actions label) or an explicit non-empty single_option_rationale.
    alternatives: tuple[ActionAlternative, ...] = field(default_factory=tuple)
    single_option_rationale: str | None = None  # explicit "why only one option"
    # P2-B (ADR-0016): the action's own governed history from the durable action_records ledger,
    # attached at proposal-build time so the approval surface can render the track record before a
    # decision. None when no history port is wired (feature off) — never a fabricated zero.
    consequence_preview: ConsequencePreview | None = None


@dataclass(frozen=True)
class TraceEvent:
    trace_id: str
    step: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RunTrace:
    """The persisted, queryable trace of one run (AR-20260611 observability v1).

    Persisted on BOTH exits of run(): ``status="ok"`` for answers and
    ``status="blocked"`` for refusals (whose last event is the ``blocked`` step),
    so refusals are as auditable as answers.
    """

    trace_id: str
    status: str  # "ok" | "blocked"
    events: tuple[TraceEvent, ...]
    telemetry_events: tuple[TelemetryEvent, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TrustedLoopResult:
    intent: BusinessIntent
    query_plan: QueryPlan
    evidence_chain: EvidenceChain
    action_proposal: ActionProposal
    trace_events: tuple[TraceEvent, ...]
    telemetry_events: tuple[TelemetryEvent, ...] = field(default_factory=tuple)
    provider_contract: ProviderContract | None = None
    data_requirement: DataRequirement | None = None
    lineage_snapshot: LineageSnapshot | None = None
    data_product_candidate: DataProductCandidate | None = None
    operation_contract: OperationContract | None = None
    operation_trace: OperationTrace | None = None
    state_snapshot: StateSnapshot | None = None
    action_result: dict[str, Any] | None = None
    approval_record: Any | None = None
    feedback_event: FeedbackEvent | None = None
    knowledge_asset_candidate: KnowledgeAsset | None = None
    # Prior organizational knowledge recalled for this question (read-side of the
    # learning loop, AR-20260611). Advisory context: never alters the data/evidence path.
    related_knowledge: tuple[RetrievalResult, ...] = field(default_factory=tuple)


class BlockCode(StrEnum):
    """Machine-readable code for an expected business block in the Trusted Loop."""

    UNKNOWN_METRIC = "unknown_metric"
    NO_PROVIDER = "no_provider"
    NO_TEMPLATE = "no_template"
    SQL_SAFETY = "sql_safety"
    # P5.2 (ADR-0001): the operator has paused the system via the corrigibility
    # shell; the loop refuses to answer until resumed. Operator sovereignty, not
    # a data/intent problem.
    PAUSED = "paused"
    # RR-0032: the external governed-decision seam DENIED the action (the seam can only tighten,
    # never loosen). Distinct from PAUSED (operator) and SQL_SAFETY (data path).
    GOVERNANCE_DENIED = "governance_denied"
    # ADR-0014: an approval-required proposal failed the human choice-set contract
    # (no >=2 consistent alternatives AND no explicit single-option rationale).
    # Choice-set collapse is a contract violation, not a silent default.
    CHOICE_SET_VIOLATION = "choice_set_violation"


@dataclass(frozen=True)
class TrustedLoopBlock:
    """A structured, expected block: the loop refused to produce an answer.

    Distinct from a programming/wiring error. ``code`` is machine-readable,
    ``stage`` names where in the loop it occurred, and ``details`` carries the
    human-facing reasons (e.g. SQL-safety violation messages).
    """

    code: BlockCode
    message: str
    stage: str
    details: tuple[str, ...] = field(default_factory=tuple)
    # The persisted trace of this refusal (AR-20260611): populated by run(), so
    # 422 responses and CLI errors reference an auditable RunTrace.
    trace_id: str | None = None


@dataclass(frozen=True)
class TrustedLoopOutcome:
    """Unified result of a Trusted Loop evaluation: either ok or blocked."""

    status: str  # "ok" | "blocked"
    result: TrustedLoopResult | None = None
    block: TrustedLoopBlock | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def blocked(self) -> bool:
        return self.status == "blocked"


class ApprovalDecision(StrEnum):
    """Typed outcome of a human approval decision (P2-A, ADR-0015).

    The distinction between ``APPROVED_RECOMMENDED`` and ``APPROVED_REVISED`` is
    the anti-rubber-stamp signal: it is DERIVED by the runtime from the action the
    approver actually selected versus the proposal's ``recommended_action`` — it is
    never self-reported by the approver. ``APPROVED_REVISED`` (a ``revise``) means
    the approver picked a different, in-choice-set alternative, i.e. they engaged
    with the ADR-0014 choice set rather than rubber-stamping the pre-baked option.
    """

    APPROVED_RECOMMENDED = "approved_recommended"
    APPROVED_REVISED = "approved_revised"
    REJECTED = "rejected"
    ESCALATED = "escalated"


@dataclass(frozen=True)
class ApprovalDecisionCounts:
    """Per-decision counts backing :class:`ApprovalAnalytics` (P2-A)."""

    approved_recommended: int = 0
    approved_revised: int = 0
    rejected: int = 0
    escalated: int = 0


@dataclass(frozen=True)
class ApprovalAnalytics:
    """Derived rubber-stamp analytics over a tenant's approval decisions (P2-A, ADR-0015).

    This is a READ projection: it is computed by scanning tenant-scoped
    ``ApprovalRecord`` decisions, never by maintaining a parallel mutable counter.
    ``modify_rate`` and ``selection_concentration`` make the ADR-0014 choice-set
    mechanism falsifiable in production (RR-0050 §7):

    - ``modify_rate = approved_revised / (approved_recommended + approved_revised)``
      — the share of approvals where the operator modified the recommendation.
    - ``selection_concentration = approved_recommended / (approved_recommended +
      approved_revised)`` — the share that took the pre-baked option unchanged;
      ``1.0`` is pure rubber-stamping.

    Both are ``0.0`` when there are no approvals in scope (no division by zero).
    """

    tenant_id: str
    window: str
    counts: ApprovalDecisionCounts
    total: int
    modify_rate: float
    selection_concentration: float
    risk: str | None = None
