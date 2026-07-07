from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
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
    def save(self, record: ApprovalRecord, *, tenant_id: str = "default") -> ApprovalRecord:
        """Persist (insert or replace by ``approval_id``) and return the record."""
        ...

    @abstractmethod
    def get(self, approval_id: str, *, tenant_id: str = "default") -> ApprovalRecord | None:
        """Return the record for ``approval_id``, or ``None`` if absent."""
        ...

    @abstractmethod
    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        tenant_id: str = "default",
    ) -> tuple[ApprovalRecord, ...]:
        """Return a paginated list of approval records, optionally filtered by status."""
        ...


class ApprovalContextStorePort(ABC):
    """Persistence port for approval-bound operation contexts.

    The approval record stores the decision lifecycle; this context stores the
    exact operation/evidence/action payload captured at proposal time, so a
    later process can execute by approval_id without client replay.
    """

    @abstractmethod
    def save(
        self, context: ApprovalOperationContext, *, tenant_id: str = "default"
    ) -> ApprovalOperationContext:
        """Persist or replace a context by ``approval_id`` and return it."""
        ...

    @abstractmethod
    def get(
        self, approval_id: str, *, tenant_id: str = "default"
    ) -> ApprovalOperationContext | None:
        """Return the context for ``approval_id``, or ``None`` if absent."""
        ...

    @abstractmethod
    def claim(
        self,
        approval_id: str,
        *,
        reclaim_stale_after_seconds: float | None = None,
        tenant_id: str = "default",
    ) -> ApprovalOperationContext | None:
        """Atomically mark a pending context as executing and return it.

        When ``reclaim_stale_after_seconds`` is provided, durable stores may
        reclaim an already-executing context only if its claim lease is older
        than that age. This is crash recovery for abandoned claims, not a
        distributed exactly-once guarantee.
        """
        ...

    @abstractmethod
    def release_claim(self, approval_id: str, *, tenant_id: str = "default") -> None:
        """Return an executing context to pending so the approval can be retried."""
        ...

    @abstractmethod
    def delete(self, approval_id: str, *, tenant_id: str = "default") -> None:
        """Remove the context for ``approval_id`` if present."""
        ...


class InMemoryApprovalStore(ApprovalStorePort):
    """In-memory :class:`ApprovalStorePort` backed by a dict keyed on approval_id."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, ApprovalRecord]] = {}

    def _tenant_records(self, tenant_id: str) -> dict[str, ApprovalRecord]:
        return self._records.setdefault(tenant_id, {})

    def save(self, record: ApprovalRecord, *, tenant_id: str = "default") -> ApprovalRecord:
        self._tenant_records(tenant_id)[record.approval_id] = record
        return record

    def get(self, approval_id: str, *, tenant_id: str = "default") -> ApprovalRecord | None:
        return self._tenant_records(tenant_id).get(approval_id)

    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        tenant_id: str = "default",
    ) -> tuple[ApprovalRecord, ...]:
        records = list(self._tenant_records(tenant_id).values())
        if status is not None:
            records = [r for r in records if r.status == status]
        records = sorted(records, key=lambda r: r.approval_id)
        return tuple(records[offset : offset + limit])


class InMemoryApprovalContextStore(ApprovalContextStorePort):
    """In-memory approval-context store keyed by approval_id."""

    def __init__(self) -> None:
        self._contexts: dict[str, dict[str, ApprovalOperationContext]] = {}
        self._statuses: dict[str, dict[str, str]] = {}
        self._claimed_at: dict[str, dict[str, datetime]] = {}

    def _tenant_maps(
        self, tenant_id: str
    ) -> tuple[
        dict[str, ApprovalOperationContext],
        dict[str, str],
        dict[str, datetime],
    ]:
        return (
            self._contexts.setdefault(tenant_id, {}),
            self._statuses.setdefault(tenant_id, {}),
            self._claimed_at.setdefault(tenant_id, {}),
        )

    def save(
        self, context: ApprovalOperationContext, *, tenant_id: str = "default"
    ) -> ApprovalOperationContext:
        contexts, statuses, _ = self._tenant_maps(tenant_id)
        contexts[context.approval_id] = context
        statuses[context.approval_id] = "pending"
        return context

    def get(
        self, approval_id: str, *, tenant_id: str = "default"
    ) -> ApprovalOperationContext | None:
        contexts, _, _ = self._tenant_maps(tenant_id)
        return contexts.get(approval_id)

    def claim(
        self,
        approval_id: str,
        *,
        reclaim_stale_after_seconds: float | None = None,
        tenant_id: str = "default",
    ) -> ApprovalOperationContext | None:
        contexts, statuses, claimed_at = self._tenant_maps(tenant_id)
        status = statuses.get(approval_id)
        if status == "executing" and reclaim_stale_after_seconds is not None:
            claimed_at_dt = claimed_at.get(approval_id)
            if claimed_at_dt is None:
                return None
            elapsed = (datetime.now(timezone.utc) - claimed_at_dt).total_seconds()
            if elapsed < reclaim_stale_after_seconds:
                return None
        elif status != "pending":
            return None
        context = contexts.get(approval_id)
        if context is None:
            return None
        statuses[approval_id] = "executing"
        claimed_at[approval_id] = datetime.now(timezone.utc)
        return context

    def release_claim(self, approval_id: str, *, tenant_id: str = "default") -> None:
        _, statuses, claimed_at = self._tenant_maps(tenant_id)
        if statuses.get(approval_id) == "executing":
            statuses[approval_id] = "pending"
            claimed_at.pop(approval_id, None)

    def delete(self, approval_id: str, *, tenant_id: str = "default") -> None:
        contexts, statuses, claimed_at = self._tenant_maps(tenant_id)
        contexts.pop(approval_id, None)
        statuses.pop(approval_id, None)
        claimed_at.pop(approval_id, None)


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
        tenant_id: str = "default",
    ) -> ApprovalRecord:
        """Create a new pending approval record.

        Args:
            approval_id: Unique identifier for this approval.
            proposal_id: The proposal this approval relates to.
            approver_role: The role required to approve (may be None).
            operation_fingerprint: Optional frozen digest of the approved operation
                contract and action parameters.
            tenant_id: Tenant scope for the record.

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
        return self._store.save(record, tenant_id=tenant_id)

    def approve(
        self,
        approval_id: str,
        reason: str | None = None,
        approved_by: str | None = None,
        *,
        tenant_id: str = "default",
    ) -> ApprovalRecord:
        """Approve a pending approval record.

        Args:
            approval_id: The ID of the approval to approve.
            reason: Optional reason for the approval.
            approved_by: Optional operator/user identifier for audit.
            tenant_id: Tenant scope for the record.

        Returns:
            A new ApprovalRecord with status "approved".

        Raises:
            KeyError: If no record with the given ID exists.
            ValueError: If the record is not in "pending" status.
        """
        existing = self._store.get(approval_id, tenant_id=tenant_id)
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
        return self._store.save(updated, tenant_id=tenant_id)

    def reject(
        self,
        approval_id: str,
        reason: str | None = None,
        *,
        tenant_id: str = "default",
    ) -> ApprovalRecord:
        """Reject a pending approval record.

        Args:
            approval_id: The ID of the approval to reject.
            reason: Optional reason for the rejection.
            tenant_id: Tenant scope for the record.

        Returns:
            A new ApprovalRecord with status "rejected".

        Raises:
            KeyError: If no record with the given ID exists.
            ValueError: If the record is not in "pending" status.
        """
        existing = self._store.get(approval_id, tenant_id=tenant_id)
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
        return self._store.save(updated, tenant_id=tenant_id)

    def get(self, approval_id: str, *, tenant_id: str = "default") -> ApprovalRecord:
        """Retrieve an approval record by ID.

        Args:
            approval_id: The unique ID of the approval.
            tenant_id: Tenant scope for the record.

        Returns:
            The ApprovalRecord.

        Raises:
            KeyError: If no record with the given ID exists.
        """
        record = self._store.get(approval_id, tenant_id=tenant_id)
        if record is None:
            raise KeyError(f"No approval record found with id '{approval_id}'")
        return record

    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        tenant_id: str = "default",
    ) -> tuple[ApprovalRecord, ...]:
        """List approval records from the store.

        Args:
            status: Optional status filter ("pending", "approved", "rejected").
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            tenant_id: Tenant scope for the records.

        Returns:
            A tuple of matching ApprovalRecord instances.
        """
        return self._store.list(status=status, limit=limit, offset=offset, tenant_id=tenant_id)
