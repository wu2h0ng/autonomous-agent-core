from __future__ import annotations

from pydantic import Field, field_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime


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

    @field_validator("authority_scopes", mode="after")
    @classmethod
    def _normalize_authority_scopes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))
