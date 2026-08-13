from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime, content_digest
from .evidence import Sha256Digest
from .situated import (
    EnvironmentBindingAuthorization,
    MandateRelevanceContextRef,
    RelevanceAssessorRef,
)
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


class CreateMandateCommand(ContractModel):
    mandate_id: NonEmptyStr
    mission_statement: NonEmptyStr
    desired_outcomes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    permanent_constraints: tuple[NonEmptyStr, ...] = Field(min_length=1)
    authority_envelope: MandateEnvelope
    environment_binding_classes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    time_horizon: NonEmptyStr
    review_cadence_seconds: int = Field(ge=1)
    expires_at: UtcDateTime
    revocation_conditions: tuple[NonEmptyStr, ...] = Field(min_length=1)
    agent_instance_ref_id: NonEmptyStr
    outcome_criteria_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    principal_attestation: NonEmptyStr


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


class MandateWorkspaceRecord(ContractModel):
    source_command_digest: NonEmptyStr
    mandate: Mandate
    ratification_receipt: MandateRatificationReceipt
    standing_mission: StandingMission
    task_activation_authorized: bool = False
    capability_grant_authorized: bool = False

    @model_validator(mode="after")
    def _cannot_authorize_execution(self) -> "MandateWorkspaceRecord":
        if self.task_activation_authorized or self.capability_grant_authorized:
            raise ValueError("Mandate Workspace record cannot authorize execution")
        return self


class ObservationBindingDescriptor(ContractModel):
    """Server-provisioned exact observation source and cognition binding."""

    environment_binding_id: NonEmptyStr
    environment_binding_class: NonEmptyStr
    version: int = Field(ge=1)
    source_descriptor_digest: Sha256Digest
    observation_capabilities: tuple[NonEmptyStr, ...] = Field(min_length=1)
    max_wake_budget_per_window: int = Field(ge=0)
    max_query_budget_per_window: int = Field(ge=0)
    relevance_assessor: RelevanceAssessorRef
    relevance_context: MandateRelevanceContextRef


class MandateObservationAuthorizationCommand(ContractModel):
    """A request to authorize observation only; authority fields are server-owned."""

    authorization_id: NonEmptyStr
    environment_binding_id: NonEmptyStr
    environment_binding_class: NonEmptyStr
    binding_version: int = Field(ge=1)
    requested_capabilities: tuple[NonEmptyStr, ...] = Field(min_length=1)
    wake_budget_per_window: int = Field(ge=0)
    query_budget_per_window: int = Field(ge=0)
    relevance_assessor: RelevanceAssessorRef
    relevance_context: MandateRelevanceContextRef


class MandateObservationAuthorizationReceipt(ContractModel):
    """Sealed projection receipt. It grants observation but no work authority."""

    authorization_receipt_id: NonEmptyStr
    authorization_receipt_digest: Sha256Digest
    authorization_id: NonEmptyStr
    mandate_id: NonEmptyStr
    mandate_version: int = Field(ge=1)
    mandate_digest: Sha256Digest
    workspace_record_digest: Sha256Digest
    ratification_receipt_id: NonEmptyStr
    ratification_receipt_digest: Sha256Digest
    owner_principal_id: NonEmptyStr
    authorized_by: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    correction_epoch: int = Field(ge=0)
    authorized_at: UtcDateTime
    expires_at: UtcDateTime
    environment_binding_class: NonEmptyStr
    source_descriptor_digest: Sha256Digest
    environment_binding: EnvironmentBindingAuthorization
    observation_capabilities: tuple[NonEmptyStr, ...] = Field(min_length=1)
    wake_budget_per_window: int = Field(ge=0)
    query_budget_per_window: int = Field(ge=0)
    relevance_assessor: RelevanceAssessorRef
    relevance_context: MandateRelevanceContextRef
    task_activation_authorized: Literal[False] = False
    capability_grant_authorized: Literal[False] = False
    external_effects_authorized: Literal[False] = False

    @field_validator(
        "task_activation_authorized",
        "capability_grant_authorized",
        "external_effects_authorized",
        mode="before",
    )
    @classmethod
    def _require_exact_false(cls, value: Any) -> Literal[False]:
        if value is not False:
            raise ValueError("observation authorization cannot grant execution")
        return False

    @classmethod
    def create(cls, **payload: object) -> "MandateObservationAuthorizationReceipt":
        sealed_payload = {"schema_version": "1.0", **payload}
        digest = content_digest(sealed_payload)
        return cls.model_validate(
            {
                "authorization_receipt_id": (
                    f"mandate-observation-authorization:{digest}"
                ),
                "authorization_receipt_digest": digest,
                **payload,
            }
        )

    @model_validator(mode="after")
    def _validate_seal(self) -> "MandateObservationAuthorizationReceipt":
        payload = self.model_dump(
            mode="json",
            exclude={"authorization_receipt_id", "authorization_receipt_digest"},
        )
        expected = content_digest(payload)
        if self.authorization_receipt_digest != expected:
            raise ValueError("Mandate observation authorization digest mismatch")
        if self.authorization_receipt_id != (
            f"mandate-observation-authorization:{expected}"
        ):
            raise ValueError("Mandate observation authorization id mismatch")
        return self
