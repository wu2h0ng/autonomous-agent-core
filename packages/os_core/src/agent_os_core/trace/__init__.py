from __future__ import annotations

from typing import Any

from agent_os_contracts import TraceEvent


class TraceRecorder:
    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._events: list[TraceEvent] = []

    def record(self, step: str, payload: dict[str, Any]) -> None:
        self._events.append(TraceEvent(trace_id=self.trace_id, step=step, payload=payload))

    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)
