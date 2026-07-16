from __future__ import annotations

from threading import RLock

from .srl_ports import AuditPort, AuditTransition


class InMemoryAuditLog(AuditPort):
    """Non-erasable in-memory audit log stub."""

    durable = False

    def __init__(self) -> None:
        self._lock = RLock()
        self._transitions: list[AuditTransition] = []

    def record(self, transition: AuditTransition) -> None:
        with self._lock:
            self._transitions.append(transition)

    def transitions(self) -> tuple[AuditTransition, ...]:
        with self._lock:
            return tuple(self._transitions)
