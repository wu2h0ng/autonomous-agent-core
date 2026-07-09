from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .architecture import (
    DataProductCandidate,
    DataRequirement,
    FeedbackEvent,
    KnowledgeAsset,
    LineageSnapshot,
    OperationContract,
    OperationTrace,
    ProviderContract,
    RetrievalResult,
    StateSnapshot,
)
from .observability import TelemetryEvent


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
class ConfidenceScore:
    """Typed confidence score with calibration label."""

    score: float
    calibration: str = "rule_based"


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
