from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovalRecord:
    """Immutable record of an approval decision."""

    approval_id: str
    proposal_id: str
    status: str  # "pending" | "approved" | "rejected"
    approver_role: str | None
    reason: str | None = None
    operation_fingerprint: str | None = None


class ApprovalStorePort(ABC):
    """Persistence port for approval records (storage only; lifecycle lives in the runtime).

    OS Core depends on this abstraction; concrete backends (in-memory below, or a
    PostgreSQL adapter outside OS Core) implement it. Persisting approvals is what
    lets an approval created in one process be acted on later in another.
    """

    @abstractmethod
    def save(self, record: ApprovalRecord) -> ApprovalRecord:
        """Persist (insert or replace by ``approval_id``) and return the record."""
        ...

    @abstractmethod
    def get(self, approval_id: str) -> ApprovalRecord | None:
        """Return the record for ``approval_id``, or ``None`` if absent."""
        ...


class InMemoryApprovalStore(ApprovalStorePort):
    """In-memory :class:`ApprovalStorePort` backed by a dict keyed on approval_id."""

    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}

    def save(self, record: ApprovalRecord) -> ApprovalRecord:
        self._records[record.approval_id] = record
        return record

    def get(self, approval_id: str) -> ApprovalRecord | None:
        return self._records.get(approval_id)


class ApprovalLiteRuntime:
    """Lightweight approval lifecycle manager over an injected store.

    Owns the lifecycle (pending -> approved/rejected); storage is delegated to an
    :class:`ApprovalStorePort` (in-memory by default, or a durable adapter). Because
    ``ApprovalRecord`` is frozen, approve/reject create a new record to replace the old.
    """

    def __init__(self, store: ApprovalStorePort | None = None) -> None:
        self._store: ApprovalStorePort = store or InMemoryApprovalStore()

    def create_pending(
        self,
        *,
        approval_id: str,
        proposal_id: str,
        approver_role: str | None,
        operation_fingerprint: str | None = None,
    ) -> ApprovalRecord:
        """Create a new pending approval record.

        Args:
            approval_id: Unique identifier for this approval.
            proposal_id: The proposal this approval relates to.
            approver_role: The role required to approve (may be None).
            operation_fingerprint: Optional frozen digest of the approved operation
                contract and action parameters.

        Returns:
            The newly created ApprovalRecord with status "pending".
        """
        record = ApprovalRecord(
            approval_id=approval_id,
            proposal_id=proposal_id,
            status="pending",
            approver_role=approver_role,
            operation_fingerprint=operation_fingerprint,
        )
        return self._store.save(record)

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
        existing = self._store.get(approval_id)
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
            operation_fingerprint=existing.operation_fingerprint,
        )
        return self._store.save(updated)

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
        existing = self._store.get(approval_id)
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
            operation_fingerprint=existing.operation_fingerprint,
        )
        return self._store.save(updated)

    def get(self, approval_id: str) -> ApprovalRecord:
        """Retrieve an approval record by ID.

        Args:
            approval_id: The unique ID of the approval.

        Returns:
            The ApprovalRecord.

        Raises:
            KeyError: If no record with the given ID exists.
        """
        record = self._store.get(approval_id)
        if record is None:
            raise KeyError(f"No approval record found with id '{approval_id}'")
        return record
