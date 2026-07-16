from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime
from .srl_help import HelpBudget


class MandateStatus(str, Enum):
    DRAFT = "DRAFT"
    RATIFIED = "RATIFIED"
    ACTIVE = "ACTIVE"
    AMENDMENT_PROPOSED = "AMENDMENT_PROPOSED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class EvaluationPrinciple(ContractModel):
    principle_id: NonEmptyStr
    statement: NonEmptyStr
    outcome_criteria_ref: NonEmptyStr | None = None
    weight: float = Field(ge=0.0, le=1.0)


class MandateEnvelope(ContractModel):
    allowed_task_classes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    allowed_effect_classes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    allowed_resource_refs: tuple[NonEmptyStr, ...] = ()
    capability_grant_rules: tuple[NonEmptyStr, ...] = Field(min_length=1)
    wake_budget_per_window: int = Field(ge=0)
    query_budget_per_window: int = Field(ge=0)
    help_budget: HelpBudget
    max_concurrent_tasks: int = Field(ge=1)
    max_duration_seconds: int = Field(ge=1)
    evaluation_principles: tuple[EvaluationPrinciple, ...] = Field(min_length=1)
    escalation_conditions: tuple[NonEmptyStr, ...] = Field(min_length=1)


class Mandate(ContractModel):
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    principal_id: NonEmptyStr
    status: MandateStatus
    mission_statement: NonEmptyStr
    desired_outcomes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    permanent_constraints: tuple[NonEmptyStr, ...] = Field(min_length=1)
    authority_envelope: MandateEnvelope
    environment_binding_classes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    time_horizon: NonEmptyStr
    review_cadence_seconds: int = Field(ge=1)
    expires_at: UtcDateTime
    correction_epoch: int = Field(ge=0)
    revocation_conditions: tuple[NonEmptyStr, ...] = Field(min_length=1)
    proposed_amendment_id: NonEmptyStr | None = None
    created_at: UtcDateTime
    ratified_at: UtcDateTime | None = None

    @model_validator(mode="after")
    def _ratified_requires_receipt(self) -> "Mandate":
        if self.status in {MandateStatus.RATIFIED, MandateStatus.ACTIVE} and self.ratified_at is None:
            raise ValueError("ratified/active Mandate requires ratified_at")
        return self


class MandateRatificationReceipt(ContractModel):
    receipt_id: NonEmptyStr
    mandate_id: NonEmptyStr
    mandate_digest: NonEmptyStr
    principal_attestation: NonEmptyStr
    agent_instance_ref_id: NonEmptyStr
    initial_correction_epoch: int = Field(ge=0)
    ratified_at: UtcDateTime


class AgentInstanceRef(ContractModel):
    instance_id: NonEmptyStr
    implementation_id: NonEmptyStr
    implementation_version: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    created_at: UtcDateTime
    # NOTE: explicitly excludes mission, permissions, environment access and learning history.


class StandingMission(ContractModel):
    standing_mission_id: NonEmptyStr
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    statement: NonEmptyStr
    outcome_criteria_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    active_commitment_ids: tuple[NonEmptyStr, ...] = ()
    disallowed_action_classes: tuple[NonEmptyStr, ...] = ()
    review_cadence_seconds: int = Field(ge=1)
    projected_at: UtcDateTime
    expires_at: UtcDateTime
    parent_mandate_digest: NonEmptyStr
    correction_epoch: int = Field(ge=0)
    ratification_receipt_digest: NonEmptyStr
