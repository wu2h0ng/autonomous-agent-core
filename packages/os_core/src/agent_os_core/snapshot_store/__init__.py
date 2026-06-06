from __future__ import annotations

from abc import ABC, abstractmethod

from agent_os_contracts import StateSnapshot

__all__ = [
    "SnapshotStore",
    "InMemorySnapshotStore",
]


class SnapshotStore(ABC):
    """Persistence boundary for L3 pre-execution state snapshots.

    A snapshot captures enough connector-side state to roll back a governed
    write operation. The store is domain-independent: it persists opaque
    :class:`StateSnapshot` records keyed by ``snapshot_id`` and indexed by
    ``operation_id``, and never interprets ``state_payload``.
    """

    @abstractmethod
    def save(self, snapshot: StateSnapshot) -> StateSnapshot:
        """Persist a snapshot and return it.

        Args:
            snapshot: The snapshot to persist.

        Returns:
            The persisted snapshot.
        """
        ...

    @abstractmethod
    def get(self, snapshot_id: str) -> StateSnapshot | None:
        """Retrieve a snapshot by id.

        Args:
            snapshot_id: The unique snapshot identifier.

        Returns:
            The snapshot, or ``None`` if no snapshot with that id exists.
        """
        ...

    @abstractmethod
    def list_for_operation(self, operation_id: str) -> tuple[StateSnapshot, ...]:
        """List all snapshots captured for a given operation.

        Args:
            operation_id: The operation the snapshots belong to.

        Returns:
            A tuple of snapshots (possibly empty), in insertion order.
        """
        ...


class InMemorySnapshotStore(SnapshotStore):
    """In-memory :class:`SnapshotStore` backed by a dict keyed on snapshot_id."""

    def __init__(self) -> None:
        self._by_id: dict[str, StateSnapshot] = {}

    def save(self, snapshot: StateSnapshot) -> StateSnapshot:
        self._by_id[snapshot.snapshot_id] = snapshot
        return snapshot

    def get(self, snapshot_id: str) -> StateSnapshot | None:
        return self._by_id.get(snapshot_id)

    def list_for_operation(self, operation_id: str) -> tuple[StateSnapshot, ...]:
        return tuple(
            snapshot
            for snapshot in self._by_id.values()
            if snapshot.operation_id == operation_id
        )
