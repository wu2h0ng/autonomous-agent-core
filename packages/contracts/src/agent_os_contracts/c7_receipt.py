from __future__ import annotations

from typing import Any

from pydantic import model_validator

from .authority import CorrectionEpochVector
from .common import ContractModel, NonEmptyStr, UtcDateTime, content_digest


class C7ClearanceReceipt(ContractModel):
    """Contract-layer manifestation of the external C7 correction authority.

    A receipt is a point-in-time, digest-bound record of the externally owned
    correction state for one ``(task, run, capability)`` scope: the correction
    epoch vector and the halt flag observed from the authority. Its digest binds
    every field, so a persisted receipt that is mutated no longer validates.

    The receipt is an audit artifact and a pre-commit linearization token. It
    does NOT interrupt an effect that was already dispatched; it only authorizes
    or blocks commits made after it is verified. Worker/process compromise is NOT
    isolated by this receipt (see the C7 boundary statement).
    """

    receipt_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    capability_id: NonEmptyStr
    correction_epochs: CorrectionEpochVector
    halted: bool
    issued_by: NonEmptyStr
    issued_at: UtcDateTime
    receipt_digest: NonEmptyStr

    @staticmethod
    def compute_digest(
        *,
        receipt_id: str,
        tenant_id: str,
        workspace_id: str,
        task_id: str,
        run_id: str,
        capability_id: str,
        correction_epochs: CorrectionEpochVector,
        halted: bool,
        issued_by: str,
        issued_at: UtcDateTime,
    ) -> str:
        payload: dict[str, Any] = {
            "receipt_id": receipt_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "task_id": task_id,
            "run_id": run_id,
            "capability_id": capability_id,
            "correction_epochs": correction_epochs.model_dump(mode="json"),
            "halted": halted,
            "issued_by": issued_by,
            "issued_at": issued_at.isoformat(),
        }
        return content_digest(payload)

    @model_validator(mode="after")
    def _digest_binds_fields(self) -> "C7ClearanceReceipt":
        expected = self.compute_digest(
            receipt_id=self.receipt_id,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            task_id=self.task_id,
            run_id=self.run_id,
            capability_id=self.capability_id,
            correction_epochs=self.correction_epochs,
            halted=self.halted,
            issued_by=self.issued_by,
            issued_at=self.issued_at,
        )
        if self.receipt_digest != expected:
            raise ValueError(
                "C7 clearance receipt digest does not bind its fields"
            )
        return self
