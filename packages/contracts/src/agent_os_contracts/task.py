from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime
from .resource import ResourceBudget, RiskTier


class Goal(ContractModel):
    goal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    created_by: NonEmptyStr
    created_at: UtcDateTime
    statement: NonEmptyStr
    constraints: tuple[NonEmptyStr, ...] = ()


class Commitment(ContractModel):
    commitment_id: NonEmptyStr
    task_id: NonEmptyStr
    goal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    accepted_by: NonEmptyStr
    accepted_at: UtcDateTime
    deliverables: tuple[NonEmptyStr, ...] = Field(min_length=1)
    acceptance_criteria: tuple[NonEmptyStr, ...] = Field(min_length=1)
    authority_scopes: tuple[NonEmptyStr, ...] = ()
    budget: ResourceBudget
    risk_tier: RiskTier
    assumptions: tuple[NonEmptyStr, ...] = ()
    exit_conditions: tuple[NonEmptyStr, ...] = Field(min_length=1)
    expires_at: UtcDateTime

    @field_validator("authority_scopes", mode="after")
    @classmethod
    def _normalize_authority_scopes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _validate_expiry(self) -> Commitment:
        if self.expires_at <= self.accepted_at:
            raise ValueError("expires_at must be after accepted_at")
        return self
