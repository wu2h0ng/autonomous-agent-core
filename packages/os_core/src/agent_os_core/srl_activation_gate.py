from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Protocol

from pydantic import Field

from agent_os_contracts import Goal, ProposedGoal, content_digest
from agent_os_contracts.common import ContractModel, NonEmptyStr, UtcDateTime

from .errors import (
    ConcurrentWriteError,
    InvalidTransitionError,
    SituationalTrustDenied,
)
from .task_service import TaskService
from .srl_ports import (
    ActivationAuthority,
    MandateRegistryPort,
    TaskActivationPort,
    TaskActivationResult,
    mandate_is_active,
)


class ActivationDenialReason(str, Enum):
    """Enumerable fail-closed reasons for refusing a Task activation."""

    TRUSTED_AUTHORITY_MISSING = "TRUSTED_AUTHORITY_MISSING"
    AUTHORITY_NOT_RECOGNIZED = "AUTHORITY_NOT_RECOGNIZED"
    AUTHORITY_BINDING_MISMATCH = "AUTHORITY_BINDING_MISMATCH"
    SAME_INSTANCE_PROPOSE_AND_ACCEPT = "SAME_INSTANCE_PROPOSE_AND_ACCEPT"
    MANDATE_UNAVAILABLE = "MANDATE_UNAVAILABLE"
    MANDATE_NOT_ACTIVE = "MANDATE_NOT_ACTIVE"
    REQUIREMENTS_MISSING = "REQUIREMENTS_MISSING"
    C7_CLEARANCE_MISSING = "C7_CLEARANCE_MISSING"
    C7_EPOCH_MISMATCH = "C7_EPOCH_MISMATCH"
    TASK_CREATION_REFUSED = "TASK_CREATION_REFUSED"
    TASK_IDENTITY_CONFLICT = "TASK_IDENTITY_CONFLICT"


class C7ClearanceRef(ContractModel):
    """Reference to an external C7 clearance; this module never writes C7 state."""

    correction_epoch: int = Field(ge=0)
    clearance_digest: NonEmptyStr
    cleared_at: UtcDateTime


class TaskRequirements(ContractModel):
    """The typed prerequisites a draft must bind before activation."""

    expected_outcome_ref: NonEmptyStr
    commitment_ref: NonEmptyStr
    capability_scope: tuple[NonEmptyStr, ...] = Field(min_length=1)


class CreatedTask(ContractModel):
    """The Task identity produced by the trusted creation port."""

    task_id: NonEmptyStr
    run_id: NonEmptyStr | None = None


class TaskActivationDecision(ContractModel):
    """Typed, replayable activation decision with an enumerable reason code."""

    activated: bool
    task_id: NonEmptyStr | None = None
    reason_code: ActivationDenialReason | None = None
    authority_instance_id: NonEmptyStr
    decided_at: UtcDateTime


class TrustedActivationAuthorityRegistry(Protocol):
    """Trusted registry that resolves authority ids; never caller-owned."""

    def resolve(self, authority_id: str) -> ActivationAuthority | None: ...


class TaskRequirementsPort(Protocol):
    """Trusted resolver of ExpectedOutcome/Commitment/capability prerequisites."""

    def resolve(
        self, proposed_goal: ProposedGoal, authority: ActivationAuthority
    ) -> TaskRequirements | None: ...


class C7ClearancePort(Protocol):
    """Read-only view of the external correction clearance; never writable here."""

    def current_clearance(self, mandate_id: str) -> C7ClearanceRef | None: ...


class TrustedTaskCreationPort(Protocol):
    """Trusted authority-spine adapter that creates the real Task; injected."""

    def create_task(
        self,
        proposed_goal: ProposedGoal,
        authority: ActivationAuthority,
        requirements: TaskRequirements,
        clearance: C7ClearanceRef,
    ) -> CreatedTask | None: ...


class TrustedTaskActivationGate(TaskActivationPort):
    """Fail-closed authority transition from a ProposedGoal to a real Task.

    The gate enforces every precondition itself and delegates only the final
    Task creation to an injected trusted adapter. It never creates a
    CapabilityGrant, ActionPermit, ActionReceipt or C7 state.
    """

    def __init__(
        self,
        *,
        authority_registry: TrustedActivationAuthorityRegistry,
        mandate_registry: MandateRegistryPort,
        requirements: TaskRequirementsPort,
        c7_clearance: C7ClearancePort,
        task_creation: TrustedTaskCreationPort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._authority_registry = authority_registry
        self._mandate_registry = mandate_registry
        self._requirements = requirements
        self._c7 = c7_clearance
        self._task_creation = task_creation
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def activate(
        self, proposed_goal: ProposedGoal, authority: ActivationAuthority
    ) -> TaskActivationResult:
        decision = self.decide(proposed_goal, authority)
        if decision.activated:
            return TaskActivationResult(activated=True, task_id=decision.task_id)
        reason = decision.reason_code.value if decision.reason_code else "REJECTED"
        return TaskActivationResult(
            activated=False, rejection_reason=f"denied:{reason}"
        )

    def decide(
        self, proposed_goal: ProposedGoal, authority: ActivationAuthority
    ) -> TaskActivationDecision:
        now = self._clock()
        rejected = self._rejected(now, authority)

        # 1. The authority must be resolved by a trusted registry, not minted.
        trusted = self._authority_registry.resolve(authority.authority_id)
        if trusted is None:
            return rejected(ActivationDenialReason.AUTHORITY_NOT_RECOGNIZED)
        if content_digest(trusted) != content_digest(authority):
            return rejected(ActivationDenialReason.AUTHORITY_NOT_RECOGNIZED)

        # 2. The authority must bind the exact proposal it claims to authorize.
        if authority.source_proposed_goal_id != proposed_goal.proposal_goal_id:
            return rejected(ActivationDenialReason.AUTHORITY_BINDING_MISMATCH)

        # 3. The producer of the assessment cannot also accept it (I-23).
        producer_instance_id = self._producer_instance_id(proposed_goal)
        if (
            producer_instance_id is not None
            and authority.authority_instance_id == producer_instance_id
        ):
            return rejected(ActivationDenialReason.SAME_INSTANCE_PROPOSE_AND_ACCEPT)

        # 4. The Mandate must be currently active and scope-matched.
        try:
            mandate = self._mandate_registry.get_mandate(authority.mandate_id)
        except SituationalTrustDenied:
            return rejected(ActivationDenialReason.MANDATE_UNAVAILABLE)
        if not mandate_is_active(mandate, now):
            return rejected(ActivationDenialReason.MANDATE_NOT_ACTIVE)
        if (
            mandate.tenant_id != proposed_goal.tenant_id
            or mandate.workspace_id != proposed_goal.workspace_id
        ):
            return rejected(ActivationDenialReason.AUTHORITY_BINDING_MISMATCH)
        try:
            mission = self._mandate_registry.current_ratified_mission(
                authority.mandate_id
            )
        except SituationalTrustDenied:
            return rejected(ActivationDenialReason.MANDATE_UNAVAILABLE)
        if authority.standing_mission_id != mission.standing_mission_id:
            return rejected(ActivationDenialReason.AUTHORITY_BINDING_MISMATCH)

        # 5. ExpectedOutcome, Commitment and capability scope must be bound.
        requirements = self._requirements.resolve(proposed_goal, authority)
        if requirements is None:
            return rejected(ActivationDenialReason.REQUIREMENTS_MISSING)

        # 6. C7 clearance must be present and epoch-matched (consume only).
        clearance = self._c7.current_clearance(authority.mandate_id)
        if clearance is None:
            return rejected(ActivationDenialReason.C7_CLEARANCE_MISSING)
        if clearance.correction_epoch != mandate.correction_epoch:
            return rejected(ActivationDenialReason.C7_EPOCH_MISMATCH)

        # 7. Only a trusted creation adapter may produce the real Task. Any
        # spine refusal (identity conflict, concurrent write) must fail closed
        # as a typed denial rather than propagate to the caller.
        try:
            created = self._task_creation.create_task(
                proposed_goal, authority, requirements, clearance
            )
        except InvalidTransitionError:
            return rejected(ActivationDenialReason.TASK_IDENTITY_CONFLICT)
        except ConcurrentWriteError:
            return rejected(ActivationDenialReason.TASK_CREATION_REFUSED)
        if created is None:
            return rejected(ActivationDenialReason.TASK_CREATION_REFUSED)
        return TaskActivationDecision(
            activated=True,
            task_id=created.task_id,
            reason_code=None,
            authority_instance_id=authority.authority_instance_id,
            decided_at=now,
        )

    def _rejected(self, now: datetime, authority: ActivationAuthority):
        def _build(reason: ActivationDenialReason) -> TaskActivationDecision:
            return TaskActivationDecision(
                activated=False,
                task_id=None,
                reason_code=reason,
                authority_instance_id=authority.authority_instance_id,
                decided_at=now,
            )

        return _build

    @staticmethod
    def _producer_instance_id(proposed_goal: ProposedGoal) -> str | None:
        for constraint in proposed_goal.constraints:
            if constraint.startswith("assessor-instance:"):
                return constraint.split(":", 1)[1]
        return None


class TaskServiceCreationAdapter:
    """TrustedTaskCreationPort over the real TaskService spine.

    Materializes a durable Task via ``TaskService.ensure_task`` keyed on the
    ProposedGoal identity. Re-activation is idempotent for an identical
    (authority, requirements, clearance) tuple; a conflicting re-activation
    raises, and the gate converts that into a typed
    ``TASK_IDENTITY_CONFLICT`` denial. It does not commit, run, grant a
    capability or execute an effect; those remain separate governed gates.
    """

    def __init__(self, task_service: TaskService) -> None:
        self._task_service = task_service

    def create_task(
        self,
        proposed_goal: ProposedGoal,
        authority: ActivationAuthority,
        requirements: TaskRequirements,
        clearance: C7ClearanceRef,
    ) -> CreatedTask | None:
        task_id = f"task:srl:{proposed_goal.proposal_goal_id}"
        goal = Goal(
            goal_id=proposed_goal.proposal_goal_id,
            tenant_id=proposed_goal.tenant_id,
            workspace_id=proposed_goal.workspace_id,
            created_by=proposed_goal.created_by,
            created_at=proposed_goal.created_at,
            statement=proposed_goal.statement,
            constraints=proposed_goal.constraints
            + (
                f"expected-outcome:{requirements.expected_outcome_ref}",
                f"commitment:{requirements.commitment_ref}",
                f"authority:{authority.authority_id}",
                f"c7-epoch:{clearance.correction_epoch}",
                f"c7-clearance-digest:{clearance.clearance_digest}",
                f"capability-scope:{','.join(requirements.capability_scope)}",
            ),
        )
        aggregate = self._task_service.ensure_task(
            task_id,
            goal,
            event_id=f"event:srl-activate:{proposed_goal.proposal_goal_id}",
            occurred_at=proposed_goal.created_at,
        )
        return CreatedTask(task_id=aggregate.task_id)
