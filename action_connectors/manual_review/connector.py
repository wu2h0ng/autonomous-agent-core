from __future__ import annotations

from typing import Any

from agent_os_contracts import OperationContract, StateSnapshot

from agent_os_core.action_connectors.base import ActionConnector


class ManualReviewConnector(ActionConnector):
    """Connector for operations that require human review before execution.

    This connector does not perform any side effects — it simply records that
    an action is pending manual approval.  In the MVP, ``execute()`` returns
    immediately with a ``pending_approval`` status rather than blocking until
    a reviewer responds.
    """

    @property
    def connector_name(self) -> str:
        """Return the unique identifier for this connector."""
        return "manual_review"

    def take_snapshot(self, operation: OperationContract) -> StateSnapshot | None:
        """Manual review has no side effects to snapshot, so returns None."""
        return None

    def dry_run(self, operation: OperationContract, parameters: dict[str, Any]) -> dict[str, Any]:
        """Preview the manual-review operation without side effects."""
        return {
            "status": "dry_run",
            "connector_name": self.connector_name,
            "operation_id": operation.operation_id,
            "action_type": operation.action_type,
            "parameters": dict(parameters),
            "idempotency_key": operation.idempotency_key,
        }

    def execute(self, operation: OperationContract, parameters: dict[str, Any]) -> dict[str, Any]:
        """Record the operation as pending manual approval.

        Args:
            operation: The operation contract describing the action.
            parameters: Action-specific parameters (unused for manual review).

        Returns:
            A dict with ``status`` set to ``pending_approval``, the assigned
            approver role, and the operation ID.
        """
        return {
            "status": "pending_approval",
            "assigned_to": operation.approval_required and "approver" or None,
            "operation_id": operation.operation_id,
        }

    def rollback(self, snapshot: StateSnapshot) -> dict[str, Any]:
        """Manual review has no side effects to roll back.

        Args:
            snapshot: The state snapshot (unused).

        Returns:
            A dict indicating rollback is not applicable.
        """
        return {
            "status": "not_applicable",
            "reason": "manual_review has no side effects to rollback",
        }

    def can_rollback(self) -> bool:
        """Manual review does not support rollback."""
        return False

    def compensating_action(self) -> str | None:
        """No compensating action for manual review."""
        return None
