from __future__ import annotations

from enum import Enum
from pathlib import PurePosixPath
import re
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


class ResponsibilityWorkRoute(str, Enum):
    ORDINARY_TASK = "ORDINARY_TASK"
    SELFDEV = "SELFDEV"


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


class SelfDevelopmentWorkSpec(ContractModel):
    """Persisted execution envelope for one isolated Agent OS change."""

    repository_head: NonEmptyStr
    isolated_branch: NonEmptyStr
    target_path: NonEmptyStr
    verifier_command: NonEmptyStr
    rollback_strategy: Literal["compensate_task"] = "compensate_task"

    @field_validator("repository_head", mode="after")
    @classmethod
    def _validate_repository_head(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise ValueError("repository_head must be a 40-character lowercase Git object id")
        return value

    @field_validator("isolated_branch", mode="after")
    @classmethod
    def _validate_isolated_branch(cls, value: str) -> str:
        if (
            value in {"main", "master", "release"}
            or value.startswith("release/")
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", value) is None
            or ".." in value
            or value.endswith(("/", ".lock"))
        ):
            raise ValueError("isolated_branch cannot target main/master/release or an unsafe ref")
        return value

    @field_validator("target_path", mode="after")
    @classmethod
    def _validate_target_path(cls, value: str) -> str:
        allowed_prefixes = (
            "packages/os_core/src/agent_os_core/",
            "packages/contracts/src/agent_os_contracts/",
            "apps/api_server/",
            "apps/cli/",
        )
        path = PurePosixPath(value)
        if (
            value.startswith("/")
            or "\\" in value
            or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts)
            or not path.as_posix().startswith(allowed_prefixes)
        ):
            raise ValueError("target_path must be a safe Agent OS product path")
        return path.as_posix()

    @field_validator("verifier_command", mode="after")
    @classmethod
    def _validate_verifier_command(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if normalized not in {"pytest", "python -m pytest", "python3 -m pytest"}:
            raise ValueError("verifier_command must be an allowlisted verifier")
        return normalized


def _validate_work_route_spec(
    route: ResponsibilityWorkRoute,
    spec: SelfDevelopmentWorkSpec | None,
) -> None:
    if route is ResponsibilityWorkRoute.SELFDEV and spec is None:
        raise ValueError("SELFDEV route requires selfdev_spec")
    if route is not ResponsibilityWorkRoute.SELFDEV and spec is not None:
        raise ValueError("selfdev_spec is only valid for SELFDEV route")


class MandateTaskLinkCommand(ContractModel):
    task_id: NonEmptyStr
    reason: NonEmptyStr | None = None
    work_route: ResponsibilityWorkRoute = Field(
        default=ResponsibilityWorkRoute.ORDINARY_TASK,
        exclude_if=lambda value: value is ResponsibilityWorkRoute.ORDINARY_TASK,
    )
    selfdev_spec: SelfDevelopmentWorkSpec | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def _validate_selfdev_route(self) -> MandateTaskLinkCommand:
        _validate_work_route_spec(self.work_route, self.selfdev_spec)
        return self


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
    work_route: ResponsibilityWorkRoute = Field(
        default=ResponsibilityWorkRoute.ORDINARY_TASK,
        exclude_if=lambda value: value is ResponsibilityWorkRoute.ORDINARY_TASK,
    )
    selfdev_spec: SelfDevelopmentWorkSpec | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
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
