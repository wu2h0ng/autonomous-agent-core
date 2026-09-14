from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import uuid4

from agent_os_contracts import C7ClearanceReceipt, CorrectionEpochVector

from .errors import AgentOSCoreError


class C7ReceiptError(AgentOSCoreError):
    """Base class for C7 clearance-receipt failures. All are fail-closed."""


class C7AuthorityUnavailable(C7ReceiptError):
    """The external correction authority could not be consulted."""


class C7AuthorityHalted(C7ReceiptError):
    """The scope is halted by the C7 correction authority."""


class C7EpochReplay(C7ReceiptError):
    """The receipt's epoch vector is stale relative to the live authority."""


class C7ReceiptScopeMismatch(C7ReceiptError):
    """The receipt is not bound to the requested scope."""


class CorrectionSnapshotSource(Protocol):
    """Least-authority view of the externally owned C7 correction authority."""

    def snapshot(
        self, task_id: str, run_id: str, capability_id: str
    ) -> CorrectionEpochVector: ...

    def halted(self, task_id: str, run_id: str, capability_id: str) -> bool: ...


class C7ReceiptIssuer:
    """Issues digest-bound C7 clearance receipts from the external authority."""

    def __init__(
        self,
        authority: CorrectionSnapshotSource,
        *,
        tenant_id: str,
        workspace_id: str,
        issuer_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._authority = authority
        self._tenant_id = tenant_id
        self._workspace_id = workspace_id
        self._issuer_id = issuer_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def issue(
        self, task_id: str, run_id: str, capability_id: str
    ) -> C7ClearanceReceipt:
        try:
            epochs = self._authority.snapshot(task_id, run_id, capability_id)
            halted = self._authority.halted(task_id, run_id, capability_id)
        except Exception as exc:  # fail closed on any authority failure
            raise C7AuthorityUnavailable(str(exc)) from exc
        if halted:
            # Never issue a clearance for a halted scope.
            raise C7AuthorityHalted("scope is halted by C7")
        issued_at = self._clock()
        receipt_id = f"c7:{uuid4()}"
        digest = C7ClearanceReceipt.compute_digest(
            receipt_id=receipt_id,
            tenant_id=self._tenant_id,
            workspace_id=self._workspace_id,
            task_id=task_id,
            run_id=run_id,
            capability_id=capability_id,
            correction_epochs=epochs,
            halted=halted,
            issued_by=self._issuer_id,
            issued_at=issued_at,
        )
        return C7ClearanceReceipt(
            receipt_id=receipt_id,
            tenant_id=self._tenant_id,
            workspace_id=self._workspace_id,
            task_id=task_id,
            run_id=run_id,
            capability_id=capability_id,
            correction_epochs=epochs,
            halted=halted,
            issued_by=self._issuer_id,
            issued_at=issued_at,
            receipt_digest=digest,
        )


class C7ReceiptVerifier:
    """Verifies a C7 clearance receipt against the live external authority.

    Fail-closed: any of a missing/mismatched scope, an unavailable authority, a
    halted scope, or a stale (replayed) epoch vector raises a typed error and the
    caller must not commit. The receipt's own digest is enforced by the contract
    at construction/load, so a mutated receipt cannot even be decoded.
    """

    def __init__(self, authority: CorrectionSnapshotSource) -> None:
        self._authority = authority

    def verify(
        self,
        receipt: C7ClearanceReceipt,
        *,
        expected_task_id: str | None = None,
        expected_run_id: str | None = None,
        expected_capability_id: str | None = None,
    ) -> None:
        if expected_task_id is not None and receipt.task_id != expected_task_id:
            raise C7ReceiptScopeMismatch("receipt task scope mismatch")
        if expected_run_id is not None and receipt.run_id != expected_run_id:
            raise C7ReceiptScopeMismatch("receipt run scope mismatch")
        if (
            expected_capability_id is not None
            and receipt.capability_id != expected_capability_id
        ):
            raise C7ReceiptScopeMismatch("receipt capability scope mismatch")
        if receipt.halted:
            raise C7AuthorityHalted("receipt records a halted scope")
        try:
            current = self._authority.snapshot(
                receipt.task_id, receipt.run_id, receipt.capability_id
            )
            halted = self._authority.halted(
                receipt.task_id, receipt.run_id, receipt.capability_id
            )
        except Exception as exc:  # fail closed on any authority failure
            raise C7AuthorityUnavailable(str(exc)) from exc
        if halted:
            raise C7AuthorityHalted("scope is halted by C7")
        if current != receipt.correction_epochs:
            raise C7EpochReplay("receipt epoch vector is stale")
