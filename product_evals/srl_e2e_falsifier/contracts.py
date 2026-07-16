"""Arm-neutral SRL E2E falsifier contracts.

These typed contracts define the public responsibility surface for the SRL
end-to-end falsifier evaluation.  They carry no run, work, effect or training
authority.  Each public datum (mission, event, projection, evidence) enters the
state only through closed content-addressed cryptographic references.  No raw
payload, free-text public value, denylist or unrestricted mapping reaches any
state field.  Contracts bind to custody but do not self-prove the underlying
bytes; a resolver verifies the manifest separately.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Mapping

from pydantic import Field, field_validator, model_validator

from agent_os_contracts import (
    ContractModel,
    NonEmptyStr,
    Sha256Digest,
    UtcDateTime,
    content_digest,
)


class CandidateKind(str, Enum):
    WORK = "WORK"
    HELP = "HELP"
    NONE = "NONE"


class MissingInputKind(str, Enum):
    INFORMATION = "INFORMATION"
    PERMISSION = "PERMISSION"
    VALUE_TRADE_OFF = "VALUE_TRADE_OFF"
    AUTHORITY_CONFLICT = "AUTHORITY_CONFLICT"
    IRREVERSIBLE_RISK = "IRREVERSIBLE_RISK"


class PublicContentClass(str, Enum):
    ARM_NEUTRAL_PUBLIC = "ARM_NEUTRAL_PUBLIC"


class PublicContentRef(ContractModel):
    """Content-addressed reference to frozen public-content bytes."""

    content_digest: Sha256Digest
    content_class: PublicContentClass = PublicContentClass.ARM_NEUTRAL_PUBLIC
    media_type: NonEmptyStr


class PublicEventRef(ContractModel):
    """Closed content-addressed reference to a public event."""

    event_id: NonEmptyStr
    manifest_entry_digest: Sha256Digest
    content_ref: PublicContentRef


class PublicProjectionRef(ContractModel):
    """Closed content-addressed reference to a public projection."""

    projection_id: NonEmptyStr
    manifest_entry_digest: Sha256Digest
    content_ref: PublicContentRef


class PublicEvidenceRef(ContractModel):
    """Closed content-addressed reference to a public evidence entry."""

    evidence_id: NonEmptyStr
    manifest_entry_digest: Sha256Digest
    content_ref: PublicContentRef


class PublicMissionRef(ContractModel):
    """Closed content-addressed reference to a public mission statement."""

    manifest_entry_digest: Sha256Digest
    content_ref: PublicContentRef


class StaticBudgetConfiguration(ContractModel):
    """Static budget maxima only; remaining counters are BudgetFeedback."""

    max_llm_calls: int = Field(ge=0)
    max_input_tokens: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)
    max_retries: int = Field(ge=0)
    max_tool_invocations: int = Field(ge=0)
    max_wall_seconds: int = Field(ge=0)


class PublicResponsibilityState(ContractModel):
    """Structurally arm-neutral: only content-addressed refs, no raw payload."""

    state_id: NonEmptyStr
    mandate_digest: Sha256Digest
    mission_ref: PublicMissionRef
    environment_binding_digest: Sha256Digest
    correction_epoch: int = Field(ge=0)
    public_events: tuple[PublicEventRef, ...] = ()
    public_projections: tuple[PublicProjectionRef, ...] = ()
    public_evidence: tuple[PublicEvidenceRef, ...] = ()
    budget_configuration_digest: Sha256Digest

    def state_digest(self) -> str:
        return content_digest(self)


class BudgetFeedback(ContractModel):
    """Arm-neutral remaining-usage feedback; never part of public-state digest."""

    feedback_id: NonEmptyStr
    budget_configuration_digest: Sha256Digest
    remaining_llm_calls: int = Field(ge=0)
    remaining_input_tokens: int = Field(ge=0)
    remaining_output_tokens: int = Field(ge=0)
    remaining_retries: int = Field(ge=0)
    remaining_tool_invocations: int = Field(ge=0)
    remaining_wall_seconds: int = Field(ge=0)
    issued_at: UtcDateTime


def decision_candidate_digest(payload: Mapping[str, Any]) -> str:
    if "candidate_digest" in payload:
        raise ValueError(
            "candidate_digest must be excluded from its own digest payload"
        )
    return content_digest(payload)


class DecisionCandidate(ContractModel):
    """A proposal-only decision; it grants no work, effect or run authority."""

    candidate_id: NonEmptyStr
    candidate_kind: CandidateKind
    public_state_digest: Sha256Digest
    no_external_effect: Literal[True]
    desired_outcome: NonEmptyStr | None = None
    acceptance_criteria: tuple[NonEmptyStr, ...] = ()
    missing_input_kind: MissingInputKind | None = None
    minimum_question: NonEmptyStr | None = None
    created_at: UtcDateTime
    candidate_digest: Sha256Digest

    @field_validator("no_external_effect", mode="before")
    @classmethod
    def _require_exact_true(cls, value: object) -> object:
        if value is not True:
            raise ValueError("no_external_effect must be exactly True")
        return value

    @model_validator(mode="after")
    def _validate_kind_fields(self) -> DecisionCandidate:
        if self.candidate_kind is CandidateKind.WORK:
            if self.desired_outcome is None or not self.acceptance_criteria:
                raise ValueError(
                    "WORK requires desired_outcome and acceptance_criteria"
                )
            if self.missing_input_kind is not None or self.minimum_question is not None:
                raise ValueError("WORK forbids help-only fields")
        elif self.candidate_kind is CandidateKind.HELP:
            if self.missing_input_kind is None or self.minimum_question is None:
                raise ValueError(
                    "HELP requires missing_input_kind and minimum_question"
                )
            if self.desired_outcome is not None or self.acceptance_criteria:
                raise ValueError("HELP forbids work-only fields")
        else:
            if self.desired_outcome is not None or self.acceptance_criteria:
                raise ValueError("NONE forbids work-only fields")
            if self.missing_input_kind is not None or self.minimum_question is not None:
                raise ValueError("NONE forbids help-only fields")
        return self

    @model_validator(mode="after")
    def _validate_candidate_digest(self) -> DecisionCandidate:
        payload = self.model_dump(mode="json", exclude={"candidate_digest"})
        if self.candidate_digest != decision_candidate_digest(payload):
            raise ValueError(
                "candidate_digest does not match canonical candidate payload"
            )
        return self


class ControllerBindingReceipt(ContractModel):
    """Exact-binding evidence record with content digest; no authority."""

    receipt_id: NonEmptyStr
    public_state_digest: Sha256Digest
    controller_digest: Sha256Digest
    prompt_digest: Sha256Digest
    model_digest: Sha256Digest
    tool_catalog_digest: Sha256Digest
    budget_configuration_digest: Sha256Digest
    trigger_digest: Sha256Digest
    candidate_digest: Sha256Digest
    bound_at: UtcDateTime
    content_digest: Sha256Digest
    authority_granted: Literal[False] = False
    external_effects_authorized: Literal[False] = False

    @field_validator("authority_granted", "external_effects_authorized", mode="before")
    @classmethod
    def _require_exact_false(cls, value: object) -> object:
        if value is not False:
            raise ValueError(
                "binding receipt cannot grant authority or external effects"
            )
        return value

    @model_validator(mode="after")
    def _validate_receipt_integrity(self) -> ControllerBindingReceipt:
        payload = self.model_dump(
            mode="json", exclude={"receipt_id", "content_digest"}
        )
        expected_digest = content_digest(payload)
        if self.content_digest != expected_digest:
            raise ValueError(
                "content_digest does not match canonical receipt payload"
            )
        expected_receipt_id = f"controller-binding:{expected_digest}"
        if self.receipt_id != expected_receipt_id:
            raise ValueError(
                "receipt_id must be controller-binding:{content_digest}"
            )
        return self
