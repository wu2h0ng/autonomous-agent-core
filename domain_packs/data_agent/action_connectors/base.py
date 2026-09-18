from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..domain_contracts import OperationContract, StateSnapshot


class ActionConnector(ABC):
    """Abstract base class for action connectors.

    Each connector represents a specific execution channel (e.g., manual review,
    automated API call, notification) and defines how to snapshot, execute, and
    rollback operations within that channel.
    """

    @property
    @abstractmethod
    def connector_name(self) -> str:
        """Return the unique identifier name of this connector."""
        ...

    @abstractmethod
    def take_snapshot(self, operation: OperationContract) -> StateSnapshot | None:
        """Capture a pre-execution state snapshot.

        Connectors that do not support snapshots should return None.

        Args:
            operation: The operation contract describing the planned action.

        Returns:
            A StateSnapshot if the connector supports snapshots, otherwise None.
        """
        ...

    def dry_run(self, operation: OperationContract, parameters: dict[str, Any]) -> dict[str, Any]:
        """Preview execution without mutating connector state.

        Connectors that cannot provide a real preview must fail loudly rather
        than silently treating dry-run as success.
        """
        raise NotImplementedError(f"{self.connector_name} does not support dry_run")

    @abstractmethod
    def execute(self, operation: OperationContract, parameters: dict[str, Any]) -> dict[str, Any]:
        """Execute the action described by the operation contract.

        Args:
            operation: The operation contract describing the action.
            parameters: Action-specific parameters from the proposal.

        Returns:
            A result dictionary that must contain a 'status' key.
        """
        ...

    @abstractmethod
    def rollback(self, snapshot: StateSnapshot) -> dict[str, Any]:
        """Roll back to the state captured in the snapshot.

        Args:
            snapshot: The state snapshot to roll back to.

        Returns:
            A result dictionary that must contain a 'status' key.
        """
        ...

    @abstractmethod
    def can_rollback(self) -> bool:
        """Declare whether this connector supports rollback operations."""
        ...

    @abstractmethod
    def compensating_action(self) -> str | None:
        """Return a description of the compensating action, or None if not supported."""
        ...
