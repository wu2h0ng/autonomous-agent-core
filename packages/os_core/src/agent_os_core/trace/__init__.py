from __future__ import annotations

from typing import Any

from agent_os_contracts import TelemetryDimension, TelemetryEvent, TraceEvent


class TraceRecorder:
    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._events: list[TraceEvent] = []
        self._telemetry_events: list[TelemetryEvent] = []

    def record(self, step: str, payload: dict[str, Any]) -> None:
        self._events.append(TraceEvent(trace_id=self.trace_id, step=step, payload=payload))

    def metric(
        self,
        *,
        dimension: TelemetryDimension,
        name: str,
        value: float,
        unit: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self._telemetry_events.append(
            TelemetryEvent(
                trace_id=self.trace_id,
                dimension=dimension,
                name=name,
                value=value,
                unit=unit,
                attributes=attributes or {},
            )
        )

    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)

    def telemetry_events(self) -> tuple[TelemetryEvent, ...]:
        return tuple(self._telemetry_events)
