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


@dataclass(frozen=True)
class OperationTrace:
    trace_id: str
    proposal_id: str
    operation_id: str | None
    state: OperationState
    evidence_chain_id: str
    events: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FeedbackEvent:
    feedback_id: str
    trace_id: str
    outcome: str
    metrics: dict[str, Any] = field(default_factory=dict)
    reviewer: str | None = None


@dataclass(frozen=True)
class KnowledgeAsset:
    asset_id: str
    title: str
    asset_type: str
    source_trace_id: str | None
    owner: str
    state: LifecycleState = LifecycleState.DRAFT


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
