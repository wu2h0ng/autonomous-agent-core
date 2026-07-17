from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime, content_digest
from .evidence import Sha256Digest


class EvaluationFailureCode(str, Enum):
    CRITERIA_NOT_MET = "CRITERIA_NOT_MET"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNSUPPORTED = "UNSUPPORTED"


class EvaluationArtifactRole(str, Enum):
    CONFIG = "CONFIG"
    RUBRIC = "RUBRIC"
    PROMPT = "PROMPT"
    CHECKPOINT = "CHECKPOINT"
    HIDDEN_SET = "HIDDEN_SET"
    EVIDENCE = "EVIDENCE"


class EvaluatorIdentity(ContractModel):
    evaluator_id: NonEmptyStr
    principal_id: NonEmptyStr
    implementation_id: NonEmptyStr
    implementation_version: NonEmptyStr
    config_artifact_ref: NonEmptyStr
    config_digest: Sha256Digest
    provider_id: NonEmptyStr
    model_id: NonEmptyStr
    prompt_artifact_ref: NonEmptyStr
    prompt_digest: Sha256Digest
    checkpoint_artifact_ref: NonEmptyStr
    checkpoint_digest: Sha256Digest

    def canonical_digest(self) -> Sha256Digest:
        return content_digest(self)


class RubricRef(ContractModel):
    rubric_id: NonEmptyStr
    rubric_version: NonEmptyStr
    artifact_ref: NonEmptyStr
    rubric_digest: Sha256Digest

    def canonical_digest(self) -> Sha256Digest:
        return content_digest(self)


class HiddenSetManifest(ContractModel):
    manifest_id: NonEmptyStr
    manifest_version: NonEmptyStr
    artifact_ref: NonEmptyStr
    content_digest: Sha256Digest
    item_count: int = Field(ge=1)

    def canonical_digest(self) -> Sha256Digest:
        return content_digest(self)


class EvidenceManifestEntry(ContractModel):
    evidence_ref: NonEmptyStr
    content_digest: Sha256Digest
    media_type: NonEmptyStr


class EvidenceManifest(ContractModel):
    manifest_id: NonEmptyStr
    entries: tuple[EvidenceManifestEntry, ...] = Field(min_length=1)

    @field_validator("entries", mode="after")
    @classmethod
    def _unique_entries(
        cls,
        entries: tuple[EvidenceManifestEntry, ...],
    ) -> tuple[EvidenceManifestEntry, ...]:
        ordered = tuple(sorted(entries, key=lambda entry: entry.evidence_ref))
        if len({entry.evidence_ref for entry in ordered}) != len(ordered):
            raise ValueError("evidence refs must be unique")
        return ordered

    def canonical_digest(self) -> Sha256Digest:
        return content_digest(self)


class EvaluatorRegistration(ContractModel):
    registration_id: NonEmptyStr
    registration_version: NonEmptyStr
    registry_writer_principal_id: NonEmptyStr
    identity: EvaluatorIdentity
    adapter_id: NonEmptyStr
    adapter_version: NonEmptyStr
    adapter_binding_digest: Sha256Digest
    rubric: RubricRef
    hidden_set: HiddenSetManifest
    evidence: EvidenceManifest
    registered_at: UtcDateTime

    @model_validator(mode="after")
    def _separate_writer_and_evaluator(self) -> EvaluatorRegistration:
        if self.registry_writer_principal_id == self.identity.principal_id:
            raise ValueError("registry writer must differ from evaluator principal")
        return self

    def canonical_digest(self) -> Sha256Digest:
        return content_digest(self)


class EvaluatorInput(ContractModel):
    """Caller input references authority; it cannot define evaluator authority."""

    evaluation_id: NonEmptyStr
    proposal_id: NonEmptyStr
    proposer_principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    registration_id: NonEmptyStr
    registration_version: NonEmptyStr
    requested_at: UtcDateTime

    def canonical_digest(self) -> Sha256Digest:
        return content_digest(self)


class EvaluationScore(ContractModel):
    value: float = Field(allow_inf_nan=False)
    scale_min: float = Field(allow_inf_nan=False)
    scale_max: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def _valid_scale(self) -> EvaluationScore:
        if self.scale_max <= self.scale_min:
            raise ValueError("score scale_max must exceed scale_min")
        if not self.scale_min <= self.value <= self.scale_max:
            raise ValueError("score value must be within its scale")
        return self


class Uncertainty(ContractModel):
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    reasons: tuple[NonEmptyStr, ...] = ()

    @field_validator("reasons", mode="after")
    @classmethod
    def _normalize_reasons(cls, reasons: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(reasons)))


class FailureReason(ContractModel):
    code: EvaluationFailureCode
    message: NonEmptyStr
    retriable: bool


class EvaluationConsumptionEntry(ContractModel):
    role: EvaluationArtifactRole
    artifact_ref: NonEmptyStr
    content_digest: Sha256Digest


class EvaluatorMeasurementCandidate(ContractModel):
    """Untrusted backend measurement. It carries no outcome or receipt authority."""

    input_digest: Sha256Digest
    registration_digest: Sha256Digest
    score: EvaluationScore
    uncertainty: Uncertainty
    failure_reasons: tuple[FailureReason, ...] = ()
    consumption_manifest: tuple[EvaluationConsumptionEntry, ...] = Field(min_length=1)
    trace_digest: Sha256Digest


class EvaluationReceipt(ContractModel):
    receipt_id: NonEmptyStr
    evaluation_id: NonEmptyStr
    proposal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    input_digest: Sha256Digest
    registration_id: NonEmptyStr
    registration_version: NonEmptyStr
    registration_digest: Sha256Digest
    evaluator_identity_digest: Sha256Digest
    rubric_digest: Sha256Digest
    hidden_set_manifest_digest: Sha256Digest
    evidence_manifest_digest: Sha256Digest
    score: EvaluationScore
    uncertainty: Uncertainty
    failure_reasons: tuple[FailureReason, ...] = ()
    consumption_manifest: tuple[EvaluationConsumptionEntry, ...] = Field(min_length=1)
    trace_digest: Sha256Digest
    sealed_at: UtcDateTime
    store_namespace: NonEmptyStr
    store_sequence: int = Field(ge=1)
    receipt_digest: Sha256Digest
    store_seal: Sha256Digest

    def canonical_digest(self) -> Sha256Digest:
        return content_digest(
            self.model_dump(
                mode="json",
                exclude={"receipt_digest", "store_seal"},
            )
        )

    @model_validator(mode="after")
    def _valid_receipt_digest(self) -> EvaluationReceipt:
        if self.receipt_digest != self.canonical_digest():
            raise ValueError("receipt_digest does not match canonical receipt")
        return self
