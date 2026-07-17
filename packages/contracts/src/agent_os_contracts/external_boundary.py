from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime, content_digest
from .evidence import Sha256Digest
from .authority import CorrectionEpochVector
from .provider import CredentialRef


class BoundaryDisposition(str, Enum):
    DENIED = "DENIED"
    CANDIDATE_MIRRORED = "CANDIDATE_MIRRORED"
    EXPORTED = "EXPORTED"


class ExternalExecutionResourceRef(ContractModel):
    resource_id: NonEmptyStr
    backend_id: NonEmptyStr
    backend_version: int = Field(ge=1)
    task_id: NonEmptyStr
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr


class ExecutionCheckpointCandidate(ContractModel):
    checkpoint_id: NonEmptyStr
    backend_id: NonEmptyStr
    backend_version: int = Field(ge=1)
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    history_digest: Sha256Digest
    resume_cursor: NonEmptyStr
    payload_digest: Sha256Digest
    recorded_at: UtcDateTime
    epistemic_status: Literal["CANDIDATE"] = "CANDIDATE"
    activation_authorized: Literal[False] = False
    capability_grant_authorized: Literal[False] = False
    outcome_verification_authorized: Literal[False] = False


class ExternalBoundaryReceipt(ContractModel):
    receipt_id: NonEmptyStr
    receipt_digest: Sha256Digest
    boundary_kind: Literal["DURABLE_EXECUTION", "TRACE_EXPORT"]
    disposition: BoundaryDisposition
    backend_id: NonEmptyStr
    backend_version: int = Field(ge=1)
    resource_id: NonEmptyStr
    subject_digest: Sha256Digest | None = None
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    reason_code: NonEmptyStr
    redacted_fields: tuple[NonEmptyStr, ...] = ()
    checkpoint_candidate: ExecutionCheckpointCandidate | None = None
    activation_authorized: Literal[False] = False
    capability_grant_authorized: Literal[False] = False
    outcome_verification_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_seal(self) -> ExternalBoundaryReceipt:
        payload = self.model_dump(
            mode="json", exclude={"receipt_id", "receipt_digest"}
        )
        expected = content_digest(payload)
        if self.receipt_digest != expected:
            raise ValueError("external boundary receipt digest mismatch")
        if self.receipt_id != f"external-boundary:{expected}":
            raise ValueError("external boundary receipt id mismatch")
        if (
            self.disposition is not BoundaryDisposition.DENIED
            and self.subject_digest is None
        ):
            raise ValueError("successful external boundary receipt requires subject")
        if self.disposition is BoundaryDisposition.CANDIDATE_MIRRORED:
            if self.checkpoint_candidate is None:
                raise ValueError("mirrored receipt requires checkpoint candidate")
            if content_digest(self.checkpoint_candidate) != self.subject_digest:
                raise ValueError("checkpoint candidate digest mismatch")
        elif self.checkpoint_candidate is not None:
            raise ValueError("checkpoint candidate is only valid for mirrored receipt")
        return self


class ExternalPolicyQuery(ContractModel):
    backend_id: NonEmptyStr
    backend_version: int = Field(ge=1)
    action_id: NonEmptyStr
    action_digest: Sha256Digest
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    capability_id: NonEmptyStr
    capability_version: NonEmptyStr
    grant_id: NonEmptyStr
    policy_version: NonEmptyStr
    risk_tier: int = Field(ge=0, le=5)
    correction_epochs: CorrectionEpochVector


class ExternalPolicyAdvice(ContractModel):
    backend_id: NonEmptyStr
    backend_version: int = Field(ge=1)
    action_id: NonEmptyStr
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    verdict: Literal["ALLOW", "DENY"]
    reason_codes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    evaluated_at: UtcDateTime


TraceAttributeValue = str | int | float | bool | None


class RedactedTraceExportRecord(ContractModel):
    export_record_id: NonEmptyStr
    exporter_id: NonEmptyStr
    exporter_version: int = Field(ge=1)
    trace_id: NonEmptyStr
    resource_id: NonEmptyStr
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    trace_digest: Sha256Digest
    credential_ref: CredentialRef | None = None
    attributes: dict[NonEmptyStr, TraceAttributeValue]
    redacted_fields: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_id(self) -> RedactedTraceExportRecord:
        expected = content_digest(
            self.model_dump(mode="json", exclude={"export_record_id"})
        )
        if self.export_record_id != f"trace-export:{expected}":
            raise ValueError("trace export record id mismatch")
        return self


__all__ = [
    "BoundaryDisposition",
    "ExecutionCheckpointCandidate",
    "ExternalBoundaryReceipt",
    "ExternalExecutionResourceRef",
    "ExternalPolicyAdvice",
    "ExternalPolicyQuery",
    "RedactedTraceExportRecord",
    "TraceAttributeValue",
]
