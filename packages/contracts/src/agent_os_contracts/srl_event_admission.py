from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Mapping

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime, content_digest
from .evidence import Sha256Digest


def _content_addressed_digest(
    payload: Mapping[str, Any],
    *,
    id_field: str,
    digest_field: str,
) -> str:
    for excluded_field in (id_field, digest_field):
        if excluded_field in payload:
            raise ValueError(
                f"{excluded_field} must be excluded from its own digest payload"
            )
    return content_digest(payload)


def event_origin_registration_digest(payload: Mapping[str, Any]) -> str:
    return _content_addressed_digest(
        payload,
        id_field="registration_id",
        digest_field="registration_digest",
    )


def credential_lease_digest(payload: Mapping[str, Any]) -> str:
    return _content_addressed_digest(
        payload,
        id_field="lease_id",
        digest_field="lease_digest",
    )


def payload_admission_attestation_digest(payload: Mapping[str, Any]) -> str:
    return _content_addressed_digest(
        payload,
        id_field="attestation_id",
        digest_field="attestation_digest",
    )


def environment_event_admission_receipt_digest(payload: Mapping[str, Any]) -> str:
    return _content_addressed_digest(
        payload,
        id_field="receipt_id",
        digest_field="receipt_digest",
    )


class EventOriginRegistration(ContractModel):
    registration_id: NonEmptyStr
    environment_event_id: NonEmptyStr
    source_id: NonEmptyStr
    source_config_digest: Sha256Digest
    credential_ref_id: NonEmptyStr
    credential_ref_digest: Sha256Digest
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    mandate_id: NonEmptyStr
    environment_binding_id: NonEmptyStr
    event_digest: Sha256Digest
    observation_digest: Sha256Digest
    event_schema_digest: Sha256Digest
    payload_policy_digest: Sha256Digest
    registered_at: UtcDateTime
    registration_digest: Sha256Digest

    @model_validator(mode="after")
    def _validate_content_address(self) -> EventOriginRegistration:
        payload = self.model_dump(
            mode="json",
            exclude={"registration_id", "registration_digest"},
        )
        expected_digest = event_origin_registration_digest(payload)
        if self.registration_digest != expected_digest:
            raise ValueError(
                "registration_digest does not match canonical registration payload"
            )
        if self.registration_id != f"event-origin:{expected_digest}":
            raise ValueError("registration_id does not match registration_digest")
        return self


class CredentialLeaseRef(ContractModel):
    lease_id: NonEmptyStr
    credential_ref_id: NonEmptyStr
    credential_ref_digest: Sha256Digest
    source_id: NonEmptyStr
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    mandate_id: NonEmptyStr
    environment_binding_id: NonEmptyStr
    correction_epoch: int = Field(ge=0)
    issued_at: UtcDateTime
    valid_from: UtcDateTime
    expires_at: UtcDateTime
    issuer_id: NonEmptyStr
    lease_digest: Sha256Digest

    @model_validator(mode="after")
    def _validate_chronology_and_content_address(self) -> CredentialLeaseRef:
        if not self.issued_at <= self.valid_from < self.expires_at:
            raise ValueError("lease requires issued_at <= valid_from < expires_at")
        payload = self.model_dump(
            mode="json",
            exclude={"lease_id", "lease_digest"},
        )
        expected_digest = credential_lease_digest(payload)
        if self.lease_digest != expected_digest:
            raise ValueError("lease_digest does not match canonical lease payload")
        if self.lease_id != f"credential-lease:{expected_digest}":
            raise ValueError("lease_id does not match lease_digest")
        return self


class PayloadAdmissionAttestation(ContractModel):
    attestation_id: NonEmptyStr
    environment_event_id: NonEmptyStr
    source_id: NonEmptyStr
    observation_artifact_id: NonEmptyStr
    observation_digest: Sha256Digest
    policy_digest: Sha256Digest
    schema_digest: Sha256Digest
    issuer_id: NonEmptyStr
    assessed_at: UtcDateTime
    disposition: Literal["ADMITTED_UNDER_POLICY"] = "ADMITTED_UNDER_POLICY"
    credential_reflected: Literal[False] = False
    attestation_digest: Sha256Digest

    @field_validator("credential_reflected", mode="before")
    @classmethod
    def _require_exact_false(cls, value: Any) -> Literal[False]:
        if value is not False:
            raise ValueError("credential_reflected must be exactly boolean False")
        return False

    @model_validator(mode="after")
    def _validate_content_address(self) -> PayloadAdmissionAttestation:
        payload = self.model_dump(
            mode="json",
            exclude={"attestation_id", "attestation_digest"},
        )
        expected_digest = payload_admission_attestation_digest(payload)
        if self.attestation_digest != expected_digest:
            raise ValueError(
                "attestation_digest does not match canonical attestation payload"
            )
        if self.attestation_id != f"payload-admission:{expected_digest}":
            raise ValueError("attestation_id does not match attestation_digest")
        return self


class EnvironmentEventAdmissionReceipt(ContractModel):
    schema_version: Literal["1.1"] = "1.1"  # pyright: ignore[reportIncompatibleVariableOverride]
    receipt_id: NonEmptyStr
    environment_event_id: NonEmptyStr
    event_digest: Sha256Digest
    event_origin_digest: Sha256Digest
    credential_lease_digest: Sha256Digest
    payload_attestation_digest: Sha256Digest
    admission_policy_digest: Sha256Digest
    mandate_id: NonEmptyStr
    environment_binding_id: NonEmptyStr
    environment_binding_version: int = Field(ge=0)
    environment_binding_digest: Sha256Digest
    correction_epoch: int = Field(ge=0)
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    admitted_at: UtcDateTime
    issued_by: Literal["event-admission-service/v1"] = "event-admission-service/v1"
    receipt_digest: Sha256Digest
    grants_authority: Literal[False] = False
    authorizes_effects: Literal[False] = False

    @field_validator("grants_authority", "authorizes_effects", mode="before")
    @classmethod
    def _require_exact_false(cls, value: Any) -> Literal[False]:
        if value is not False:
            raise ValueError("authority fields must be exactly boolean False")
        return False

    @model_validator(mode="after")
    def _validate_content_address(self) -> EnvironmentEventAdmissionReceipt:
        payload = self.model_dump(
            mode="json",
            exclude={"receipt_id", "receipt_digest"},
        )
        expected_digest = environment_event_admission_receipt_digest(payload)
        if self.receipt_digest != expected_digest:
            raise ValueError("receipt_digest does not match canonical receipt payload")
        if self.receipt_id != f"event-admission:{expected_digest}":
            raise ValueError("receipt_id does not match receipt_digest")
        return self


class SituatedTraceStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"


class SituatedTraceReason(str, Enum):
    ASSESSMENT_PENDING = "ASSESSMENT_PENDING"
    TASK_DRAFT = "TASK_DRAFT"
    HELP_REQUEST = "HELP_REQUEST"
    NO_PROPOSAL = "NO_PROPOSAL"
    ADMISSION_DENIED = "ADMISSION_DENIED"
    AUTHORITY_CHANGED = "AUTHORITY_CHANGED"
    PROVIDER_FAILED = "PROVIDER_FAILED"


class SituatedEvaluationTrace(ContractModel):
    trace_id: NonEmptyStr
    admission_receipt_digest: Sha256Digest
    event_id: NonEmptyStr
    projection_id: NonEmptyStr
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    status: SituatedTraceStatus
    reason: SituatedTraceReason
    result_binding_digest: Sha256Digest | None = None
    delegation_attempt_count: int = Field(ge=0)
    committed_provider_call_attempted: bool | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    duration_ms: int = Field(ge=0)
    measurement_scope: Literal["LOCAL_CONTROLLED"] = "LOCAL_CONTROLLED"
    recorded_at: UtcDateTime
