from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from agent_os_contracts import (
    ActionContract,
    ActionPermit,
    ActionReceipt,
    CapabilitySpec,
    ReceiptStatus,
)

from ._action_outcome import (
    CapabilityDenied,
    CapabilityEffectUnknown,
    CapabilityResult,
    DurableActionOutcomeRepository,
    ExecutionLease,
    ExecutionLeaseConflict,
)
from .governance import CorrectionGuardConflict, CorrectionReadPort


class CapabilityCorrectionBlocked(CapabilityDenied):
    """C7 changed before an effect was dispatched."""


@dataclass(frozen=True)
class CapabilityEffect:
    status: ReceiptStatus
    output: dict[str, object]
    error_code: str = "error:none"
    detail_ref: str = "detail:none"


class CapabilityPort(Protocol):
    """Generic capability dispatch interface. Core depends on this, not on WorkspaceSandbox.

    ADR-0059: the broker orchestrates the durable reservation/lease/UNKNOWN/C7
    spine; the connector executes the physical effect and exposes replay,
    preflight, outcomes, and execution-lease primitives.
    """

    def specs(
        self,
        now: datetime | None = None,
        *,
        include_internal: bool = False,
    ) -> Mapping[str, CapabilitySpec]: ...

    def execute(self, action: ActionContract) -> CapabilityEffect: ...

    def replay(self, action: ActionContract) -> CapabilityResult | None: ...

    def outcomes(self) -> DurableActionOutcomeRepository | None: ...

    def preflight(
        self,
        capability_id: str,
        args: dict[str, object],
        action_key: str,
    ) -> None: ...

    def acquire_execution_lease(
        self, action: ActionContract, owner: str
    ) -> ExecutionLease: ...

    def release_execution_lease(self, lease: ExecutionLease) -> bool: ...


class CapabilityBroker:
    """The only production execution boundary for typed capability actions.

    ADR-0059 merged spine: the broker runs the durable reservation ->
    lease-fenced dispatch -> typed-UNKNOWN -> seal sequence around the
    connector's physical `execute`, with C7 linearization via
    `guard_unchanged`. Deterministic deny checks (preflight) run BEFORE any
    reservation, so DENIED never produces a reservation or an UNKNOWN record.
    """

    def __init__(self, connector: CapabilityPort, correction: CorrectionReadPort) -> None:
        self.connector = connector
        self.correction = correction

    def invoke(
        self,
        action: ActionContract,
        permit: ActionPermit,
        attempt: int = 1,
        *,
        execution_claim: ExecutionLease,
    ) -> CapabilityResult:
        if not permit.matches(action):
            raise CapabilityDenied("broker rejected a permit/action digest mismatch")
        replayed = self.replay(action)
        if replayed is not None:
            return replayed
        if (
            execution_claim.run_id != action.run_id
            or execution_claim.fence != permit.lease_fence
        ):
            raise ExecutionLeaseConflict(
                "execution claim does not bind the action permit"
            )
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
        args = json.loads(action.arguments_json)
        if not isinstance(args, dict):
            raise CapabilityDenied("capability arguments must be an object")
        outcomes = self.connector.outcomes()
        if outcomes is None:
            raise CapabilityDenied(
                "durable idempotency store is required before capability dispatch"
            )
        # Deterministic allowlist/path checks run before reservation: a DENIED
        # action never produces a reservation or an UNKNOWN record.
        self.connector.preflight(action.capability_id, args, action.idempotency_key)
        reserved = outcomes.reserve(action, execution_lease=execution_claim)
        if isinstance(reserved, CapabilityResult):
            return reserved
        reservation = reserved
        try:
            with self.correction.guard_unchanged(
                action.task_id,
                action.run_id,
                action.capability_id,
                permit.correction_epochs,
            ) as unchanged:
                if not unchanged:
                    raise CapabilityCorrectionBlocked(
                        "correction authority changed before guarded dispatch"
                    )
                effect = self.connector.execute(action)
                output = outcomes.canonical_output(effect.output)
        except Exception as exc:
            correction_conflict = isinstance(
                exc,
                (CapabilityCorrectionBlocked, CorrectionGuardConflict),
            )
            raise outcomes.unknown(
                action,
                reason_code=(
                    "DISPATCH_CORRECTION_CONFLICT"
                    if correction_conflict
                    else (
                        exc.reason_code
                        if isinstance(exc, CapabilityEffectUnknown)
                        else "POST_DISPATCH_UNCERTAIN"
                    )
                ),
                detail=f"{type(exc).__name__}: {exc}",
                reservation=reservation,
            ) from exc
        receipt = _build_receipt(
            action,
            permit,
            reservation,
            output,
            status=(
                ReceiptStatus.COMPENSATED
                if action.capability_id == "workspace.compensate_patch"
                else ReceiptStatus.SUCCEEDED
            ),
            error_code="error:none",
            attempt=attempt,
        )
        return outcomes.seal(action, reservation, permit, receipt, output)

    def replay(self, action: ActionContract) -> CapabilityResult | None:
        replay = getattr(self.connector, "replay", None)
        if replay is None:
            return None
        result = replay(action)
        if result is not None and not result.permit.matches(action):
            raise CapabilityEffectUnknown(
                action,
                reason_code="OUTCOME_PERMIT_MISMATCH",
                detail="stored capability outcome permit/action mismatch",
            )
        return result


def _build_receipt(
    action: ActionContract,
    permit: ActionPermit,
    reservation: dict[str, object],
    output: dict[str, object],
    *,
    status: ReceiptStatus,
    error_code: str,
    attempt: int,
) -> ActionReceipt:
    """Sealed receipt identity is the reservation's receipt_id (ADR-0059 R3)."""

    return ActionReceipt(
        receipt_id=str(reservation["receipt_id"]),
        action_id=action.action_id,
        action_digest=action.action_digest(),
        permit_id=permit.permit_id,
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        connector_id=action.capability_id,
        status=status,
        idempotency_key=action.idempotency_key,
        attempt=attempt,
        output_artifact_ids=tuple(
            str(value) for value in _as_sequence(output.get("artifact_ids", ()))
        ),
        error_code=error_code,
        detail_ref=str(output.get("compensation_ref", "detail:none")),
        occurred_at=datetime.now(timezone.utc),
    )


def _as_sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, (tuple, list)):
        return tuple(value)
    return ()
