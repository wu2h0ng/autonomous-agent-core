from __future__ import annotations

import json
from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .common import (
    ContractModel,
    NonEmptyStr,
    UtcDateTime,
    canonical_json,
    content_digest,
)
from .approval_choice import ApprovalChoiceSet
from .evidence import Sha256Digest
from .resource import ResourceBudget, RiskTier


NO_APPROVAL_ID = "approval:none"
NO_ERROR_CODE = "error:none"
NO_DETAIL_REF = "detail:none"


class PrincipalRole(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    TENANT_ADMIN = "TENANT_ADMIN"
    WORKER = "WORKER"
    MODEL = "MODEL"
    PLUGIN = "PLUGIN"


class PolicyVerdict(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


class ApprovalDisposition(str, Enum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    REJECT = "REJECT"


class CorrectionScope(str, Enum):
    TASK = "TASK"
    RUN = "RUN"
    CAPABILITY = "CAPABILITY"


class ReceiptStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"
    COMPENSATED = "COMPENSATED"


class PrincipalIdentity(ContractModel):
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    role: PrincipalRole
    authenticated_at: UtcDateTime


class CandidateExclusion(ContractModel):
    candidate_class: NonEmptyStr
    reason: NonEmptyStr


class CandidateGenerationEnvelope(ContractModel):
    envelope_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    generator_id: NonEmptyStr
    generator_version: NonEmptyStr
    allowed_capability_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    resource_budget: ResourceBudget
    candidate_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    exclusions: tuple[CandidateExclusion, ...] = ()
    coverage_evidence_refs: tuple[NonEmptyStr, ...] = ()
    has_abstain: bool
    has_ask: bool
    has_no_action: bool
    created_at: UtcDateTime

    @field_validator(
        "allowed_capability_ids",
        "candidate_ids",
        "coverage_evidence_refs",
        mode="after",
    )
    @classmethod
    def _normalize_set_like_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class CorrectionEpochVector(ContractModel):
    task_epoch: int = Field(ge=0)
    run_epoch: int = Field(ge=0)
    capability_epoch: int = Field(ge=0)


class CorrectionState(ContractModel):
    correction_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    scope: CorrectionScope
    scope_id: NonEmptyStr
    epoch: int = Field(ge=0)
    halted: bool
    reason: NonEmptyStr
    written_by: NonEmptyStr
    written_at: UtcDateTime


class CorrectionSnapshot(ContractModel):
    task: CorrectionState
    run: CorrectionState
    capability: CorrectionState

    @model_validator(mode="after")
    def _validate_scopes(self) -> CorrectionSnapshot:
        expected = (
            (self.task, CorrectionScope.TASK, "task correction"),
            (self.run, CorrectionScope.RUN, "run correction"),
            (self.capability, CorrectionScope.CAPABILITY, "capability correction"),
        )
        for state, scope, label in expected:
            if state.scope is not scope:
                raise ValueError(f"{label} must use {scope.value} scope")
        scoped = (self.run, self.capability)
        if any(
            state.tenant_id != self.task.tenant_id
            or state.workspace_id != self.task.workspace_id
            for state in scoped
        ):
            raise ValueError("correction snapshot scope mismatch")
        return self

    def epoch_vector(self) -> CorrectionEpochVector:
        return CorrectionEpochVector(
            task_epoch=self.task.epoch,
            run_epoch=self.run.epoch,
            capability_epoch=self.capability.epoch,
        )

    def halted_scopes(self) -> tuple[CorrectionScope, ...]:
        return tuple(
            state.scope
            for state in (self.task, self.run, self.capability)
            if state.halted
        )


class ActionContract(ContractModel):
    action_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    node_id: NonEmptyStr
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    capability_id: NonEmptyStr
    capability_version: NonEmptyStr
    arguments_json: NonEmptyStr
    risk_tier: RiskTier
    idempotency_key: NonEmptyStr
    estimated_budget: ResourceBudget
    policy_version: NonEmptyStr
    observed_correction_epochs: CorrectionEpochVector
    expected_outcome_id: NonEmptyStr
    candidate_envelope_id: NonEmptyStr
    approval_requirement: Literal["policy", "external_exact"] = Field(
        default="policy",
        exclude_if=lambda value: value == "policy",
    )
    created_at: UtcDateTime

    @field_validator("arguments_json", mode="after")
    @classmethod
    def _canonicalize_arguments(cls, value: str) -> str:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("arguments_json must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("arguments_json must encode an object")
        return canonical_json(payload)

    def action_digest(self) -> str:
        return content_digest(self)


class ApprovalDecision(ContractModel):
    approval_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    action_digest: Sha256Digest
    actor_id: NonEmptyStr
    actor_role: PrincipalRole
    disposition: ApprovalDisposition
    reason: NonEmptyStr
    decided_at: UtcDateTime
    expires_at: UtcDateTime
    # ADR-0014: optional human-facing choice set + the action the approver actually selected.
    # Backward compatible (defaults None); enforced fail-closed for REVISE below.
    choice_set: ApprovalChoiceSet | None = None
    selected_action: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _validate_authority(self) -> ApprovalDecision:
        if self.actor_role not in {PrincipalRole.PRINCIPAL, PrincipalRole.TENANT_ADMIN}:
            raise ValueError("approval must be authored by a principal or tenant admin")
        if self.expires_at <= self.decided_at:
            raise ValueError("expires_at must be after decided_at")
        return self

    @model_validator(mode="after")
    def _validate_choice_set_discipline(self) -> ApprovalDecision:
        labels = self.choice_set.action_labels() if self.choice_set is not None else ()
        if self.disposition is ApprovalDisposition.REVISE:
            if self.choice_set is None:
                raise ValueError("a REVISE decision requires the surfaced approval choice set")
            if self.selected_action is None:
                raise ValueError("a REVISE decision must name the selected surfaced action")
            if self.selected_action not in labels:
                raise ValueError(
                    "a REVISE decision must select an action within the surfaced choice set"
                )
        elif self.selected_action is not None:
            if self.choice_set is None or self.selected_action not in labels:
                raise ValueError(
                    "a selected_action requires a choice set that surfaces it"
                )
        return self


class PolicyDecision(ContractModel):
    decision_id: NonEmptyStr
    action_id: NonEmptyStr
    action_digest: Sha256Digest
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    verdict: PolicyVerdict
    policy_version: NonEmptyStr
    reason_codes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    correction_epochs: CorrectionEpochVector
    approval_id: NonEmptyStr
    evaluated_at: UtcDateTime


class ActionPermit(ContractModel):
    permit_id: NonEmptyStr
    action_id: NonEmptyStr
    action_digest: Sha256Digest
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    policy_decision_id: NonEmptyStr
    grant_id: NonEmptyStr
    correction_epochs: CorrectionEpochVector
    lease_fence: int = Field(ge=0)
    issued_at: UtcDateTime
    expires_at: UtcDateTime

    @model_validator(mode="after")
    def _validate_expiry(self) -> ActionPermit:
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        return self

    def matches(self, action: ActionContract) -> bool:
        return (
            self.action_id == action.action_id
            and self.action_digest == action.action_digest()
            and self.principal_id == action.principal_id
            and self.tenant_id == action.tenant_id
            and self.workspace_id == action.workspace_id
            and self.correction_epochs == action.observed_correction_epochs
        )


class ActionReceipt(ContractModel):
    receipt_id: NonEmptyStr
    action_id: NonEmptyStr
    action_digest: Sha256Digest
    permit_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    connector_id: NonEmptyStr
    status: ReceiptStatus
    idempotency_key: NonEmptyStr
    attempt: int = Field(ge=1)
    output_artifact_ids: tuple[NonEmptyStr, ...] = ()
    error_code: NonEmptyStr = NO_ERROR_CODE
    detail_ref: NonEmptyStr = NO_DETAIL_REF
    occurred_at: UtcDateTime
