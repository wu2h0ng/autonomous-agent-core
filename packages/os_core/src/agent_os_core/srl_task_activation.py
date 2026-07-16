from __future__ import annotations

from agent_os_contracts import ProposedGoal

from .srl_ports import ActivationAuthority, TaskActivationPort, TaskActivationResult


class InMemoryTaskActivation(TaskActivationPort):
    """M0 TaskActivation stub: never mints authority from an SRL organ."""

    def __init__(self, *, allow_activation: bool = False) -> None:
        self._allow_activation = allow_activation
        self._activated: dict[str, tuple[ProposedGoal, ActivationAuthority]] = {}

    def activate(
        self, proposed_goal: ProposedGoal, authority: ActivationAuthority
    ) -> TaskActivationResult:
        if any(
            "capability-grant" in constraint for constraint in proposed_goal.constraints
        ):
            return TaskActivationResult(
                activated=False,
                rejection_reason="SRL organ cannot create CapabilityGrant",
            )
        if any(
            "action-permit" in constraint for constraint in proposed_goal.constraints
        ):
            return TaskActivationResult(
                activated=False,
                rejection_reason="SRL organ cannot create ActionPermit",
            )
        if any(
            "action-receipt" in constraint for constraint in proposed_goal.constraints
        ):
            return TaskActivationResult(
                activated=False,
                rejection_reason="SRL organ cannot create ActionReceipt",
            )
        if not self._allow_activation:
            return TaskActivationResult(
                activated=False,
                rejection_reason="no TaskService integration in M0",
            )
        task_id = f"task:{proposed_goal.proposal_goal_id}"
        self._activated[task_id] = (proposed_goal, authority)
        return TaskActivationResult(activated=True, task_id=task_id)
