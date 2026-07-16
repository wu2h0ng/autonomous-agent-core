"""Arm-neutral SRL E2E falsifier contracts.

These typed contracts define the public responsibility surface for the SRL
end-to-end falsifier evaluation.  They carry no run, work, effect or training
authority.  The public state is structurally arm-neutral: it cannot carry arm
identity, remaining budget counters, task class, plugin, expected answers,
source identity, HCW, transcripts or internal state, at any nesting depth.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Final, Literal, Mapping

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


FORBIDDEN_PUBLIC_STATE_KEY_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "arm_id",
        "arm_label",
        "remaining",
        "task_class",
        "plugin",
        "expected_answer",
        "expected_outcome",
        "source_identity",
        "hcw",
        "transcript",
        "internal_state",
    }
)


def _reject_forbidden_keys(value: object, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(
                    f"public-state mapping keys must be strings at {path}"
                )
            normalized = key.strip().lower()
            for token in FORBIDDEN_PUBLIC_STATE_KEY_TOKENS:
                if token in normalized:
                    raise ValueError(
                        f"forbidden public-state key {key!r} at {path}"
                    )
            _reject_forbidden_keys(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_forbidden_keys(item, f"{path}[{index}]")


class PublicContentRef(ContractModel):
    """Digest-only reference to public content bytes; never an authority."""

    content_digest: Sha256Digest
    media_type: NonEmptyStr


class PublicEventRecord(ContractModel):
    """Public event bytes or content ref; exactly one representation."""

    event_id: NonEmptyStr
    payload: Mapping[str, Any] | None = None
    content_ref: PublicContentRef | None = None

    @model_validator(mode="after")
    def _validate_record(self) -> PublicEventRecord:
        if (self.payload is None) == (self.content_ref is None):
            raise ValueError(
                "public event requires exactly one of payload or content_ref"
            )
        if self.payload is not None:
            _reject_forbidden_keys(self.payload, f"public_events[{self.event_id}]")
        return self


class PublicProjectionRecord(ContractModel):
    """Public projection bytes or content ref; exactly one representation."""

    projection_id: NonEmptyStr
    payload: Mapping[str, Any] | None = None
    content_ref: PublicContentRef | None = None

    @model_validator(mode="after")
    def _validate_record(self) -> PublicProjectionRecord:
        if (self.payload is None) == (self.content_ref is None):
            raise ValueError(
                "public projection requires exactly one of payload or content_ref"
            )
        if self.payload is not None:
            _reject_forbidden_keys(
                self.payload, f"public_projections[{self.projection_id}]"
            )
        return self


class StaticBudgetConfiguration(ContractModel):
    """Static budget maxima only; remaining counters are BudgetFeedback."""

    max_llm_calls: int = Field(ge=0)
    max_input_tokens: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)
    max_retries: int = Field(ge=0)
    max_tool_invocations: int = Field(ge=0)
    max_wall_seconds: int = Field(ge=0)


class PublicResponsibilityState(ContractModel):
    """The exact arm-neutral public surface a controller may condition on."""

    state_id: NonEmptyStr
    mandate_digest: Sha256Digest
    mission_statement: NonEmptyStr
    environment_binding_digest: Sha256Digest
    correction_epoch: int = Field(ge=0)
    public_events: tuple[PublicEventRecord, ...] = ()
    public_projections: tuple[PublicProjectionRecord, ...] = ()
    public_evidence_ids: tuple[NonEmptyStr, ...] = ()
    budget_configuration: StaticBudgetConfiguration

    @field_validator("public_evidence_ids", mode="after")
    @classmethod
    def _normalize_evidence_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _reject_forbidden_content(self) -> PublicResponsibilityState:
        _reject_forbidden_keys(
            self.model_dump(mode="json"), f"public_state[{self.state_id}]"
        )
        return self

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
    """Exact-binding evidence record; it grants no authority or effects."""

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
