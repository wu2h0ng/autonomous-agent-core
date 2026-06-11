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

    def is_complete(self) -> bool:
        return bool(
            self.evidence_chain_id
            and self.intent.question
            and self.metric_contract.definition
            and self.query_plan.sql
            and self.sql_safety.allowed
            and self.trace_id
        )


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


@dataclass(frozen=True)
class TraceEvent:
    trace_id: str
    step: str
    payload: dict[str, Any]


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
