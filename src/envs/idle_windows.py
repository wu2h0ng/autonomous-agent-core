"""Idle-window wrapper (T-P2.2, ADR-0012).

Adds idle phases to any env exposing ``act(action) -> reward`` without
changing its semantics. Idle means "no external demand", not "the world
stops": ``act`` passes through unchanged. (Attenuating idle yield is a
T-P2.3 environment-validity knob, to be added via ADR revision if the
gate run needs it — not unvalidated mechanism here.)

All other attributes (``force_regime_change``, ``best_action`` …) are
delegated to the inner env so experiments can drive it through the wrapper.
"""
from __future__ import annotations

from typing import Any


class IdleWindowEnv:
    """Deterministic work/idle schedule around an inner environment.

    A cycle is ``work_period`` work steps followed by ``idle_period`` idle
    steps. :attr:`idle` reflects the phase of the *next* ``act`` call.
    """

    def __init__(self, inner: Any, work_period: int = 60, idle_period: int = 20) -> None:
        if work_period <= 0:
            raise ValueError("work_period must be positive")
        if idle_period < 0:
            raise ValueError("idle_period must be non-negative")
        self.inner = inner
        self.work_period = work_period
        self.idle_period = idle_period
        self._t = 0

    @property
    def idle(self) -> bool:
        if self.idle_period == 0:
            return False
        return (self._t % (self.work_period + self.idle_period)) >= self.work_period

    def act(self, action: int) -> float:
        self._t += 1
        return self.inner.act(action)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)
