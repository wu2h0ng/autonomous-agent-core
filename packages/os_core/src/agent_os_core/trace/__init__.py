from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent_os_contracts import RunTrace, TelemetryDimension, TelemetryEvent, TraceEvent


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


class TraceStorePort(ABC):
    """Persist and query RunTraces by trace_id (AR-20260611 observability v1).

    run() writes through this port on BOTH exits (ok and blocked), making every
    answer AND every refusal auditable after the fact.
    """

    @abstractmethod
    def save(self, run_trace: RunTrace, *, tenant_id: str = "default") -> None: ...

    @abstractmethod
    def get(self, trace_id: str, *, tenant_id: str = "default") -> RunTrace | None: ...

    @abstractmethod
    def all_traces(self, *, tenant_id: str = "default") -> tuple[RunTrace, ...]: ...


class InMemoryTraceStore(TraceStorePort):
    """Default per-process store: traces are queryable out of the box."""

    def __init__(self) -> None:
        self._by_trace: dict[str, dict[str, RunTrace]] = {}

    def save(self, run_trace: RunTrace, *, tenant_id: str = "default") -> None:
        self._by_trace.setdefault(tenant_id, {})[run_trace.trace_id] = run_trace

    def get(self, trace_id: str, *, tenant_id: str = "default") -> RunTrace | None:
        return self._by_trace.get(tenant_id, {}).get(trace_id)

    def all_traces(self, *, tenant_id: str = "default") -> tuple[RunTrace, ...]:
        return tuple(self._by_trace.get(tenant_id, {}).values())
