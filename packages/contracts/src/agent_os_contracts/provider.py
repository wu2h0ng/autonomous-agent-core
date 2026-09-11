from __future__ import annotations

import json
from decimal import Decimal
from enum import Enum
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .common import (
    ContractModel,
    NonEmptyStr,
    UtcDateTime,
    canonical_json,
    content_digest,
)
from .authority import CorrectionEpochVector
from .evidence import Sha256Digest
from .trajectory import BindingStatus, WorkingSetRef


class CredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ProviderMessageRole(str, Enum):
    SYSTEM = "SYSTEM"
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    TOOL = "TOOL"


class SessionRef(ContractModel):
    """Stable typed identity for one terminal conversation session."""

    session_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr


class TurnId(ContractModel):
    """Turn identity bound to the session that owns it."""

    turn_id: NonEmptyStr
    session_id: NonEmptyStr


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
    model_revision_digest: Sha256Digest | None = None
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


class ProviderToolCall(ContractModel):
    """Assistant-emitted tool invocation echoed back in conversation history."""

    tool_call_id: NonEmptyStr
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


class ProviderMessage(ContractModel):
    role: ProviderMessageRole
    content: str = ""
    tool_call_id: NonEmptyStr | None = None
    tool_calls: tuple[ProviderToolCall, ...] = ()

    @model_validator(mode="after")
    def _validate_tool_binding(self) -> ProviderMessage:
        if self.role is ProviderMessageRole.TOOL:
            if self.tool_call_id is None:
                raise ValueError("TOOL message requires tool_call_id")
            if self.tool_calls:
                raise ValueError("TOOL message cannot carry tool_calls")
            if not self.content.strip():
                raise ValueError("TOOL message requires tool result content")
        elif self.tool_call_id is not None:
            raise ValueError("tool_call_id is only valid on TOOL messages")
        if self.role is not ProviderMessageRole.ASSISTANT and self.tool_calls:
            raise ValueError("tool_calls are only valid on ASSISTANT messages")
        if not self.content.strip() and not self.tool_calls:
            raise ValueError("message requires content or tool calls")
        return self


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
    """V2 usage: token counts are exact; cost is honest.

    cost_status UNKNOWN (default) means no versioned pricing source exists:
    estimated_cost_usd must be None and is projected as None even for legacy
    v1 payloads that carried an amount — historical figures have no pricing
    provenance and are never trusted or rewritten in the event store.
    cost_status KNOWN requires a non-null amount and a non-empty
    pricing_source_ref; a zero amount is allowed only with a source
    (genuinely free model), never as a pseudo-zero.
    """

    schema_version: Literal["2.0"] = "2.0"  # pyright: ignore[reportIncompatibleVariableOverride]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_usd: Decimal | None = Field(default=None, ge=0)
    cost_status: Literal["KNOWN", "UNKNOWN"] = "UNKNOWN"
    pricing_source_ref: str | None = None

    @model_validator(mode="after")
    def _validate_total(self) -> ProviderUsage:
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens + output_tokens")
        return self

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_v1(cls, data: Any) -> Any:
        """Legacy v1 payloads carried an amount with no cost_status and no
        pricing provenance. Project them to UNKNOWN + None at decode time;
        stored raw events are never rewritten. Any payload that names an
        amount MUST also name cost_status explicitly (v2 writer contract).
        """
        if isinstance(data, dict) and "cost_status" not in data:
            data = dict(data)
            data.pop("estimated_cost_usd", None)
            data["schema_version"] = "2.0"
        return data

    @model_validator(mode="after")
    def _validate_cost_honesty(self) -> ProviderUsage:
        if self.cost_status == "UNKNOWN":
            if self.estimated_cost_usd is not None:
                raise ValueError(
                    "UNKNOWN cost must not carry estimated_cost_usd "
                    "(no pseudo-zero; use KNOWN with a pricing_source_ref)"
                )
            if self.pricing_source_ref is not None:
                raise ValueError("UNKNOWN cost must not carry a pricing_source_ref")
        else:
            if self.estimated_cost_usd is None:
                raise ValueError("KNOWN cost requires estimated_cost_usd")
            if not self.pricing_source_ref:
                raise ValueError("KNOWN cost requires a pricing_source_ref")
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


def provider_execution_receipt_digest(
    payload: Mapping[str, Any],
) -> Sha256Digest:
    """Digest an execution receipt without trusting its claimed seal."""

    return content_digest(
        {key: value for key, value in payload.items() if key != "receipt_digest"}
    )


class ProviderExecutionReceipt(ContractModel):
    """Safe provenance for one Product provider invocation.

    Prompt, response text, credentials and transport configuration are excluded.
    Missing model revisions and working sets remain explicit rather than inferred.
    """

    schema_version: Literal["1.0"] = "1.0"  # pyright: ignore[reportIncompatibleVariableOverride]
    source_event_id: NonEmptyStr
    node_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    provider_profile_id: NonEmptyStr
    provider_profile_digest: Sha256Digest
    provider_id: NonEmptyStr
    model_id: NonEmptyStr
    model_revision_digest: Sha256Digest | None = None
    request_id: NonEmptyStr
    request_digest: Sha256Digest
    response_id: NonEmptyStr
    response_digest: Sha256Digest
    invocation_binding_digest: Sha256Digest
    working_set_ref: WorkingSetRef
    pre_correction_epochs: CorrectionEpochVector
    post_correction_epochs: CorrectionEpochVector
    correction_epoch: int = Field(ge=0)
    missing_fields: tuple[NonEmptyStr, ...] = ()
    receipt_digest: Sha256Digest

    @field_validator("missing_fields", mode="after")
    @classmethod
    def _normalize_missing_fields(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _validate_receipt(self) -> ProviderExecutionReceipt:
        expected_missing: set[str] = set()
        if self.model_revision_digest is None:
            expected_missing.add("model_revision_digest")
        if self.working_set_ref.status is BindingStatus.MISSING:
            expected_missing.add("working_set_digest")
        if set(self.missing_fields) != expected_missing:
            raise ValueError("provider receipt missing fields are not explicit")
        if self.pre_correction_epochs != self.post_correction_epochs:
            raise ValueError("provider correction epochs changed during invocation")
        expected_epoch = max(
            self.pre_correction_epochs.task_epoch,
            self.pre_correction_epochs.run_epoch,
            self.pre_correction_epochs.capability_epoch,
        )
        if self.correction_epoch != expected_epoch:
            raise ValueError("provider receipt correction epoch mismatch")
        expected_digest = provider_execution_receipt_digest(
            self.model_dump(mode="json")
        )
        if self.receipt_digest != expected_digest:
            raise ValueError("provider execution receipt digest mismatch")
        return self


class ProviderFailure(ContractModel):
    failure_id: NonEmptyStr
    request_id: NonEmptyStr
    code: ProviderErrorCode
    retryable: bool
    safe_message: NonEmptyStr
    occurred_at: UtcDateTime
