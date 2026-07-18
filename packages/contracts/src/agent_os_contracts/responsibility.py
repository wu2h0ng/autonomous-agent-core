from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime
from .evidence import Sha256Digest
from .outcome import ExpectedOutcome, ObservedOutcome
from .runtime import RunStatus, TaskStatus, WaitCondition
from .situated import MandateOperationalStatus
from .task import Commitment, Goal


class ResponsibilityItemState(str, Enum):
    UNKNOWN = "UNKNOWN"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    DONE_VERIFIED = "DONE_VERIFIED"
    TRACKED = "TRACKED"


class ResponsibilityAttentionReason(str, Enum):
    MANDATE_AUTHORITY_MISSING = "MANDATE_AUTHORITY_MISSING"
    MANDATE_AUTHORITY_MISMATCH = "MANDATE_AUTHORITY_MISMATCH"
    MANDATE_CORRECTION_DRIFT = "MANDATE_CORRECTION_DRIFT"
    TASK_SOURCE_MISSING = "TASK_SOURCE_MISSING"
    TASK_SOURCE_MALFORMED = "TASK_SOURCE_MALFORMED"
    TASK_IDENTITY_CHANGED = "TASK_IDENTITY_CHANGED"
    UNSUPPORTED_EVALUATOR = "UNSUPPORTED_EVALUATOR"
    OUTCOME_NOT_MET = "OUTCOME_NOT_MET"
    OUTCOME_UNRESOLVED = "OUTCOME_UNRESOLVED"
    OUTCOME_INVALID = "OUTCOME_INVALID"
    TASK_FAILED = "TASK_FAILED"
    TASK_CANCELLED = "TASK_CANCELLED"
    TASK_PAUSED = "TASK_PAUSED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    WAIT_DEADLINE_ARRIVED = "WAIT_DEADLINE_ARRIVED"
    WAIT_CONDITION_MISSING = "WAIT_CONDITION_MISSING"
    WAIT_CONDITION_MALFORMED = "WAIT_CONDITION_MALFORMED"
    COMMITMENT_EXPIRED = "COMMITMENT_EXPIRED"
    TERMINAL_WITHOUT_OUTCOME = "TERMINAL_WITHOUT_OUTCOME"
    SCHEDULE_SOURCE_MALFORMED = "SCHEDULE_SOURCE_MALFORMED"
    UNHANDLED_TASK_RUN_STATE = "UNHANDLED_TASK_RUN_STATE"


class MandateTaskLinkCommand(ContractModel):
    task_id: NonEmptyStr
    reason: NonEmptyStr | None = None


class MandateTaskLink(ContractModel):
    association_id: NonEmptyStr
    link_id: NonEmptyStr
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    mandate_id: NonEmptyStr
    task_id: NonEmptyStr
    task_created_event_digest: Sha256Digest
    workspace_record_digest: Sha256Digest
    operational_mandate_ref_digest: Sha256Digest
    correction_epoch: int = Field(ge=0)
    linked_by: NonEmptyStr
    linked_at: UtcDateTime
    reason: NonEmptyStr | None = None
    prior_record_digest: Sha256Digest | None = None
    command_digest: Sha256Digest
    record_digest: Sha256Digest
    task_activation_authorized: Literal[False] = False
    capability_grant_authorized: Literal[False] = False
    external_effects_authorized: Literal[False] = False

    @field_validator(
        "task_activation_authorized",
        "capability_grant_authorized",
        "external_effects_authorized",
        mode="before",
    )
    @classmethod
    def _require_exact_false(cls, value: Any) -> Literal[False]:
        if value is not False:
            raise ValueError("responsibility link cannot grant execution authority")
        return False


class MandateTaskLinkRevocationCommand(ContractModel):
    expected_link_digest: Sha256Digest
    reason: NonEmptyStr


class MandateTaskLinkRevocation(ContractModel):
    revocation_id: NonEmptyStr
    association_id: NonEmptyStr
    link_id: NonEmptyStr
    link_record_digest: Sha256Digest
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    mandate_id: NonEmptyStr
    task_id: NonEmptyStr
    correction_epoch: int = Field(ge=0)
    revoked_by: NonEmptyStr
    revoked_at: UtcDateTime
    reason: NonEmptyStr
    command_digest: Sha256Digest
    record_digest: Sha256Digest
    task_activation_authorized: Literal[False] = False
    capability_grant_authorized: Literal[False] = False
    external_effects_authorized: Literal[False] = False

    @field_validator(
        "task_activation_authorized",
        "capability_grant_authorized",
        "external_effects_authorized",
        mode="before",
    )
    @classmethod
    def _require_exact_false(cls, value: Any) -> Literal[False]:
        if value is not False:
            raise ValueError("responsibility revocation cannot grant execution authority")
        return False


class ResponsibilityActivePerceptionSummary(ContractModel):
    schedule_digest: Sha256Digest
    schedule_status: NonEmptyStr
    next_observation_at: UtcDateTime | None = None


class ResponsibilityItem(ContractModel):
    link: MandateTaskLink
    goal: Goal | None = None
    commitment: Commitment | None = None
    expected_outcome: ExpectedOutcome | None = None
    current_outcome: ObservedOutcome | None = None
    task_status: TaskStatus | None
    run_status: RunStatus | None
    wait_condition: WaitCondition | None = None
    state: ResponsibilityItemState
    attention_reasons: tuple[ResponsibilityAttentionReason, ...] = ()
    task_event_position: int | None = Field(default=None, ge=1)
    task_event_head_digest: Sha256Digest | None = None
    historical_outcome_digest: Sha256Digest | None = None
    outcome_validation_status: NonEmptyStr | None = None
    outcome_validation_reason: NonEmptyStr | None = None
    completed_at: UtcDateTime | None = None

    @field_validator("attention_reasons", mode="after")
    @classmethod
    def _normalize_reasons(
        cls, values: tuple[ResponsibilityAttentionReason, ...]
    ) -> tuple[ResponsibilityAttentionReason, ...]:
        return tuple(sorted(set(values), key=lambda item: item.value))

    @model_validator(mode="after")
    def _validate_reason_semantics(self) -> ResponsibilityItem:
        if self.state in {
            ResponsibilityItemState.UNKNOWN,
            ResponsibilityItemState.NEEDS_ATTENTION,
        } and not self.attention_reasons:
            raise ValueError("attention state requires at least one attention reason")
        if self.state in {
            ResponsibilityItemState.TRACKED,
            ResponsibilityItemState.DONE_VERIFIED,
        } and self.attention_reasons:
            raise ValueError("non-attention state cannot contain attention reasons")
        return self


class MandateResponsibilityViewStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL_UNKNOWN = "PARTIAL_UNKNOWN"
    REVOKED = "REVOKED"


_ITEM_STATE_ORDER = {
    ResponsibilityItemState.UNKNOWN: 0,
    ResponsibilityItemState.NEEDS_ATTENTION: 1,
    ResponsibilityItemState.DONE_VERIFIED: 2,
    ResponsibilityItemState.TRACKED: 3,
}


class MandateResponsibilityView(ContractModel):
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    mandate_id: NonEmptyStr
    mandate_status: MandateOperationalStatus
    desired_outcomes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    status: MandateResponsibilityViewStatus
    items: tuple[ResponsibilityItem, ...] = ()
    active_perception: ResponsibilityActivePerceptionSummary | None = None
    global_gaps: tuple[ResponsibilityAttentionReason, ...] = ()
    workspace_record_digest: Sha256Digest
    operational_mandate_ref_digest: Sha256Digest
    schedule_source_digest: Sha256Digest | None = None
    computed_at: UtcDateTime
    view_digest: Sha256Digest

    @field_validator("desired_outcomes", mode="after")
    @classmethod
    def _normalize_desired_outcomes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @field_validator("items", mode="after")
    @classmethod
    def _normalize_items(
        cls, values: tuple[ResponsibilityItem, ...]
    ) -> tuple[ResponsibilityItem, ...]:
        by_link_id: dict[str, ResponsibilityItem] = {}
        for item in values:
            existing = by_link_id.get(item.link.link_id)
            if existing is not None and existing != item:
                raise ValueError("responsibility item link ids must be unique")
            by_link_id[item.link.link_id] = item
        return tuple(
            sorted(
                by_link_id.values(),
                key=lambda item: (
                    _ITEM_STATE_ORDER[item.state],
                    item.commitment.expires_at if item.commitment else item.link.linked_at,
                    item.link.linked_at,
                    item.link.link_id,
                ),
            )
        )

    @field_validator("global_gaps", mode="after")
    @classmethod
    def _normalize_global_gaps(
        cls, values: tuple[ResponsibilityAttentionReason, ...]
    ) -> tuple[ResponsibilityAttentionReason, ...]:
        return tuple(sorted(set(values), key=lambda item: item.value))
