from __future__ import annotations

from agent_os_contracts import ProposedGoal

from .srl_ports import ActivationAuthority, TaskActivationPort, TaskActivationResult


class InMemoryTaskActivation(TaskActivationPort):
    """Fail-closed M0 stub with no TaskService or C7 authority integration."""

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
        if self._allow_activation:
            return TaskActivationResult(
                activated=False,
                rejection_reason=(
                    "allow_activation cannot replace trusted TaskService/C7 "
                    "authority in M0"
                ),
            )
        return TaskActivationResult(
            activated=False,
            rejection_reason="no trusted TaskService/C7 activation authority in M0",
        )
