from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime
from .evidence import ArtifactRef, EvidenceRef, Sha256Digest


class ProjectionEpistemicStatus(str, Enum):
    EVIDENCED = "EVIDENCED"
    HYPOTHESIS = "HYPOTHESIS"
    DISPUTED = "DISPUTED"
    UNKNOWN = "UNKNOWN"


class RelevanceDisposition(str, Enum):
    IGNORE = "IGNORE"
    OBSERVE = "OBSERVE"
    INVESTIGATE = "INVESTIGATE"
    CREATE_TASK = "CREATE_TASK"
    HELP = "HELP"
    ABSTAIN = "ABSTAIN"


class RelevanceUrgency(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


def _normalized(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _validate_evidence_scope(
    evidence: tuple[EvidenceRef, ...],
    *,
    tenant_id: str,
    workspace_id: str,
) -> None:
    for item in evidence:
        if item.tenant_id != tenant_id or item.workspace_id != workspace_id:
            raise ValueError("evidence scope must match contract scope")


class EnvironmentEvent(ContractModel):
    """A domain-opaque observation that carries no work or effect authority."""

    environment_event_id: NonEmptyStr
    environment_binding_id: NonEmptyStr
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    event_type_ref: NonEmptyStr
    dedupe_key: NonEmptyStr
    observation: ArtifactRef
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    occurred_at: UtcDateTime
    recorded_at: UtcDateTime

    @field_validator("evidence", mode="after")
    @classmethod
    def _normalize_evidence(
        cls, values: tuple[EvidenceRef, ...]
    ) -> tuple[EvidenceRef, ...]:
        by_id = {item.evidence_id: item for item in values}
        if len(by_id) != len(values):
            raise ValueError("evidence ids must be unique")
        return tuple(by_id[key] for key in sorted(by_id))

    @model_validator(mode="after")
    def _validate_event(self) -> EnvironmentEvent:
        if self.recorded_at < self.occurred_at:
            raise ValueError("recorded_at cannot precede occurred_at")
        if (
            self.observation.tenant_id != self.tenant_id
            or self.observation.workspace_id != self.workspace_id
        ):
            raise ValueError("observation artifact scope must match event scope")
        _validate_evidence_scope(
            self.evidence,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
        )
        if not any(
            self.observation.artifact_id in item.artifact_ids
            for item in self.evidence
        ):
            raise ValueError(
                "event evidence must reference the bound observation artifact"
            )
        return self


class OperationalProjectionRef(ContractModel):
    """An exact, opaque projection artifact reference, never an authority source."""

    projection_id: NonEmptyStr
    environment_binding_id: NonEmptyStr
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    task_id: NonEmptyStr | None = None
    source_event_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    projection_artifact: ArtifactRef
    schema_uri: NonEmptyStr
    version: int = Field(ge=1)
    scope_ref: NonEmptyStr
    valid_from: UtcDateTime
    recorded_at: UtcDateTime
    fresh_until: UtcDateTime
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    epistemic_status: ProjectionEpistemicStatus
    uncertainty_summary: NonEmptyStr
    conflict_refs: tuple[NonEmptyStr, ...] = ()
    compatibility_digest: Sha256Digest

    @field_validator("source_event_ids", "conflict_refs", mode="after")
    @classmethod
    def _normalize_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized(values)

    @field_validator("evidence", mode="after")
    @classmethod
    def _normalize_evidence(
        cls, values: tuple[EvidenceRef, ...]
    ) -> tuple[EvidenceRef, ...]:
        by_id = {item.evidence_id: item for item in values}
        if len(by_id) != len(values):
            raise ValueError("evidence ids must be unique")
        return tuple(by_id[key] for key in sorted(by_id))

    @model_validator(mode="after")
    def _validate_projection(self) -> OperationalProjectionRef:
        if self.recorded_at < self.valid_from:
            raise ValueError("recorded_at cannot precede valid_from")
        if self.fresh_until <= self.recorded_at:
            raise ValueError("fresh_until must follow recorded_at")
        if (
            self.projection_artifact.tenant_id != self.tenant_id
            or self.projection_artifact.workspace_id != self.workspace_id
        ):
            raise ValueError("projection artifact scope must match projection scope")
        _validate_evidence_scope(
            self.evidence,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
        )
        if not any(
            self.projection_artifact.artifact_id in item.artifact_ids
            for item in self.evidence
        ):
            raise ValueError(
                "projection evidence must reference the bound projection artifact"
            )
        return self


class RelevanceAssessment(ContractModel):
    assessment_id: NonEmptyStr
    environment_event_id: NonEmptyStr
    event_observation_digest: Sha256Digest
    projection_id: NonEmptyStr
    projection_digest: Sha256Digest
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    affected_commitment_ids: tuple[NonEmptyStr, ...] = ()
    disposition: RelevanceDisposition
    uncertainty_summary: NonEmptyStr
    urgency: RelevanceUrgency
    expected_loss_of_delay: NonEmptyStr
    attention_budget_seconds: int = Field(gt=0)
    rationale: NonEmptyStr
    evidence_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    proposed_goal_statement: NonEmptyStr | None = None
    known_facts: tuple[NonEmptyStr, ...] = ()
    unknown_facts: tuple[NonEmptyStr, ...] = ()
    acquisition_attempts: tuple[NonEmptyStr, ...] = ()
    bounded_options: tuple[NonEmptyStr, ...] = ()
    minimum_external_input: NonEmptyStr | None = None
    continuable_work: tuple[NonEmptyStr, ...] = ()
    assessed_at: UtcDateTime

    @field_validator(
        "affected_commitment_ids",
        "evidence_ids",
        "known_facts",
        "unknown_facts",
        "acquisition_attempts",
        "bounded_options",
        "continuable_work",
        mode="after",
    )
    @classmethod
    def _normalize_string_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized(values)

    @model_validator(mode="after")
    def _validate_disposition_payload(self) -> RelevanceAssessment:
        task_dispositions = {
            RelevanceDisposition.INVESTIGATE,
            RelevanceDisposition.CREATE_TASK,
        }
        if self.disposition in task_dispositions:
            if self.proposed_goal_statement is None:
                raise ValueError(
                    "proposed_goal_statement is required for task dispositions"
                )
            if self.minimum_external_input is not None:
                raise ValueError(
                    "minimum_external_input is only valid for HELP disposition"
                )
        elif self.disposition is RelevanceDisposition.HELP:
            if self.minimum_external_input is None:
                raise ValueError(
                    "minimum_external_input is required for HELP disposition"
                )
            if self.proposed_goal_statement is not None:
                raise ValueError(
                    "proposed_goal_statement is not valid for HELP disposition"
                )
        elif self.proposed_goal_statement is not None:
            raise ValueError(
                "proposed_goal_statement is not valid for non-work disposition"
            )
        return self


class ProposedGoal(ContractModel):
    """A non-activatable goal proposal distinct from the Task creation contract."""

    proposal_goal_id: NonEmptyStr
    source_binding_digest: Sha256Digest
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    created_by: NonEmptyStr
    created_at: UtcDateTime
    statement: NonEmptyStr
    constraints: tuple[NonEmptyStr, ...] = ()


class TaskDraftProposal(ContractModel):
    task_draft_id: NonEmptyStr
    source_binding_digest: Sha256Digest
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    triggering_event_id: NonEmptyStr
    event_observation_digest: Sha256Digest
    projection_id: NonEmptyStr
    projection_digest: Sha256Digest
    relevance_assessment_id: NonEmptyStr
    goal: ProposedGoal
    evidence_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    created_at: UtcDateTime
    activation_authorized: Literal[False] = False
    external_effects_authorized: Literal[False] = False


class HelpRequest(ContractModel):
    help_request_id: NonEmptyStr
    source_binding_digest: Sha256Digest
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    triggering_event_id: NonEmptyStr
    event_observation_digest: Sha256Digest
    projection_id: NonEmptyStr
    relevance_assessment_id: NonEmptyStr
    known_facts: tuple[NonEmptyStr, ...]
    unknown_facts: tuple[NonEmptyStr, ...]
    acquisition_attempts: tuple[NonEmptyStr, ...]
    bounded_options: tuple[NonEmptyStr, ...]
    minimum_external_input: NonEmptyStr
    continuable_work: tuple[NonEmptyStr, ...]
    rationale: NonEmptyStr
    evidence_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    created_at: UtcDateTime
    authority_granted: Literal[False] = False
    external_effects_authorized: Literal[False] = False
