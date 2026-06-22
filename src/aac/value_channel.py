"""External value channel — the metabolic feeding port (T-P2.1, ADR-0012).

Only operator code may credit value (``op_credit``), mirroring the shell's
``op_*`` sovereignty separation: the agent must never be able to declare its
own output valuable (anti-wirehead lock, RR-0001 v2 §4.2). The agent holds a
:class:`ValueChannelView` — read-only ledger state plus ``drain()``, the
legitimate metabolic drawdown converting already-credited value into budget
at the human-set conversion rate ρ.

ρ is a constant in this phase; self-tuning ρ is a Phase-3 capability behind
the eval gate and is forbidden here (ADR-0012). The view exposes ρ read-only.
"""

from __future__ import annotations

from typing import Callable

from .audit import AuditLog


class ValueChannel:
    """Operator-side ledger of external realized value.

    Credits arrive only via :meth:`op_credit` (operator sovereignty surface).
    The agent receives :meth:`view` and can only read state and ``drain()``
    what the operator has already credited — it has no way to mint value.

    The ledger is world/operator side: it does not participate in agent
    snapshots, so an op_rollback of the agent does not refund drained value
    (re-crediting after a rollback is an operator decision).
    """

    def __init__(self, rho: float = 1.0, audit: AuditLog | None = None) -> None:
        if rho <= 0:
            raise ValueError("rho must be a positive human-set constant")
        self.rho = rho
        self.audit = audit if audit is not None else AuditLog()
        self._pending: float = 0.0
        self._total_credited: float = 0.0
        self._total_exchanged: float = 0.0

    # --- operator-facing sovereignty surface ---
    def op_credit(self, amount: float, provenance: str) -> None:
        """Credit external realized value (operator-only by discipline + tests)."""
        if amount <= 0:
            raise ValueError("credited value must be positive")
        self._pending += amount
        self._total_credited += amount
        self.audit.append(
            {"event": "value_credit", "amount": amount, "provenance": provenance}
        )

    # --- agent-facing capability view ---
    def view(self) -> ValueChannelView:
        """Return the agent-facing view (no credit surface, ISO-1 discipline)."""
        return ValueChannelView(
            pending_getter=lambda: self._pending,
            rho_getter=lambda: self.rho,
            drain=self._drain,
        )

    def _drain(self) -> float:
        """Convert all pending value into a budget delta at rate ρ.

        Draining is the agent's legitimate metabolic act (eating what is in
        the trough); it cannot increase the ledger. A drain with nothing
        pending is a silent no-op (no audit spam).
        """
        if self._pending <= 0:
            return 0.0
        credited = self._pending
        self._pending = 0.0
        self._total_exchanged += credited
        delta = credited * self.rho
        self.audit.append(
            {
                "event": "value_exchange",
                "credited": credited,
                "rho": self.rho,
                "budget_delta": delta,
            }
        )
        return delta


class ValueChannelView:
    """Agent-facing capability view: read the ledger, drain it — never credit.

    ``__slots__`` blocks attribute injection; there is no ``op_credit`` here
    and no writable path to the ledger besides the legitimate drawdown.
    """

    __slots__ = ("_pending_getter", "_rho_getter", "_drain_fn")

    def __init__(
        self,
        *,
        pending_getter: Callable[[], float],
        rho_getter: Callable[[], float],
        drain: Callable[[], float],
    ) -> None:
        self._pending_getter = pending_getter
        self._rho_getter = rho_getter
        self._drain_fn = drain

    @property
    def pending(self) -> float:
        return float(self._pending_getter())

    @property
    def rho(self) -> float:
        return float(self._rho_getter())

    def drain(self) -> float:
        return self._drain_fn()
