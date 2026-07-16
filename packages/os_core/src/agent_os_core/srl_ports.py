from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from agent_os_contracts import (
    EnvironmentBinding,
    HelpBurdenReceipt,
    Mandate,
    MandateRatificationReceipt,
    MandateStatus,
    ObservedOutcome,
    ProposedGoal,
    SrlEnvironmentEvent,
    SrlHelpRequest,
    SrlHelpResponse,
    SrlRelevanceAssessment,
    StandingMission,
    content_digest,
)
from agent_os_contracts.common import ContractModel, NonEmptyStr, UtcDateTime


SrlResultClass: Literal[
    "IGNORE",
    "OBSERVE",
    "INVESTIGATE",
    "PROPOSED_GOAL",
    "HELP",
    "BUDGET_HALT",
] = "IGNORE"  # type: ignore[assignment]


class SrlEvaluationResult(ContractModel):
    """Bounded outcome of evaluating a single environment event."""

    result_class: Literal[
        "IGNORE",
        "OBSERVE",
        "INVESTIGATE",
        "PROPOSED_GOAL",
        "HELP",
        "BUDGET_HALT",
    ]
    event_id: NonEmptyStr
    assessment_id: NonEmptyStr | None = None
    goal_id: NonEmptyStr | None = None
    help_request_id: NonEmptyStr | None = None
    halt_reason: NonEmptyStr | None = None


class TaskActivationResult(ContractModel):
    """Outcome of attempting to activate a ProposedGoal into a Task."""

    activated: bool
    task_id: NonEmptyStr | None = None
    rejection_reason: NonEmptyStr | None = None


class HelpDispatchResult(ContractModel):
    """Outcome of emitting or resolving an SrlHelpRequest."""

    emitted: bool = False
    resolved: bool = False
    help_request_id: NonEmptyStr
    burden_receipt: HelpBurdenReceipt | None = None
    rejection_reason: NonEmptyStr | None = None


class OutcomeAcceptanceResult(ContractModel):
    """Outcome of attempting to accept a trusted outcome record."""

    accepted: bool
    rejection_reason: NonEmptyStr | None = None


class ActivationAuthority(ContractModel):
    """External authority record required to promote a ProposedGoal to a Task."""

    authority_id: NonEmptyStr
    mandate_id: NonEmptyStr
    standing_mission_id: NonEmptyStr
    authority_instance_id: NonEmptyStr
    source_assessment_id: NonEmptyStr
    source_proposed_goal_id: NonEmptyStr
    authorization_digest: NonEmptyStr
    authorized_at: UtcDateTime


class TrustedOutcomeRecord(ContractModel):
    """Outcome record signed by the trusted evaluator registry."""

    record_id: NonEmptyStr
    mandate_id: NonEmptyStr
    standing_mission_id: NonEmptyStr
    task_id: NonEmptyStr
    observed_outcome: ObservedOutcome
    evaluator_registry_instance_id: NonEmptyStr
    registry_signature_digest: NonEmptyStr
    recorded_at: UtcDateTime


class AuditTransition(ContractModel):
    """Non-erasable record of a Runtime state transition."""

    transition_class: NonEmptyStr
    from_state: NonEmptyStr
    to_state: NonEmptyStr
    transition_digest: NonEmptyStr
    timestamp: UtcDateTime
    authority_instance_id: NonEmptyStr
    provenance: tuple[NonEmptyStr, ...] = ()


class EventLedgerReceipt(ContractModel):
    """Receipt returned by EventLedgerPort.append."""

    event_id: NonEmptyStr
    binding_id: NonEmptyStr
    dedupe_key: NonEmptyStr
    status: Literal["APPENDED", "DUPLICATE", "REJECTED"]


class BudgetStatus(ContractModel):
    """Per-binding budget snapshot returned by BudgetEnforcementPort."""

    binding_id: NonEmptyStr
    status: Literal["WITHIN_BUDGET", "EXHAUSTED", "HALTED"]
    remaining_wake: int
    remaining_query: int


class EventLedgerPort(Protocol):
    """Immutable, deduplicated event ledger."""

    def append(self, event: SrlEnvironmentEvent) -> EventLedgerReceipt: ...

    def get(self, binding_id: str, dedupe_key: str) -> SrlEnvironmentEvent | None: ...

    def list_events(self, binding_id: str) -> tuple[SrlEnvironmentEvent, ...]: ...


class MandateRegistryPort(Protocol):
    """Ratified Mandate and StandingMission versions."""

    def current_ratified_mission(self, mandate_id: str) -> StandingMission: ...

    def ratify_mandate(
        self, mandate: Mandate, receipt: MandateRatificationReceipt
    ) -> None: ...

    def get_mandate(self, mandate_id: str) -> Mandate: ...

    def expected_assessor_policy_digest(self, mandate_id: str) -> str: ...


class AssessorPort(Protocol):
    """Policy-bound relevance assessment; proposal only."""

    def assess(
        self, event: SrlEnvironmentEvent, mission: StandingMission
    ) -> SrlRelevanceAssessment: ...


class GoalFormationPort(Protocol):
    """Turn an INVESTIGATE/CREATE_TASK assessment into a ProposedGoal."""

    def form_goal(
        self, assessment: SrlRelevanceAssessment, mission: StandingMission
    ) -> ProposedGoal: ...


class BudgetEnforcementPort(Protocol):
    """Wake/query/help budgets."""

    def check_binding_budget(self, binding: EnvironmentBinding) -> BudgetStatus: ...

    def charge_help(self, help_request: SrlHelpRequest) -> HelpBurdenReceipt: ...


class HelpDispatchPort(Protocol):
    """SrlHelpRequest lifecycle."""

    def emit(self, help_request: SrlHelpRequest) -> HelpDispatchResult: ...

    def resolve(self, response: SrlHelpResponse) -> HelpDispatchResult: ...


class TaskActivationPort(Protocol):
    """Existing TaskService wrapper; consumes existing authority spine only."""

    def activate(
        self, proposed_goal: ProposedGoal, authority: ActivationAuthority
    ) -> TaskActivationResult: ...


class OutcomeAcceptorPort(Protocol):
    """Consume trusted evaluator output."""

    def accept(
        self, outcome_record: TrustedOutcomeRecord
    ) -> OutcomeAcceptanceResult: ...


class AuditPort(Protocol):
    """Non-erasable transition records."""

    def record(self, transition: AuditTransition) -> None: ...

    def transitions(self) -> tuple[AuditTransition, ...]: ...


def mandate_is_active(mandate: Mandate, now: datetime) -> bool:
    """Return True only when the Mandate is ratified/active and unexpired."""
    return (
        mandate.status in {MandateStatus.RATIFIED, MandateStatus.ACTIVE}
        and now < mandate.expires_at
    )


def compute_assessment_digest(assessment: SrlRelevanceAssessment) -> str:
    """Canonical digest of an assessment for authority references."""
    return content_digest(assessment)
