from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime, content_digest
from .evidence import ArtifactRef, EvidenceRef, Sha256Digest
from .provider import ProviderInvocationBinding


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


class MandateOperationalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REVOKED = "REVOKED"


class SituatedAssessmentOutcomeKind(str, Enum):
    NO_PROPOSAL = "NO_PROPOSAL"
    TASK_DRAFT = "TASK_DRAFT"
    HELP_REQUEST = "HELP_REQUEST"


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


class RelevanceAssessorRef(ContractModel):
    """Versioned policy identity; it grants no work or effect authority."""

    assessor_id: NonEmptyStr
    version: int = Field(ge=1)
    policy_digest: Sha256Digest


class ProviderRelevancePolicy(ContractModel):
    """Ratifiable provider-assessor policy; it grants no work authority."""

    schema_version: Literal["2.0"] = "2.0"  # pyright: ignore[reportIncompatibleVariableOverride]
    assessor_id: NonEmptyStr
    version: int = Field(ge=1)
    provider_invocation: ProviderInvocationBinding
    prompt_revision: NonEmptyStr
    prompt_template_digest: Sha256Digest
    output_schema_ref: NonEmptyStr
    output_schema_digest: Sha256Digest
    request_timeout_seconds: int = Field(ge=1)
    max_artifact_bytes: int = Field(ge=1)
    failure_attention_budget_seconds: int = Field(ge=1)

    def assessor_ref(self) -> RelevanceAssessorRef:
        return RelevanceAssessorRef(
            assessor_id=self.assessor_id,
            version=self.version,
            policy_digest=content_digest(self),
        )


class MandateOutcomeContext(ContractModel):
    outcome_id: NonEmptyStr
    statement: NonEmptyStr


class MandateCommitmentContext(ContractModel):
    commitment_id: NonEmptyStr
    statement: NonEmptyStr
    due_at: UtcDateTime | None = None


class MandateRelevanceContextRef(ContractModel):
    relevance_context_id: NonEmptyStr
    version: int = Field(ge=1)
    content_digest: Sha256Digest


class MandateRelevanceContext(ContractModel):
    """Digest-bound semantic context ratified for relevance assessment only."""

    relevance_context_id: NonEmptyStr
    version: int = Field(ge=1)
    mandate_id: NonEmptyStr
    mandate_version: int = Field(ge=1)
    mandate_digest: Sha256Digest
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    mission_statement: NonEmptyStr
    desired_outcomes: tuple[MandateOutcomeContext, ...] = Field(min_length=1)
    open_commitments: tuple[MandateCommitmentContext, ...] = ()
    permanent_constraints: tuple[NonEmptyStr, ...] = ()

    def ref(self) -> MandateRelevanceContextRef:
        return MandateRelevanceContextRef(
            relevance_context_id=self.relevance_context_id,
            version=self.version,
            content_digest=content_digest(self),
        )


class EnvironmentBindingAuthorization(ContractModel):
    """Exact externally authorized observation binding."""

    environment_binding_id: NonEmptyStr
    version: int = Field(ge=1)
    binding_digest: Sha256Digest


class RatifiedMandateRef(ContractModel):
    """Minimal V0 ratification anchor, not a self-writable Mandate aggregate."""

    mandate_id: NonEmptyStr
    version: int = Field(ge=1)
    mandate_digest: Sha256Digest
    ratification_receipt_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    owner_principal_id: NonEmptyStr
    ratified_by: NonEmptyStr
    ratified_at: UtcDateTime
    valid_from: UtcDateTime
    expires_at: UtcDateTime
    correction_epoch: int = Field(ge=0)
    status: MandateOperationalStatus = MandateOperationalStatus.ACTIVE
    authority_envelope_digest: Sha256Digest
    allowed_environment_bindings: tuple[EnvironmentBindingAuthorization, ...] = Field(
        min_length=1
    )
    relevance_assessor: RelevanceAssessorRef
    relevance_context: MandateRelevanceContextRef | None = None

    @field_validator("allowed_environment_bindings", mode="after")
    @classmethod
    def _unique_bindings(
        cls, values: tuple[EnvironmentBindingAuthorization, ...]
    ) -> tuple[EnvironmentBindingAuthorization, ...]:
        indexed = {item.environment_binding_id: item for item in values}
        if len(indexed) != len(values):
            raise ValueError("environment binding ids must be unique")
        return tuple(indexed[key] for key in sorted(indexed))

    @model_validator(mode="after")
    def _validate_ratification(self) -> RatifiedMandateRef:
        if self.valid_from < self.ratified_at:
            raise ValueError("mandate valid_from cannot precede ratification")
        if self.expires_at <= self.valid_from:
            raise ValueError("mandate expires_at must follow valid_from")
        return self

    def binding(self, binding_id: str) -> EnvironmentBindingAuthorization | None:
        return next(
            (
                item
                for item in self.allowed_environment_bindings
                if item.environment_binding_id == binding_id
            ),
            None,
        )


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
            self.observation.artifact_id in item.artifact_ids for item in self.evidence
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
    schema_version: Literal["1.0", "2.0"] = "2.0"  # pyright: ignore[reportIncompatibleVariableOverride]
    assessment_id: NonEmptyStr
    environment_event_id: NonEmptyStr
    event_observation_digest: Sha256Digest
    projection_id: NonEmptyStr
    projection_digest: Sha256Digest
    mandate_id: NonEmptyStr
    mandate_version: int = Field(ge=1)
    mandate_digest: Sha256Digest
    environment_binding_id: NonEmptyStr
    environment_binding_version: int = Field(ge=1)
    environment_binding_digest: Sha256Digest
    correction_epoch: int = Field(ge=0)
    assessor: RelevanceAssessorRef
    expected_provider_invocation_binding_digest: Sha256Digest | None = None
    provider_call_attempted: bool = False
    provider_invocation_receipt_digest: Sha256Digest | None = None
    provider_invocation_binding_digest: Sha256Digest | None = None
    input_binding_digest: Sha256Digest
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
        if self.provider_invocation_receipt_digest is not None:
            if not self.provider_call_attempted:
                raise ValueError("provider receipt requires an attempted provider call")
            if (
                self.expected_provider_invocation_binding_digest
                != self.provider_invocation_receipt_digest
            ):
                raise ValueError("provider receipt must match the expected invocation")
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


class RelevanceAssessmentDraft(ContractModel):
    """Provider-authored semantics only; trusted code supplies all bindings."""

    schema_version: Literal["2.0"] = "2.0"  # pyright: ignore[reportIncompatibleVariableOverride]
    affected_commitment_ids: tuple[NonEmptyStr, ...] = ()
    disposition: RelevanceDisposition
    uncertainty_summary: NonEmptyStr
    urgency: RelevanceUrgency
    expected_loss_of_delay: NonEmptyStr
    attention_budget_seconds: int = Field(gt=0)
    rationale: NonEmptyStr
    proposed_goal_statement: NonEmptyStr | None = None
    known_facts: tuple[NonEmptyStr, ...] = ()
    unknown_facts: tuple[NonEmptyStr, ...] = ()
    acquisition_attempts: tuple[NonEmptyStr, ...] = ()
    bounded_options: tuple[NonEmptyStr, ...] = ()
    minimum_external_input: NonEmptyStr | None = None
    continuable_work: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def _validate_payload(self) -> RelevanceAssessmentDraft:
        task_dispositions = {
            RelevanceDisposition.INVESTIGATE,
            RelevanceDisposition.CREATE_TASK,
        }
        if self.disposition in task_dispositions:
            if (
                self.proposed_goal_statement is None
                or self.minimum_external_input is not None
            ):
                raise ValueError(
                    "task disposition requires only proposed_goal_statement"
                )
        elif self.disposition is RelevanceDisposition.HELP:
            if (
                self.minimum_external_input is None
                or self.proposed_goal_statement is not None
            ):
                raise ValueError("HELP requires only minimum_external_input")
        elif (
            self.proposed_goal_statement is not None
            or self.minimum_external_input is not None
        ):
            raise ValueError(
                "non-work disposition cannot propose a goal or request input"
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
    mandate_version: int = Field(ge=1)
    mandate_digest: Sha256Digest
    environment_binding_id: NonEmptyStr
    environment_binding_version: int = Field(ge=1)
    environment_binding_digest: Sha256Digest
    correction_epoch: int = Field(ge=0)
    assessor: RelevanceAssessorRef
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
    mandate_version: int = Field(ge=1)
    mandate_digest: Sha256Digest
    environment_binding_id: NonEmptyStr
    environment_binding_version: int = Field(ge=1)
    environment_binding_digest: Sha256Digest
    correction_epoch: int = Field(ge=0)
    assessor: RelevanceAssessorRef
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    triggering_event_id: NonEmptyStr
    event_observation_digest: Sha256Digest
    projection_id: NonEmptyStr
    projection_digest: Sha256Digest
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


class SituatedAssessmentRecord(ContractModel):
    """Durable proposal-only assessment outcome; never a Task or effect authority."""

    assessment_record_id: NonEmptyStr
    source_binding_digest: Sha256Digest
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    assessment: RelevanceAssessment
    outcome_kind: SituatedAssessmentOutcomeKind
    task_draft: TaskDraftProposal | None = None
    help_request: HelpRequest | None = None
    recorded_at: UtcDateTime

    @model_validator(mode="after")
    def _validate_outcome(self) -> SituatedAssessmentRecord:
        if self.assessment_record_id != (
            f"situated-assessment:{self.source_binding_digest}"
        ):
            raise ValueError("assessment record id must be source-bound")
        if (
            self.tenant_id != self.assessment.tenant_id
            or self.workspace_id != self.assessment.workspace_id
        ):
            raise ValueError("assessment record scope must match assessment scope")
        if self.recorded_at < self.assessment.assessed_at:
            raise ValueError("assessment record cannot precede assessment")
        expected_kind = SituatedAssessmentOutcomeKind.NO_PROPOSAL
        outcome: TaskDraftProposal | HelpRequest | None = None
        if self.assessment.disposition in {
            RelevanceDisposition.INVESTIGATE,
            RelevanceDisposition.CREATE_TASK,
        }:
            expected_kind = SituatedAssessmentOutcomeKind.TASK_DRAFT
            outcome = self.task_draft
            if outcome is None or self.help_request is not None:
                raise ValueError("task assessment must contain exactly one task draft")
        elif self.assessment.disposition is RelevanceDisposition.HELP:
            expected_kind = SituatedAssessmentOutcomeKind.HELP_REQUEST
            outcome = self.help_request
            if outcome is None or self.task_draft is not None:
                raise ValueError(
                    "help assessment must contain exactly one help request"
                )
        elif self.task_draft is not None or self.help_request is not None:
            raise ValueError("non-work assessment cannot contain a proposal")
        if self.outcome_kind is not expected_kind:
            raise ValueError("assessment outcome kind does not match disposition")
        if outcome is not None:
            if outcome.source_binding_digest != self.source_binding_digest:
                raise ValueError("proposal source binding does not match record")
            if outcome.relevance_assessment_id != self.assessment.assessment_id:
                raise ValueError("proposal assessment id does not match record")
            if (
                outcome.tenant_id != self.tenant_id
                or outcome.workspace_id != self.workspace_id
            ):
                raise ValueError("proposal scope does not match record")
        return self
