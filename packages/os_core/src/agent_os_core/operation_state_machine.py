from __future__ import annotations

from agent_os_contracts import OperationState


class InvalidStateTransition(Exception):
    """Raised when an operation state transition is not allowed."""

    def __init__(
        self,
        current: OperationState,
        target: OperationState,
        message: str | None = None,
    ) -> None:
        self.current = current
        self.target = target
        self.message = message or f"Invalid state transition: {current.value} -> {target.value}"
        super().__init__(self.message)


class OperationStateMachine:
    """State machine governing the lifecycle of an operation.

    Validates that state transitions follow the allowed transition table.
    Terminal states (REJECTED, OBSERVED, FAILED) have no outgoing transitions.
    """

    def __init__(self) -> None:
        self._transitions: dict[OperationState, frozenset[OperationState]] = {
            OperationState.PROPOSED: frozenset(
                {
                    OperationState.AWAITING_APPROVAL,
                    OperationState.APPROVED,
                    OperationState.REJECTED,
                    OperationState.POLICY_EVALUATED,
                }
            ),
            OperationState.POLICY_EVALUATED: frozenset(
                {
                    OperationState.POLICY_PRE_APPROVED,
                    OperationState.AWAITING_APPROVAL,
                    OperationState.REJECTED,
                }
            ),
            OperationState.POLICY_PRE_APPROVED: frozenset(
                {
                    OperationState.SNAPSHOTTING,
                    OperationState.EXECUTED,
                    OperationState.REJECTED,
                }
            ),
            OperationState.AWAITING_APPROVAL: frozenset(
                {
                    OperationState.APPROVED,
                    OperationState.REJECTED,
                }
            ),
            OperationState.APPROVED: frozenset(
                {
                    OperationState.SNAPSHOTTING,
                    OperationState.EXECUTED,
                }
            ),
            OperationState.SNAPSHOTTING: frozenset(
                {
                    OperationState.EXECUTED,
                    OperationState.FAILED,
                }
            ),
            OperationState.EXECUTED: frozenset(
                {
                    OperationState.OBSERVED,
                    OperationState.FAILED,
                    OperationState.ROLLING_BACK,
                    OperationState.COMPENSATING,
                }
            ),
            OperationState.ROLLING_BACK: frozenset(
                {
                    OperationState.ROLLED_BACK,
                    OperationState.FAILED,
                }
            ),
            OperationState.ROLLED_BACK: frozenset(
                {
                    OperationState.OBSERVED,
                }
            ),
            OperationState.COMPENSATING: frozenset(
                {
                    OperationState.OBSERVED,
                    OperationState.FAILED,
                }
            ),
            OperationState.REJECTED: frozenset(),
            OperationState.OBSERVED: frozenset(),
            OperationState.FAILED: frozenset(),
        }

    def transition(self, current: OperationState, target: OperationState) -> OperationState:
        """Validate and perform a state transition.

        Args:
            current: The current state of the operation.
            target: The desired target state.

        Returns:
            The target state if the transition is valid.

        Raises:
            InvalidStateTransition: If the transition is not allowed.
        """
        allowed = self._transitions.get(current, frozenset())
        if target not in allowed:
            raise InvalidStateTransition(current, target)
        return target

    def allowed_transitions(self, current: OperationState) -> tuple[OperationState, ...]:
        """Return the set of states that can be reached from the current state.

        Args:
            current: The current state.

        Returns:
            A tuple of allowed target states.
        """
        return tuple(self._transitions.get(current, frozenset()))
