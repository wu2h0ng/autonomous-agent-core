from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from agent_os_contracts import EvidenceChain, OperationContract


@dataclass(frozen=True)
class ApprovalRecord:
    """Immutable record of an approval decision."""

    approval_id: str
    proposal_id: str
    status: str  # "pending" | "approved" | "rejected"
    approver_role: str | None
    reason: str | None = None
    operation_fingerprint: str | None = None
    approved_by: str | None = None


@dataclass(frozen=True)
class ApprovalOperationContext:
    """Frozen operation context needed to resume an approved action by approval id."""

    approval_id: str
    proposal_id: str
    operation: OperationContract
    action_parameters: dict[str, Any]
    evidence_chain: EvidenceChain


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


class ApprovalContextStorePort(ABC):
    """Persistence port for approval-bound operation contexts.

    The approval record stores the decision lifecycle; this context stores the
    exact operation/evidence/action payload captured at proposal time, so a
    later process can execute by approval_id without client replay.
    """

    @abstractmethod
    def save(self, context: ApprovalOperationContext) -> ApprovalOperationContext:
        """Persist or replace a context by ``approval_id`` and return it."""
        ...

    @abstractmethod
    def get(self, approval_id: str) -> ApprovalOperationContext | None:
        """Return the context for ``approval_id``, or ``None`` if absent."""
        ...

    @abstractmethod
    def claim(self, approval_id: str) -> ApprovalOperationContext | None:
        """Atomically mark a pending context as executing and return it."""
        ...

    @abstractmethod
    def release_claim(self, approval_id: str) -> None:
        """Return an executing context to pending so the approval can be retried."""
        ...

    @abstractmethod
    def delete(self, approval_id: str) -> None:
        """Remove the context for ``approval_id`` if present."""
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


class InMemoryApprovalContextStore(ApprovalContextStorePort):
    """In-memory approval-context store keyed by approval_id."""

    def __init__(self) -> None:
        self._contexts: dict[str, ApprovalOperationContext] = {}
        self._statuses: dict[str, str] = {}

    def save(self, context: ApprovalOperationContext) -> ApprovalOperationContext:
        self._contexts[context.approval_id] = context
        self._statuses[context.approval_id] = "pending"
        return context

    def get(self, approval_id: str) -> ApprovalOperationContext | None:
        return self._contexts.get(approval_id)

    def claim(self, approval_id: str) -> ApprovalOperationContext | None:
        if self._statuses.get(approval_id) != "pending":
            return None
        context = self._contexts.get(approval_id)
        if context is None:
            return None
        self._statuses[approval_id] = "executing"
        return context

    def release_claim(self, approval_id: str) -> None:
        if self._statuses.get(approval_id) == "executing":
            self._statuses[approval_id] = "pending"

    def delete(self, approval_id: str) -> None:
        self._contexts.pop(approval_id, None)
        self._statuses.pop(approval_id, None)


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

    def approve(
        self,
        approval_id: str,
        reason: str | None = None,
        approved_by: str | None = None,
    ) -> ApprovalRecord:
        """Approve a pending approval record.

        Args:
            approval_id: The ID of the approval to approve.
            reason: Optional reason for the approval.
            approved_by: Optional operator/user identifier for audit.

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
            approved_by=approved_by,
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
