from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field

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


class HelpRequest(ContractModel):
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
