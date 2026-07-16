from __future__ import annotations

from threading import RLock

from .srl_ports import (
    OutcomeAcceptanceResult,
    OutcomeAcceptorPort,
    TrustedOutcomeRecord,
)


class InMemoryOutcomeAcceptor(OutcomeAcceptorPort):
    """Fail-closed M0 stub with no trusted evaluator registry integration."""

    durable = False

    def __init__(self, trusted_registry_instance_ids: set[str] | None = None) -> None:
        self._lock = RLock()
        self._trusted_registry_instance_ids = trusted_registry_instance_ids or set()

    def trust_registry(self, instance_id: str) -> None:
        with self._lock:
            self._trusted_registry_instance_ids.add(instance_id)

    def accept(self, outcome_record: TrustedOutcomeRecord) -> OutcomeAcceptanceResult:
        with self._lock:
            return OutcomeAcceptanceResult(
                accepted=False,
                rejection_reason=(
                    "no trusted evaluator registry integration in M0; caller-provided "
                    "registry IDs and signature digests are not authority"
                ),
            )
