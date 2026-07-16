from __future__ import annotations

from threading import RLock

from agent_os_contracts import OutcomeStatus

from .srl_ports import (
    OutcomeAcceptanceResult,
    OutcomeAcceptorPort,
    TrustedOutcomeRecord,
)


class InMemoryOutcomeAcceptor(OutcomeAcceptorPort):
    """Accept only ObservedOutcome records signed by a trusted evaluator registry."""

    durable = False

    def __init__(self, trusted_registry_instance_ids: set[str] | None = None) -> None:
        self._lock = RLock()
        self._trusted_registry_instance_ids = trusted_registry_instance_ids or set()
        self._accepted: dict[str, TrustedOutcomeRecord] = {}

    def trust_registry(self, instance_id: str) -> None:
        with self._lock:
            self._trusted_registry_instance_ids.add(instance_id)

    def accept(self, outcome_record: TrustedOutcomeRecord) -> OutcomeAcceptanceResult:
        with self._lock:
            if (
                outcome_record.evaluator_registry_instance_id
                not in self._trusted_registry_instance_ids
            ):
                return OutcomeAcceptanceResult(
                    accepted=False,
                    rejection_reason="outcome not signed by trusted evaluator registry",
                )
            observed = outcome_record.observed_outcome
            if observed.status in {OutcomeStatus.INVALID, OutcomeStatus.UNRESOLVED}:
                return OutcomeAcceptanceResult(
                    accepted=False,
                    rejection_reason=f"outcome status is {observed.status.value}",
                )
            self._accepted[outcome_record.record_id] = outcome_record
            return OutcomeAcceptanceResult(accepted=True)
