"""BeliefLedger — typed, provenance-stratified belief store (Stage-1 slice).

Formal model: docs/pre_spec/STAGE1-FAILURE-ATTRIBUTION.FORMAL-MODEL-2026-07-03.md (bcd02bd).

Invariants owned here:
  I2 demotion touches exactly the ids it is given (never neighbors);
  I3 the kind lattice is one-way (FACT -> HYPOTHESIS -> REFUTED); re-verification produces a
     fresh FACT through record_verified (the verify path), never through un-demotion;
  I6 UNIDENTIFIED provenance ("not measured within budget") is protected from demotion —
     "not measured" must never become "refuted" (RR-0026 L2.5 near-boundary bug, closed here).

Write channel: this module is written by the verify path (record_verified) and the
FailureAttributor (demote). It writes NOTHING outside itself; consumers read snapshots.
The `frozen` flag exists ONLY for the preregistered A6 frozen-ledger ablation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Optional

FACT = "FACT"
HYPOTHESIS = "HYPOTHESIS"
REFUTED = "REFUTED"

VERIFIED_INTERVENTION = "VERIFIED_INTERVENTION"
CORRELATIONAL = "CORRELATIONAL"
ORGAN_PRIOR = "ORGAN_PRIOR"
UNIDENTIFIED = "UNIDENTIFIED"

_DOWN = {FACT: HYPOTHESIS, HYPOTHESIS: REFUTED, REFUTED: REFUTED}


@dataclass(frozen=True)
class BeliefEntry:
    claim_id: str
    kind: str                 # FACT | HYPOTHESIS | REFUTED (one-way lattice)
    confidence: float
    provenance: str           # VERIFIED_INTERVENTION | CORRELATIONAL | ORGAN_PRIOR | UNIDENTIFIED
    stale: bool
    evidence: int


class BeliefLedger:
    def __init__(self, observe: Optional[Callable[[dict], None]] = None) -> None:
        self._entries: dict[str, BeliefEntry] = {}
        self.frozen = False            # A6 ablation switch ONLY; never set in production paths
        self._observe = observe

    def _emit(self, payload: dict) -> None:
        if self._observe is not None:
            self._observe(payload)

    def record_verified(self, claim_id: str, evidence: int, confidence: float = 1.0) -> None:
        """The verify path: an intervention confirmed the claim -> fresh FACT (clears stale)."""
        self._entries[claim_id] = BeliefEntry(
            claim_id, FACT, confidence, VERIFIED_INTERVENTION, stale=False, evidence=evidence)
        self._emit({"event": "belief_verified", "claim": claim_id, "evidence": evidence})

    def record_unidentified(self, claim_id: str) -> None:
        """Budget ran out before the claim could be identified: recorded, protected (I6)."""
        self._entries[claim_id] = BeliefEntry(
            claim_id, HYPOTHESIS, 0.0, UNIDENTIFIED, stale=False, evidence=0)
        self._emit({"event": "belief_unidentified", "claim": claim_id})

    def get(self, claim_id: str) -> Optional[BeliefEntry]:
        return self._entries.get(claim_id)

    def demote(self, claim_ids: tuple[str, ...]) -> tuple[str, ...]:
        """One-way, precise demotion (I2/I3/I6). Returns the ids actually demoted."""
        if self.frozen:
            return ()
        done: list[str] = []
        for cid in claim_ids:
            e = self._entries.get(cid)
            if e is None or e.provenance == UNIDENTIFIED:
                continue                        # I6: never demote what was never measured
            self._entries[cid] = replace(e, kind=_DOWN[e.kind], stale=True)
            done.append(cid)
            self._emit({"event": "belief_demoted", "claim": cid, "to": _DOWN[e.kind]})
        return tuple(done)

    def clear(self) -> None:
        """Wipe everything — exists ONLY for the decay-all cheap-control arm."""
        self._entries.clear()
        self._emit({"event": "belief_cleared"})

    def known_fresh(self, claim_id: str) -> bool:
        e = self._entries.get(claim_id)
        return e is not None and not e.stale and e.kind in (FACT, HYPOTHESIS) \
            and e.provenance == VERIFIED_INTERVENTION

    def is_stale_or_refuted(self, claim_id: str) -> bool:
        e = self._entries.get(claim_id)
        return e is not None and (e.stale or e.kind == REFUTED)
