from __future__ import annotations

import json
from decimal import Decimal
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
from .evidence import Sha256Digest


class CredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ProviderMessageRole(str, Enum):
    SYSTEM = "SYSTEM"
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    TOOL = "TOOL"


class ProviderErrorCode(str, Enum):
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    MALFORMED = "MALFORMED"
    REFUSED = "REFUSED"
    UNAVAILABLE = "UNAVAILABLE"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"


class CredentialRef(ContractModel):
    credential_ref_id: NonEmptyStr
    owner_principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    provider_id: NonEmptyStr
    resolver_key: NonEmptyStr
    scopes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    status: CredentialStatus
    created_at: UtcDateTime
    expires_at: UtcDateTime

    @field_validator("scopes", mode="after")
    @classmethod
    def _normalize_scopes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _validate_expiry(self) -> CredentialRef:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self


class ProviderProfile(ContractModel):
    profile_id: NonEmptyStr
    provider_id: NonEmptyStr
    model_id: NonEmptyStr
    endpoint_class: NonEmptyStr
    credential_ref_id: NonEmptyStr
    capabilities: tuple[NonEmptyStr, ...] = Field(min_length=1)
    max_context_tokens: int = Field(ge=1)
    request_timeout_seconds: int = Field(ge=1)
    created_at: UtcDateTime

    @field_validator("capabilities", mode="after")
    @classmethod
    def _normalize_capabilities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class ProviderInvocationBinding(ContractModel):
    """Exact provider profile plus adapter settings that alter invocation semantics."""

    schema_version: Literal["2.0"] = "2.0"  # pyright: ignore[reportIncompatibleVariableOverride]
    provider_profile: ProviderProfile
    provider_id: NonEmptyStr
    endpoint_class: NonEmptyStr
    credential_ref_id: NonEmptyStr
    credential_ref_digest: Sha256Digest
    max_context_tokens: int = Field(ge=1)
    adapter_kind: NonEmptyStr
    transport: NonEmptyStr
    base_url: NonEmptyStr
    endpoint_path: NonEmptyStr
    model_id: NonEmptyStr
    request_timeout_seconds: int = Field(ge=1)
    temperature: Decimal = Field(allow_inf_nan=False)

    def digest(self) -> Sha256Digest:
        return content_digest(self)

    @model_validator(mode="after")
    def _validate_profile_consistency(self) -> ProviderInvocationBinding:
        exact_values = (
            (self.provider_id, self.provider_profile.provider_id, "provider id"),
            (self.model_id, self.provider_profile.model_id, "model id"),
            (
                self.endpoint_class,
                self.provider_profile.endpoint_class,
                "endpoint class",
            ),
            (
                self.credential_ref_id,
                self.provider_profile.credential_ref_id,
                "credential ref id",
            ),
            (
                self.max_context_tokens,
                self.provider_profile.max_context_tokens,
                "max context tokens",
            ),
        )
        for actual, expected, label in exact_values:
            if actual != expected:
                raise ValueError(
                    f"invocation {label} must match the complete provider profile"
                )
        return self


class ProviderMessage(ContractModel):
    role: ProviderMessageRole
    content: NonEmptyStr


class ProviderToolProposal(ContractModel):
    proposal_id: NonEmptyStr
    capability_id: NonEmptyStr
    arguments_json: NonEmptyStr

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


class ProviderRequest(ContractModel):
    request_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    provider_profile_id: NonEmptyStr
    messages: tuple[ProviderMessage, ...] = Field(min_length=1)
    allowed_capability_ids: tuple[NonEmptyStr, ...] = ()
    timeout_seconds: int = Field(ge=1)
    created_at: UtcDateTime

    @field_validator("allowed_capability_ids", mode="after")
    @classmethod
    def _normalize_capabilities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class ProviderDecisionRequest(ContractModel):
    """Narrow model decision input that carries no Task/Run authority."""

    schema_version: Literal["2.0"] = "2.0"  # pyright: ignore[reportIncompatibleVariableOverride]
    request_id: NonEmptyStr
    decision_kind: NonEmptyStr
    provider_profile_id: NonEmptyStr
    expected_invocation_binding_digest: Sha256Digest
    messages: tuple[ProviderMessage, ...] = Field(min_length=1)
    timeout_seconds: int = Field(ge=1)
    created_at: UtcDateTime


class ProviderUsage(ContractModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_usd: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def _validate_total(self) -> ProviderUsage:
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens + output_tokens")
        return self


class ProviderResponse(ContractModel):
    """V1-compatible response; relevance V2 requires the optional receipt field."""

    response_id: NonEmptyStr
    request_id: NonEmptyStr
    text: str
    tool_proposals: tuple[ProviderToolProposal, ...]
    usage: ProviderUsage
    finish_reason: NonEmptyStr
    received_at: UtcDateTime
    invocation_binding_digest: Sha256Digest | None = None

    @model_validator(mode="after")
    def _require_content(self) -> ProviderResponse:
        if not self.text.strip() and not self.tool_proposals:
            raise ValueError("provider response requires text or tool proposal")
        return self


class ProviderFailure(ContractModel):
    failure_id: NonEmptyStr
    request_id: NonEmptyStr
    code: ProviderErrorCode
    retryable: bool
    safe_message: NonEmptyStr
    occurred_at: UtcDateTime
