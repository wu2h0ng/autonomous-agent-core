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


class SelfDevelopmentVerifierBinding(ContractModel):
    """Admission-sealed immutable Product test oracle."""

    path: NonEmptyStr
    base_blob_sha256: Sha256Digest

    @field_validator("path", mode="after")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        if re.fullmatch(r"tests/product/test_[A-Za-z0-9_]+\.py", value) is None:
            raise ValueError(
                "verifier binding path must be an exact tests/product/test_*.py path"
            )
        return value


class SelfDevelopmentWorkSpec(ContractModel):
    """Persisted execution envelope for one isolated Agent OS change."""

    repository_head: NonEmptyStr
    isolated_branch: NonEmptyStr
    target_path: NonEmptyStr
    edit_mode: Literal["complete_replacement", "agent_loop_precise"] = Field(
        default="complete_replacement",
        exclude_if=lambda value: value == "complete_replacement",
    )
    additional_target_paths: tuple[NonEmptyStr, ...] = Field(
        default=(),
        max_length=7,
        exclude_if=lambda value: not value,
    )
    verifier_bindings: tuple[SelfDevelopmentVerifierBinding, ...] = Field(
        default=(),
        max_length=8,
        exclude_if=lambda value: not value,
    )
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
        return cls._safe_product_path(value)

    @field_validator("additional_target_paths", mode="after")
    @classmethod
    def _validate_additional_target_paths(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        return tuple(cls._safe_product_path(value) for value in values)

    @staticmethod
    def _safe_product_path(value: str) -> str:
        allowed_prefixes = (
            "packages/os_core/src/agent_os_core/",
        )
        path = PurePosixPath(value)
        reserved_paths = {
            "apps/api_server/app.py",
            "packages/contracts/src/agent_os_contracts/authority.py",
            "packages/contracts/src/agent_os_contracts/evaluator.py",
            "packages/contracts/src/agent_os_contracts/outcome_portfolio.py",
            "packages/contracts/src/agent_os_contracts/responsibility.py",
            "packages/os_core/src/agent_os_core/action_pipeline.py",
            "packages/os_core/src/agent_os_core/agent_loop.py",
            "packages/os_core/src/agent_os_core/capability.py",
            "packages/os_core/src/agent_os_core/execution.py",
            "packages/os_core/src/agent_os_core/governance.py",
            "packages/os_core/src/agent_os_core/evaluator_authority.py",
            "packages/os_core/src/agent_os_core/event_store.py",
            "packages/os_core/src/agent_os_core/mandate_outcome_portfolio.py",
            "packages/os_core/src/agent_os_core/mandate_responsibility.py",
            "packages/os_core/src/agent_os_core/materialization_evaluation.py",
            "packages/os_core/src/agent_os_core/materialization_evaluation_persistence.py",
            "packages/os_core/src/agent_os_core/materialization_promotion.py",
            "packages/os_core/src/agent_os_core/materialization_promotion_persistence.py",
            "packages/os_core/src/agent_os_core/materialization_promotion_policy.py",
            "packages/os_core/src/agent_os_core/responsibility_controller.py",
            "packages/os_core/src/agent_os_core/responsibility_loop.py",
            "packages/os_core/src/agent_os_core/responsibility_surface.py",
            "packages/os_core/src/agent_os_core/self_development_organ.py",
            "packages/os_core/src/agent_os_core/srl_event_authority.py",
            "packages/os_core/src/agent_os_core/srl_event_store.py",
            "packages/os_core/src/agent_os_core/task_aggregate.py",
            "packages/os_core/src/agent_os_core/task_configuration.py",
            "packages/os_core/src/agent_os_core/task_service.py",
        }
        reserved_name_tokens = (
            "approval",
            "authority",
            "capability",
            "correction",
            "evaluation",
            "evaluator",
            "event_store",
            "governance",
            "mandate",
            "policy",
            "promotion",
            "responsibility",
            "security",
        )
        reserved_stems = {
            "action_pipeline",
            "agent_cli",
            "agent_loop",
            "execution",
            "self_development_organ",
            "task_aggregate",
            "task_configuration",
            "task_service",
        }
        stem = path.stem.lower()
        if (
            value.startswith("/")
            or "\\" in value
            or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts)
            or not path.as_posix().startswith(allowed_prefixes)
            or path.as_posix() in reserved_paths
            or stem in reserved_stems
            or any(token in stem for token in reserved_name_tokens)
        ):
            raise ValueError(
                "target_path must be a safe Agent OS product path outside authority core"
            )
        return path.as_posix()

    @model_validator(mode="after")
    def _validate_write_set(self) -> SelfDevelopmentWorkSpec:
        paths = self.allowed_write_paths
        if len(set(paths)) != len(paths):
            raise ValueError("SELFDEV write paths must be unique")
        if self.additional_target_paths and self.edit_mode != "agent_loop_precise":
            raise ValueError(
                "multiple SELFDEV targets require agent_loop_precise edit mode"
            )
        return self

    @property
    def allowed_write_paths(self) -> tuple[str, ...]:
        return (self.target_path, *self.additional_target_paths)

    @field_validator("verifier_command", mode="after")
    @classmethod
    def _validate_verifier_command(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if normalized not in {"pytest", "python -m pytest", "python3 -m pytest"}:
            raise ValueError("verifier_command must be an allowlisted verifier")
        return normalized


class SelfDevelopmentAdmissionCommand(ContractModel):
    """Operator-authored request for one exact, bounded SELFDEV responsibility."""

    admission_id: NonEmptyStr
    statement: NonEmptyStr
    deliverables: tuple[NonEmptyStr, ...] = Field(min_length=1)
    acceptance_criteria: tuple[NonEmptyStr, ...] = Field(min_length=1)
    verifier_paths: tuple[NonEmptyStr, ...] = Field(min_length=1, max_length=8)
    selfdev_spec: SelfDevelopmentWorkSpec

    @field_validator("verifier_paths", mode="after")
    @classmethod
    def _validate_verifier_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("verifier_paths must be unique")
        for value in values:
            path = PurePosixPath(value)
            if (
                re.fullmatch(r"tests/product/test_[A-Za-z0-9_]+\.py", value)
                is None
                or path.as_posix() != value
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
            ):
                raise ValueError(
                    "verifier_paths must be exact canonical tests/product/test_*.py paths"
                )
        return values

    @model_validator(mode="after")
    def _require_precise_route(self) -> SelfDevelopmentAdmissionCommand:
        if self.selfdev_spec.edit_mode != "agent_loop_precise":
            raise ValueError(
                "SELFDEV admission requires edit_mode=agent_loop_precise"
            )
        if self.selfdev_spec.verifier_bindings:
            raise ValueError(
                "SELFDEV verifier bindings are server-computed; callers provide verifier_paths only"
            )
        if self.selfdev_spec.verifier_command != "pytest":
            raise ValueError("new SELFDEV admission requires canonical pytest")
        return self


class SelfDevelopmentAdmissionReceipt(ContractModel):
    """Canonical responsibility graph receipt; replay is response-local truth."""

    admission_id: NonEmptyStr
    admission_digest: Sha256Digest
    command_digest: Sha256Digest
    semantic_key: Sha256Digest
    mandate_id: NonEmptyStr
    portfolio_id: NonEmptyStr
    task_id: NonEmptyStr
    task_created_event_digest: Sha256Digest
    commitment_id: NonEmptyStr
    commitment_digest: Sha256Digest
    expected_outcome_id: NonEmptyStr
    expected_outcome_digest: Sha256Digest
    workflow_id: NonEmptyStr
    workflow_digest: Sha256Digest
    link_id: NonEmptyStr
    link_digest: Sha256Digest
    persistent_commitment_id: NonEmptyStr
    persistent_commitment_digest: Sha256Digest
    snapshot_id: NonEmptyStr
    snapshot_digest: Sha256Digest
    run_id: NonEmptyStr
    work_spec_digest: Sha256Digest
    replayed: bool
    provider_executed: Literal[False] = False
    effect_authorized: Literal[False] = False
    approval_created: Literal[False] = False
    outcome_created: Literal[False] = False
    help_created: Literal[False] = False
    hcw_measured: Literal[False] = False
    claim_ceiling: Literal[
        "SELFDEV_RESPONSIBILITY_ADMISSION / NOT_EXECUTED / NOT_RELEASED"
    ] = "SELFDEV_RESPONSIBILITY_ADMISSION / NOT_EXECUTED / NOT_RELEASED"


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
