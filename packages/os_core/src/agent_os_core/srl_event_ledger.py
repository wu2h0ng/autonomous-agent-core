from __future__ import annotations

from threading import RLock

from agent_os_contracts import SrlEnvironmentEvent

from .srl_ports import EventLedgerPort, EventLedgerReceipt


class InMemoryEventLedger(EventLedgerPort):
    """In-memory immutable event ledger with deduplication per binding."""

    durable = False

    def __init__(self) -> None:
        self._lock = RLock()
        self._events: dict[str, SrlEnvironmentEvent] = {}
        self._by_binding: dict[str, list[str]] = {}

    def append(self, event: SrlEnvironmentEvent) -> EventLedgerReceipt:
        with self._lock:
            key = self._key(event.binding_id, event.dedupe_key)
            if key in self._events:
                return EventLedgerReceipt(
                    event_id=event.event_id,
                    binding_id=event.binding_id,
                    dedupe_key=event.dedupe_key,
                    status="DUPLICATE",
                )
            self._events[key] = event
            self._by_binding.setdefault(event.binding_id, []).append(event.dedupe_key)
            return EventLedgerReceipt(
                event_id=event.event_id,
                binding_id=event.binding_id,
                dedupe_key=event.dedupe_key,
                status="APPENDED",
            )

    def get(self, binding_id: str, dedupe_key: str) -> SrlEnvironmentEvent | None:
        with self._lock:
            return self._events.get(self._key(binding_id, dedupe_key))

    def list_events(self, binding_id: str) -> tuple[SrlEnvironmentEvent, ...]:
        with self._lock:
            dedupe_keys = self._by_binding.get(binding_id, ())
            return tuple(
                self._events[self._key(binding_id, dedupe_key)]
                for dedupe_key in dedupe_keys
            )

    @staticmethod
    def _key(binding_id: str, dedupe_key: str) -> str:
        return f"{binding_id}::{dedupe_key}"
