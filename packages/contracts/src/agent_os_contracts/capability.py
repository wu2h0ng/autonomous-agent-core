from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime
from .resource import ResourceBudget, RiskTier


class SideEffectGuarantee(str, Enum):
    READ_ONLY = "READ_ONLY"
    TRANSACTIONAL_INTERNAL = "TRANSACTIONAL_INTERNAL"
    IDEMPOTENT_EXTERNAL = "IDEMPOTENT_EXTERNAL"
    CANCELLABLE_EXTERNAL = "CANCELLABLE_EXTERNAL"
    SANDBOX_IDEMPOTENT = "SANDBOX_IDEMPOTENT"
    SANDBOX_COMPENSATABLE = "SANDBOX_COMPENSATABLE"
    NON_IDEMPOTENT_NON_QUERYABLE = "NON_IDEMPOTENT_NON_QUERYABLE"


class CapabilityGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class CapabilitySpec(ContractModel):
    capability_id: NonEmptyStr
    version: NonEmptyStr
    display_name: NonEmptyStr
    input_contract: NonEmptyStr
    output_contract: NonEmptyStr
    side_effect_guarantee: SideEffectGuarantee
    idempotency_supported: bool
    credential_class: NonEmptyStr
    data_boundary: NonEmptyStr
    risk_tier: RiskTier
    timeout_seconds: int = Field(ge=1)
    cancellation_supported: bool
    compensation_supported: bool
    audit_policy: NonEmptyStr
    created_by: NonEmptyStr
    created_at: UtcDateTime
    collaboration_required: bool = False

    @model_validator(mode="after")
    def _validate_side_effect_guarantee(self) -> CapabilitySpec:
        if self.side_effect_guarantee is SideEffectGuarantee.SANDBOX_COMPENSATABLE and not (
            self.idempotency_supported
            and self.cancellation_supported
            and self.compensation_supported
        ):
            raise ValueError(
                "sandbox compensatable capability requires idempotency, cancellation, "
                "and compensation"
            )
        if self.side_effect_guarantee is SideEffectGuarantee.SANDBOX_IDEMPOTENT and not (
            self.idempotency_supported and self.cancellation_supported
        ):
            raise ValueError(
                "sandbox idempotent capability requires idempotency and cancellation"
            )
        if (
            self.side_effect_guarantee
            is SideEffectGuarantee.NON_IDEMPOTENT_NON_QUERYABLE
            and self.idempotency_supported
        ):
            raise ValueError("non-idempotent capability cannot claim idempotency")
        return self


class CapabilityGrant(ContractModel):
    grant_id: NonEmptyStr
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    capability_id: NonEmptyStr
    capability_version: NonEmptyStr
    max_risk_tier: RiskTier
    budget_limit: ResourceBudget
    status: CapabilityGrantStatus
    granted_by: NonEmptyStr
    granted_at: UtcDateTime
    expires_at: UtcDateTime

    @model_validator(mode="after")
    def _validate_expiry(self) -> CapabilityGrant:
        if self.expires_at <= self.granted_at:
            raise ValueError("expires_at must be after granted_at")
        return self
