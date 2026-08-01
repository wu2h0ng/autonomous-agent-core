from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime, content_digest
from .evidence import Sha256Digest
from .outcome import OutcomeStatus
from .srl_help import HelpClass, SrlHelpRequest, SrlHelpResponse, SrlHelpResponseKind


class PersistentCommitmentState(str, Enum):
    OPEN = "OPEN"
    SETTLED_MET = "SETTLED_MET"
    SETTLED_NOT_MET = "SETTLED_NOT_MET"
    INVALID = "INVALID"
    REVOKED = "REVOKED"


def _require_exact_false(value: Any) -> Literal[False]:
    if value is not False:
        raise ValueError("outcome portfolio cannot grant execution authority")
    return False


class OutcomePortfolioCreateCommand(ContractModel):
    reason: NonEmptyStr | None = None
    authority_credential_digest: Sha256Digest | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class OutcomePortfolio(ContractModel):
    portfolio_id: NonEmptyStr
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    mandate_id: NonEmptyStr
    desired_outcomes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    workspace_record_digest: Sha256Digest
    operational_mandate_ref_digest: Sha256Digest
    correction_epoch: int = Field(ge=0)
    created_by: NonEmptyStr
    created_at: UtcDateTime
    reason: NonEmptyStr | None = None
    authority_credential_digest: Sha256Digest | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    command_digest: Sha256Digest
    record_digest: Sha256Digest
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
    def _false_flags(cls, value: Any) -> Literal[False]:
        return _require_exact_false(value)

    @field_validator("desired_outcomes", mode="after")
    @classmethod
    def _normalize_desired(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class PersistentCommitmentAttachCommand(ContractModel):
    task_id: NonEmptyStr
    commitment_digest: Sha256Digest
    expected_outcome_digest: Sha256Digest
    reason: NonEmptyStr | None = None


class PersistentCommitment(ContractModel):
    commitment_record_id: NonEmptyStr
    portfolio_id: NonEmptyStr
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    mandate_id: NonEmptyStr
    task_id: NonEmptyStr
    commitment_digest: Sha256Digest
    expected_outcome_digest: Sha256Digest
    state: PersistentCommitmentState
    workspace_record_digest: Sha256Digest
    operational_mandate_ref_digest: Sha256Digest
    correction_epoch: int = Field(ge=0)
    attached_by: NonEmptyStr
    attached_at: UtcDateTime
    reason: NonEmptyStr | None = None
    command_digest: Sha256Digest
    record_digest: Sha256Digest
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
    def _false_flags(cls, value: Any) -> Literal[False]:
        return _require_exact_false(value)


class SettlementCommand(ContractModel):
    commitment_record_id: NonEmptyStr
    expected_outcome_digest: Sha256Digest
    observed_outcome_digest: Sha256Digest
    observed_status: OutcomeStatus
    reason: NonEmptyStr | None = None


class SettlementRecord(ContractModel):
    settlement_id: NonEmptyStr
    commitment_record_id: NonEmptyStr
    portfolio_id: NonEmptyStr
    mandate_id: NonEmptyStr
    task_id: NonEmptyStr
    expected_outcome_digest: Sha256Digest
    observed_outcome_digest: Sha256Digest
    observed_status: OutcomeStatus
    resulting_state: PersistentCommitmentState
    settled_by: NonEmptyStr
    settled_at: UtcDateTime
    command_digest: Sha256Digest
    record_digest: Sha256Digest
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
    def _false_flags(cls, value: Any) -> Literal[False]:
        return _require_exact_false(value)


class OutcomePortfolioHelpGap(str, Enum):
    """Portfolio-local gap classifier; maps into canonical SrlHelpRequest.help_class."""

    MISSING_OBSERVED_OUTCOME = "MISSING_OBSERVED_OUTCOME"
    PENDING_ACTION_APPROVAL = "PENDING_ACTION_APPROVAL"
    MISSING_TASK_LINK = "MISSING_TASK_LINK"
    REVOKED_TASK_LINK = "REVOKED_TASK_LINK"
    DIGEST_DRIFT = "DIGEST_DRIFT"
    CORRECTION_EPOCH_DRIFT = "CORRECTION_EPOCH_DRIFT"
    MISSING_COMMITMENT_OR_EXPECTED = "MISSING_COMMITMENT_OR_EXPECTED"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"


_GAP_TO_HELP_CLASS: dict[OutcomePortfolioHelpGap, HelpClass] = {
    OutcomePortfolioHelpGap.MISSING_OBSERVED_OUTCOME: HelpClass.INFORMATION,
    OutcomePortfolioHelpGap.PENDING_ACTION_APPROVAL: HelpClass.PERMISSION,
    OutcomePortfolioHelpGap.MISSING_COMMITMENT_OR_EXPECTED: HelpClass.INFORMATION,
    OutcomePortfolioHelpGap.MISSING_TASK_LINK: HelpClass.PERMISSION,
    OutcomePortfolioHelpGap.REVOKED_TASK_LINK: HelpClass.PERMISSION,
    OutcomePortfolioHelpGap.DIGEST_DRIFT: HelpClass.AUTHORITY_CONFLICT,
    OutcomePortfolioHelpGap.CORRECTION_EPOCH_DRIFT: HelpClass.AUTHORITY_CONFLICT,
    OutcomePortfolioHelpGap.SCOPE_MISMATCH: HelpClass.AUTHORITY_CONFLICT,
}


def help_class_for_gap(gap_kind: OutcomePortfolioHelpGap) -> HelpClass:
    return _GAP_TO_HELP_CLASS[gap_kind]


class OutcomePortfolioHelpRespondCommand(ContractModel):
    """Admin respond body; server binds help_request_id, responder, and timestamp."""

    response_kind: SrlHelpResponseKind
    decision: Literal["APPROVE", "REJECT", "MORE_INFO"] | None = None
    notes: NonEmptyStr | None = None


class OutcomePortfolioHelpRequest(ContractModel):
    """Portfolio binding over the canonical SrlHelpRequest — not a second help taxonomy."""

    portfolio_id: NonEmptyStr
    task_id: NonEmptyStr | None = None
    gap_kind: OutcomePortfolioHelpGap
    srl_help: SrlHelpRequest
    response: SrlHelpResponse | None = None
    authority_granted: Literal[False] = False
    external_effects_authorized: Literal[False] = False
    task_activation_authorized: Literal[False] = False
    capability_grant_authorized: Literal[False] = False

    @field_validator(
        "authority_granted",
        "external_effects_authorized",
        "task_activation_authorized",
        "capability_grant_authorized",
        mode="before",
    )
    @classmethod
    def _false_flags(cls, value: Any) -> Literal[False]:
        return _require_exact_false(value)

    @property
    def help_request_id(self) -> str:
        return self.srl_help.help_request_id

    @property
    def mandate_id(self) -> str:
        return self.srl_help.mandate_id

    @property
    def is_open(self) -> bool:
        return self.response is None


def _outcome_portfolio_help_request_id(
    mandate_id: str,
    portfolio_id: str,
    task_id: str | None,
    gap_kind: OutcomePortfolioHelpGap,
    details: str,
    created_by: str,
    created_at: UtcDateTime,
) -> str:
    return "help-request:" + content_digest(
        {
            "mandate_id": mandate_id,
            "portfolio_id": portfolio_id,
            "task_id": task_id,
            "gap_kind": gap_kind.value,
            "details": details,
            "created_by": created_by,
            "created_at": created_at.isoformat(),
        }
    )


class OutcomePortfolioView(ContractModel):
    portfolio: OutcomePortfolio
    commitments: tuple[PersistentCommitment, ...] = ()
    settlements: tuple[SettlementRecord, ...] = ()
    help_requests: tuple[OutcomePortfolioHelpRequest, ...] = ()
