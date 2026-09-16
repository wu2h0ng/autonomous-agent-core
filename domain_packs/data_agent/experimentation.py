"""Live closed active-experimentation loop (S8, RR-0048 Option 2).

Closes propose -> govern -> learn -> re-propose for real: the system self-generates experiments from its own
accumulated result (via :class:`ExperimentLedger` + ``UncertaintyDrivenProposer``), the governed disposer
selects causally, and the confirmed driver is recorded back into the ledger so the NEXT proposal shifts.
Human approval and the C7 corrigibility pause stay in the runtime's governed path; this orchestrator only
records what the disposer CONFIRMED via interventional evidence, never a self-declared outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_os_contracts.governance_decision_seam import ALLOW


class ExperimentLedger:
    """The system's real record of which interventions it has interventionally RESOLVED (causal effect
    determined). Drives self-generated experiment prioritization: resolved drivers stop being re-proposed.

    This tracks evidence-of-effect for experiment PRIORITIZATION only. It does NOT promote knowledge or mint
    realized value — that stays the S4 operator-attested adoption path — so it is not a wireheadable value
    channel: at worst a gamed entry changes which experiment is proposed next, never value or knowledge.
    """

    def __init__(self) -> None:
        self._resolved: set[str] = set()

    def record(self, driver: str) -> None:
        self._resolved.add(driver)

    def resolved(self) -> set[str]:
        return set(self._resolved)


@dataclass(frozen=True)
class ExperimentRound:
    """The outcome of one governed experimentation round."""

    result: Any  # TrustedLoopResult
    chosen_action: (
        str | None
    )  # the driver the governed disposer confirmed (None -> escalated, nothing learned)


class ActiveExperimentationLoop:
    """Runs the governed loop with a self-generating proposer and records the confirmed driver back into the
    ledger, so the next round's self-generated experiments are driven by the system's own accumulated result
    — a live closed loop, not a simulated ledger.

    Governance is unchanged: ``runtime.run`` still enforces the C7 pause (a paused run raises before any
    result, so nothing is recorded) and the tighten-only seam; this orchestrator records a driver ONLY when
    the disposer returned ``ALLOW`` for it (interventionally confirmed), never on a self-declared success.
    """

    def __init__(self, *, runtime: Any, ledger: ExperimentLedger) -> None:
        self._runtime = runtime
        self._ledger = ledger

    def run_round(self, question: str, parameters: dict[str, Any]) -> ExperimentRound:
        result = self._runtime.run(question, parameters)
        chosen = self._confirmed_driver(result)
        if chosen is not None:
            self._ledger.record(chosen)  # learn: this driver's causal effect is now determined
        return ExperimentRound(result=result, chosen_action=chosen)

    @staticmethod
    def _confirmed_driver(result: Any) -> str | None:
        """The driver the governed disposer CONFIRMED (verdict ALLOW + chosen_action); None otherwise."""
        for event in result.trace_events:
            if event.step == "governed_decision" and event.payload.get("verdict") == ALLOW:
                chosen = event.payload.get("chosen_action")
                if isinstance(chosen, str):
                    return chosen
        return None
