from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from agent_os_contracts import (
    ActionContract,
    ActionPermit,
    ActionReceipt,
    CapabilitySpec,
    ReceiptStatus,
)

from .governance import CorrectionReadPort


class CapabilityDenied(PermissionError):
    pass


@dataclass(frozen=True)
class CapabilityResult:
    receipt: ActionReceipt
    output: dict[str, object]


@dataclass(frozen=True)
class CapabilityEffect:
    status: ReceiptStatus
    output: dict[str, object]
    error_code: str = "error:none"
    detail_ref: str = "detail:none"


class CapabilityPort(Protocol):
    def specs(
        self,
        now: datetime | None = None,
        *,
        include_internal: bool = False,
    ) -> Mapping[str, CapabilitySpec]:
        raise NotImplementedError

    def execute(self, action: ActionContract) -> CapabilityEffect:
        raise NotImplementedError


class CapabilityBroker:
    """The only production execution boundary for typed capability actions."""

    def __init__(self, connector: CapabilityPort, correction: CorrectionReadPort) -> None:
        self.connector = connector
        self.correction = correction

    def invoke(
        self, action: ActionContract, permit: ActionPermit, attempt: int = 1
    ) -> CapabilityResult:
        if not permit.matches(action):
            raise CapabilityDenied("broker rejected a permit/action digest mismatch")
        if permit.expires_at <= datetime.now(timezone.utc):
            raise CapabilityDenied("permit expired before capability dispatch")
        if self.correction.halted(action.task_id, action.run_id, action.capability_id):
            raise CapabilityDenied("correction authority is halted")
        current_epochs = self.correction.snapshot(
            action.task_id, action.run_id, action.capability_id
        )
        if (
            current_epochs != permit.correction_epochs
            or current_epochs != action.observed_correction_epochs
        ):
            raise CapabilityDenied("stale correction epoch")
        effect = self.connector.execute(action)
        receipt = ActionReceipt(
            receipt_id=f"receipt-{uuid4()}",
            action_id=action.action_id,
            action_digest=action.action_digest(),
            permit_id=permit.permit_id,
            tenant_id=action.tenant_id,
            workspace_id=action.workspace_id,
            connector_id=action.capability_id,
            status=effect.status,
            idempotency_key=action.idempotency_key,
            attempt=attempt,
            output_artifact_ids=tuple(
                str(value)
                for value in _as_sequence(effect.output.get("artifact_ids", ()))
            ),
            error_code=effect.error_code,
            detail_ref=effect.detail_ref,
            occurred_at=datetime.now(timezone.utc),
        )
        return CapabilityResult(receipt=receipt, output=effect.output)


def _as_sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, (tuple, list)):
        return tuple(value)
    return ()
