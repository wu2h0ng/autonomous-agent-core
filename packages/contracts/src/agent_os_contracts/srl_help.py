from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime


class HelpClass(str, Enum):
    INFORMATION = "INFORMATION"
    PERMISSION = "PERMISSION"
    VALUE_TRADE_OFF = "VALUE_TRADE_OFF"
    AUTHORITY_CONFLICT = "AUTHORITY_CONFLICT"
    IRREVERSIBLE_RISK = "IRREVERSIBLE_RISK"


class KnownFact(ContractModel):
    assertion: NonEmptyStr
    provenance_ref: NonEmptyStr
    confidence: float = Field(ge=0.0, le=1.0)


class BoundedOption(ContractModel):
    option_id: NonEmptyStr
    label: NonEmptyStr
    expected_impact: NonEmptyStr
    required_authority: tuple[NonEmptyStr, ...] = ()


class SrlHelpRequest(ContractModel):
    help_request_id: NonEmptyStr
    mandate_id: NonEmptyStr
    standing_mission_id: NonEmptyStr
    commitment_id: NonEmptyStr | None = None
    goal_id: NonEmptyStr | None = None
    help_class: HelpClass
    known_facts: tuple[KnownFact, ...] = ()
    unknowns: tuple[NonEmptyStr, ...] = ()
    acquisition_attempts: tuple[NonEmptyStr, ...] = ()
    unsafe_boundary: NonEmptyStr
    bounded_options: tuple[BoundedOption, ...] = ()
    minimum_answer: NonEmptyStr
    continuable_work: tuple[NonEmptyStr, ...] = ()
    expires_at: UtcDateTime
    cancellation_policy: NonEmptyStr
    escalation_policy: NonEmptyStr
    requested_at: UtcDateTime

    @model_validator(mode="after")
    def _validate_expiry(self) -> "SrlHelpRequest":
        if self.expires_at <= self.requested_at:
            raise ValueError("expires_at must be after requested_at")
        return self


class SrlHelpResponseKind(str, Enum):
    OPERATOR_DECISION = "OPERATOR_DECISION"
    CAPABILITY_GRANT = "CAPABILITY_GRANT"
    REVOCATION_REQUEST = "REVOCATION_REQUEST"
    CANCELLATION = "CANCELLATION"


class SrlHelpResponse(ContractModel):
    """Typed operator response to a help request; raw text is not authority."""

    help_request_id: NonEmptyStr
    responded_at: UtcDateTime
    responder_principal_id: NonEmptyStr
    response_kind: SrlHelpResponseKind
    decision: Literal["APPROVE", "REJECT", "MORE_INFO"] | None = None
    capability_grant_id: NonEmptyStr | None = None
    revocation_request_id: NonEmptyStr | None = None
    notes: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _validate_response_kind(self) -> "SrlHelpResponse":
        if self.response_kind is SrlHelpResponseKind.OPERATOR_DECISION:
            if self.decision is None:
                raise ValueError("OPERATOR_DECISION requires decision")
            if self.capability_grant_id is not None:
                raise ValueError("OPERATOR_DECISION cannot carry capability_grant_id")
            if self.revocation_request_id is not None:
                raise ValueError("OPERATOR_DECISION cannot carry revocation_request_id")
        elif self.response_kind is SrlHelpResponseKind.CAPABILITY_GRANT:
            if self.capability_grant_id is None:
                raise ValueError("CAPABILITY_GRANT requires capability_grant_id")
            if self.decision is not None:
                raise ValueError("CAPABILITY_GRANT cannot carry decision")
            if self.revocation_request_id is not None:
                raise ValueError("CAPABILITY_GRANT cannot carry revocation_request_id")
        elif self.response_kind is SrlHelpResponseKind.REVOCATION_REQUEST:
            if self.revocation_request_id is None:
                raise ValueError("REVOCATION_REQUEST requires revocation_request_id")
            if self.decision is not None:
                raise ValueError("REVOCATION_REQUEST cannot carry decision")
            if self.capability_grant_id is not None:
                raise ValueError("REVOCATION_REQUEST cannot carry capability_grant_id")
        elif self.response_kind is SrlHelpResponseKind.CANCELLATION:
            if self.decision is not None:
                raise ValueError("CANCELLATION cannot carry decision")
            if self.capability_grant_id is not None:
                raise ValueError("CANCELLATION cannot carry capability_grant_id")
            if self.revocation_request_id is not None:
                raise ValueError("CANCELLATION cannot carry revocation_request_id")
        return self


class HelpBudget(ContractModel):
    max_requests_per_window: int = Field(ge=0)
    max_operator_minutes_per_window: int = Field(ge=0)
    max_repeated_question_rate: float = Field(ge=0.0, le=1.0)
    max_unresolved_wait_seconds: int = Field(ge=0)
    window_seconds: int = Field(ge=1)


class HelpBurdenReceipt(ContractModel):
    receipt_id: NonEmptyStr
    mandate_id: NonEmptyStr
    window_start: UtcDateTime
    window_end: UtcDateTime
    request_count: int = Field(ge=0)
    operator_minutes: int = Field(ge=0)
    repeated_question_rate: float = Field(ge=0.0, le=1.0)
    longest_unresolved_wait_seconds: int = Field(ge=0)
    status: Literal["WITHIN_BUDGET", "EXCEEDED"]
