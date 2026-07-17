from __future__ import annotations

import math
from enum import Enum

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime
from .evidence import Sha256Digest


class BindingStatus(str, Enum):
    BOUND = "BOUND"
    MISSING = "MISSING"


class CreditMethod(str, Enum):
    ASSOCIATIONAL = "ASSOCIATIONAL"
    COUNTERFACTUAL = "COUNTERFACTUAL"
    ABLATION = "ABLATION"


class CreditUncertaintyKind(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNIDENTIFIABLE = "UNIDENTIFIABLE"


class WorkingSetRef(ContractModel):
    status: BindingStatus
    working_set_id: NonEmptyStr | None = None
    digest: Sha256Digest | None = None
    gap_reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _validate_binding(self) -> WorkingSetRef:
        bound = self.status is BindingStatus.BOUND
        if bound and (self.working_set_id is None or self.digest is None):
            raise ValueError("bound working set requires id and digest")
        if bound and self.gap_reason is not None:
            raise ValueError("bound working set cannot carry a gap reason")
        if not bound and (
            self.working_set_id is not None
            or self.digest is not None
            or self.gap_reason is None
        ):
            raise ValueError("missing working set requires only a gap reason")
        return self


class ModelInvocationRef(ContractModel):
    source_event_id: NonEmptyStr
    provider_profile_id: NonEmptyStr | None = None
    provider_profile_digest: Sha256Digest | None = None
    provider_id: NonEmptyStr | None = None
    model_id: NonEmptyStr | None = None
    model_revision_digest: Sha256Digest | None = None
    request_digest: Sha256Digest | None = None
    response_digest: Sha256Digest
    invocation_binding_digest: Sha256Digest | None = None
    working_set_ref: WorkingSetRef
    missing_fields: tuple[NonEmptyStr, ...] = ()

    @field_validator("missing_fields", mode="after")
    @classmethod
    def _normalize_missing_fields(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class CapabilityInvocationRef(ContractModel):
    source_event_id: NonEmptyStr
    capability_id: NonEmptyStr | None = None
    capability_version: NonEmptyStr | None = None
    capability_spec_digest: Sha256Digest | None = None
    action_id: NonEmptyStr | None = None
    action_digest: Sha256Digest | None = None
    receipt_id: NonEmptyStr | None = None
    receipt_digest: Sha256Digest | None = None
    policy_version: NonEmptyStr | None = None
    policy_digest: Sha256Digest | None = None
    missing_fields: tuple[NonEmptyStr, ...] = ()

    @field_validator("missing_fields", mode="after")
    @classmethod
    def _normalize_missing_fields(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class OutcomeLink(ContractModel):
    outcome_id: NonEmptyStr
    source_event_id: NonEmptyStr
    status: NonEmptyStr
    linked_step_ids: tuple[NonEmptyStr, ...]
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    delayed: bool = True


class CorrectionLink(ContractModel):
    correction_id: NonEmptyStr
    source_event_id: NonEmptyStr
    epoch: int = Field(ge=0)
    linked_step_ids: tuple[NonEmptyStr, ...]


class TrajectoryStep(ContractModel):
    step_id: NonEmptyStr
    sequence: int = Field(ge=1)
    source_event_id: NonEmptyStr
    event_type: NonEmptyStr
    event_digest: Sha256Digest
    occurred_at: UtcDateTime
    model_invocation: ModelInvocationRef | None = None
    capability_invocation: CapabilityInvocationRef | None = None


class EpisodeManifest(ContractModel):
    episode_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    source_stream_last_sequence: int = Field(ge=1)
    workflow_digest: Sha256Digest | None = None
    workflow_status: BindingStatus
    policy_version: NonEmptyStr | None = None
    policy_digest: Sha256Digest | None = None
    policy_status: BindingStatus
    working_set_ref: WorkingSetRef
    correction_epoch: int | None = Field(default=None, ge=0)
    correction_epoch_status: BindingStatus
    missing_bindings: tuple[NonEmptyStr, ...] = ()

    @field_validator("missing_bindings", mode="after")
    @classmethod
    def _normalize_missing_bindings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _validate_statuses(self) -> EpisodeManifest:
        pairs = (
            (self.workflow_status, self.workflow_digest, "workflow"),
            (self.policy_status, self.policy_digest, "policy"),
            (
                self.correction_epoch_status,
                self.correction_epoch,
                "correction epoch",
            ),
        )
        for status, value, label in pairs:
            if (status is BindingStatus.BOUND) != (value is not None):
                raise ValueError(f"{label} status does not match its value")
        return self


class CreditUncertainty(ContractModel):
    kind: CreditUncertaintyKind
    confidence: float = Field(ge=0, le=1)
    reasons: tuple[NonEmptyStr, ...]

    @field_validator("confidence", mode="after")
    @classmethod
    def _require_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("confidence must be finite")
        return value

    @model_validator(mode="after")
    def _validate_uncertainty(self) -> CreditUncertainty:
        if self.kind is CreditUncertaintyKind.NONE:
            if self.confidence != 1 or self.reasons:
                raise ValueError("no uncertainty requires confidence 1 and no reasons")
        elif not self.reasons:
            raise ValueError("uncertainty requires reasons")
        return self


class CreditEvidenceRef(ContractModel):
    evidence_id: NonEmptyStr
    evidence_digest: Sha256Digest
    evidence_kind: NonEmptyStr


class CreditAssignment(ContractModel):
    credit_id: NonEmptyStr
    episode_digest: Sha256Digest
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    correction_epoch: int = Field(ge=0)
    target_step_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    method: CreditMethod
    value: float = Field(ge=-1, le=1)
    evidence_refs: tuple[CreditEvidenceRef, ...] = Field(min_length=1)
    uncertainty: CreditUncertainty
    assigned_at: UtcDateTime

    @field_validator("value", mode="after")
    @classmethod
    def _require_finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("credit value must be finite")
        return value

    @field_validator("target_step_ids", mode="after")
    @classmethod
    def _normalize_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @field_validator("evidence_refs", mode="after")
    @classmethod
    def _normalize_evidence_refs(
        cls, values: tuple[CreditEvidenceRef, ...]
    ) -> tuple[CreditEvidenceRef, ...]:
        by_key = {(item.evidence_id, item.evidence_digest): item for item in values}
        if len(by_key) != len(values):
            raise ValueError("credit evidence refs must be unique")
        return tuple(by_key[key] for key in sorted(by_key))

    @model_validator(mode="after")
    def _prevent_false_causal_certainty(self) -> CreditAssignment:
        if (
            self.uncertainty.kind is CreditUncertaintyKind.NONE
            or self.uncertainty.confidence == 1
        ):
            raise ValueError("V0 forbids deterministic credit")
        return self


class TrajectoryProjection(ContractModel):
    manifest: EpisodeManifest
    steps: tuple[TrajectoryStep, ...] = Field(min_length=1)
    outcome_links: tuple[OutcomeLink, ...] = ()
    correction_links: tuple[CorrectionLink, ...] = ()
    trajectory_digest: Sha256Digest
