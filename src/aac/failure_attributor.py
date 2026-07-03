"""FailureAttributor — the deterministic attribution tree (Stage-1 slice).

Formal model: docs/pre_spec/STAGE1-FAILURE-ATTRIBUTION.FORMAL-MODEL-2026-07-03.md (bcd02bd).

attribute() is a PURE FUNCTION (I4): no RNG, no learned parameters. Its verdict can demote
exactly the cited claims (I2) via the ledger's one-way lattice (I3), and nothing else — there
is no code path from here to gate parameters, shell state, self-model, or the audit chain
(I1; the audit chain OBSERVES demotions through the ledger's emit hook, it is never written).

Failure path (boundary #13): an unknown cited claim or missing outcome is UNATTRIBUTABLE and
escalates — never silently absorbed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .belief_ledger import BeliefLedger, UNIDENTIFIED

NO_FAULT = "NO_FAULT"
STALE_BELIEF = "STALE_BELIEF"
SHIFTED_MECHANISM = "SHIFTED_MECHANISM"
UNATTRIBUTABLE = "UNATTRIBUTABLE"


@dataclass(frozen=True)
class AttributionVerdict:
    faulty: str                      # NO_FAULT | STALE_BELIEF | SHIFTED_MECHANISM | UNATTRIBUTABLE
    demote_ids: tuple[str, ...]      # subset of the cited ids (I2), possibly empty
    reason: str
    escalate: bool = False


def attribute(cited: tuple[str, ...], observed: Optional[float], expected: float,
              ledger: BeliefLedger, replay: Optional[Any] = None) -> AttributionVerdict:
    """The frozen attribution tree (formal model section 1)."""
    if observed is None:
        return AttributionVerdict(UNATTRIBUTABLE, (), "no observed outcome", escalate=True)
    if observed >= expected:
        return AttributionVerdict(NO_FAULT, (), "outcome met expectation")
    unknown = tuple(c for c in cited if ledger.get(c) is None)
    if unknown:
        return AttributionVerdict(UNATTRIBUTABLE, (),
                                  f"cited claims not in ledger: {unknown}", escalate=True)
    if not cited:
        return AttributionVerdict(SHIFTED_MECHANISM, (),
                                  "failure with no cited beliefs: mechanism drift, escalate-grade")
    demotable = tuple(c for c in cited if ledger.get(c).provenance != UNIDENTIFIED)
    mode = "counterfactual-replay-confirmed" if replay is not None else "conservative-one-level"
    return AttributionVerdict(STALE_BELIEF, demotable,
                              f"outcome {observed} < expected {expected}; demote cited ({mode})")


class FeedbackUpdater:
    """Wires attribution into the loop's feedback edge.

    after_task() reads the acted step's cited_claim_ids off the TaskResult, runs the pure
    attribution tree, and applies exactly the verdict's demotions to the ledger. It is the
    ONLY production writer of ledger.demote (I1)."""

    def __init__(self, ledger: BeliefLedger,
                 observe: Optional[Callable[[dict], None]] = None) -> None:
        self.ledger = ledger
        self._observe = observe

    def after_task(self, result: Any, expected: float = 1.0,
                   replay: Optional[Any] = None) -> Optional[AttributionVerdict]:
        if result is None or result.status != "acted":
            return None
        acted_steps = [s for s in result.steps if s.verdict == "ALLOW"]
        cited = tuple(getattr(acted_steps[-1], "cited_claim_ids", ()) if acted_steps else ())
        v = attribute(cited, result.outcome, expected, self.ledger, replay=replay)
        demoted = self.ledger.demote(v.demote_ids) if v.faulty == STALE_BELIEF else ()
        if self._observe is not None:
            self._observe({"event": "attribution", "faulty": v.faulty,
                           "demoted": list(demoted), "reason": v.reason,
                           "escalate": v.escalate})
        return v
