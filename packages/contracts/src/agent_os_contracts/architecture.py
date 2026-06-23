from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class LifecycleState(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
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


@dataclass(frozen=True)
class SemanticObject:
    object_id: str
    name: str
    object_type: str
    description: str
    owner: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    related_metrics: tuple[str, ...] = field(default_factory=tuple)
    state: LifecycleState = LifecycleState.DRAFT


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
class ActionConnectorContract:
    connector_name: str
    display_name: str
    supported_action_types: tuple[str, ...]
    supports_snapshot: bool
    supports_rollback: bool
    compensating_action_description: str | None
    risk_ceiling: str
    owner: str


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
