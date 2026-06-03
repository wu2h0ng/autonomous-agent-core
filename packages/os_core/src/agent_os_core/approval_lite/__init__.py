from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovalRecord:
    """Immutable record of an approval decision."""

    approval_id: str
    proposal_id: str
    status: str  # "pending" | "approved" | "rejected"
    approver_role: str | None
    reason: str | None = None


class ApprovalLiteRuntime:
    """Lightweight in-memory approval lifecycle manager.

    Supports creating pending approval records, and transitioning them to
    approved or rejected states.  Because ``ApprovalRecord`` is frozen,
    approve/reject create a new record to replace the old one.
    """

    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}

    def create_pending(
        self,
        *,
        approval_id: str,
        proposal_id: str,
        approver_role: str | None,
    ) -> ApprovalRecord:
        """Create a new pending approval record.

        Args:
            approval_id: Unique identifier for this approval.
            proposal_id: The proposal this approval relates to.
            approver_role: The role required to approve (may be None).

        Returns:
            The newly created ApprovalRecord with status "pending".
        """
        record = ApprovalRecord(
            approval_id=approval_id,
            proposal_id=proposal_id,
            status="pending",
            approver_role=approver_role,
        )
        self._records[approval_id] = record
        return record

    def approve(self, approval_id: str, reason: str | None = None) -> ApprovalRecord:
        """Approve a pending approval record.

        Args:
            approval_id: The ID of the approval to approve.
            reason: Optional reason for the approval.

        Returns:
            A new ApprovalRecord with status "approved".

        Raises:
            KeyError: If no record with the given ID exists.
            ValueError: If the record is not in "pending" status.
        """
        existing = self._records.get(approval_id)
        if existing is None:
            raise KeyError(f"No approval record found with id '{approval_id}'")
        if existing.status != "pending":
            raise ValueError(
                f"Cannot approve record '{approval_id}': "
                f"current status is '{existing.status}', expected 'pending'"
            )
        updated = ApprovalRecord(
            approval_id=existing.approval_id,
            proposal_id=existing.proposal_id,
            status="approved",
            approver_role=existing.approver_role,
            reason=reason,
        )
        self._records[approval_id] = updated
        return updated

    def reject(self, approval_id: str, reason: str | None = None) -> ApprovalRecord:
        """Reject a pending approval record.

        Args:
            approval_id: The ID of the approval to reject.
            reason: Optional reason for the rejection.

        Returns:
            A new ApprovalRecord with status "rejected".

        Raises:
            KeyError: If no record with the given ID exists.
            ValueError: If the record is not in "pending" status.
        """
        existing = self._records.get(approval_id)
        if existing is None:
            raise KeyError(f"No approval record found with id '{approval_id}'")
        if existing.status != "pending":
            raise ValueError(
                f"Cannot reject record '{approval_id}': "
                f"current status is '{existing.status}', expected 'pending'"
            )
        updated = ApprovalRecord(
            approval_id=existing.approval_id,
            proposal_id=existing.proposal_id,
            status="rejected",
            approver_role=existing.approver_role,
            reason=reason,
        )
        self._records[approval_id] = updated
        return updated

    def get(self, approval_id: str) -> ApprovalRecord:
        """Retrieve an approval record by ID.

        Args:
            approval_id: The unique ID of the approval.

        Returns:
            The ApprovalRecord.

        Raises:
            KeyError: If no record with the given ID exists.
        """
        if approval_id not in self._records:
            raise KeyError(f"No approval record found with id '{approval_id}'")
        return self._records[approval_id]
