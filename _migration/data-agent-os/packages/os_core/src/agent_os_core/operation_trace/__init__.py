from __future__ import annotations

from typing import Any

from agent_os_contracts import OperationState, OperationTrace


class OperationTraceBuilder:
    """Builder for OperationTrace instances.

    Because ``OperationTrace`` is a frozen dataclass, ``update_trace``
    returns a new instance with the updated state and appended event
    rather than mutating in place.
    """

    def open_trace(
        self,
        *,
        trace_id: str,
        proposal_id: str,
        evidence_chain_id: str,
        operation_id: str | None = None,
    ) -> OperationTrace:
        """Create an initial OperationTrace in the PROPOSED state.

        Args:
            trace_id: Unique identifier for this trace.
            proposal_id: The proposal this trace is associated with.
            evidence_chain_id: The evidence chain backing the proposal.
            operation_id: Optional operation ID.

        Returns:
            A new OperationTrace with state PROPOSED.
        """
        return OperationTrace(
            trace_id=trace_id,
            proposal_id=proposal_id,
            operation_id=operation_id,
            state=OperationState.PROPOSED,
            evidence_chain_id=evidence_chain_id,
            events=({"step": "proposed"},),
        )

    def update_trace(
        self,
        trace: OperationTrace,
        state: OperationState,
        event: dict[str, Any],
    ) -> OperationTrace:
        """Return a new OperationTrace with updated state and appended event.

        The original trace is not mutated (frozen dataclass).

        Args:
            trace: The current OperationTrace instance.
            state: The new operation state.
            event: A dictionary describing the event.

        Returns:
            A new OperationTrace with the updated state and events.
        """
        return OperationTrace(
            trace_id=trace.trace_id,
            proposal_id=trace.proposal_id,
            operation_id=trace.operation_id,
            state=state,
            evidence_chain_id=trace.evidence_chain_id,
            events=trace.events + (event,),
        )
