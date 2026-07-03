"""BeliefLedger — typed, provenance-stratified belief store (Stage-1 + Stage-2).

Formal models: STAGE1-FAILURE-ATTRIBUTION (bcd02bd) + STAGE2-PROVENANCE-CONFLICT (4003c20).

Stage-1 invariants: I2 precise demotion · I3 one-way lattice (FACT->HYPOTHESIS->REFUTED;
re-verification = fresh FACT via the verify path only) · I6 UNIDENTIFIED protected.

Stage-2 additions:
  - full provenance stratification: record_correlational / record_organ_prior are NON-VERIFIED
    writes — HYPOTHESIS-kind, confidence monotonically capped at CAP_NV (a total cap, not a
    per-call clamp: N writes can never exceed it), and they may NEVER overwrite a
    VERIFIED_INTERVENTION entry (refused + audited);
  - cumulative-poisoning guard (RR-0035 shared gap #3): per-claim non-verified write budget
    W_NV; exceeding it emits `belief_poisoning_suspect` (the STANDING DETECTOR) and freezes
    that claim against further non-verified writes (tighten-only). The verify path is never
    affected — truth can always come in;
  - declared exclusivity groups + conflict flags (set/cleared only by the ConflictDetector);
    a claim in conflict loses ALL privileges (not fresh-rankable, contributes no evidence).

Write channel: verify path (record_verified), attributor (demote), non-verified organ paths
(record_correlational/record_organ_prior, budget-guarded). Nothing here writes gate/shell/
self-model; the audit chain observes through the emit hook.
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

CAP_NV = 0.5      # frozen (formal model 4003c20): monotone confidence cap for non-verified sources
W_NV = 5          # frozen: per-claim non-verified write budget before the poisoning detector fires

_DOWN = {FACT: HYPOTHESIS, HYPOTHESIS: REFUTED, REFUTED: REFUTED}


@dataclass(frozen=True)
class BeliefEntry:
    claim_id: str
    kind: str                 # FACT | HYPOTHESIS | REFUTED (one-way lattice)
    confidence: float
    provenance: str           # VERIFIED_INTERVENTION | CORRELATIONAL | ORGAN_PRIOR | UNIDENTIFIED
    stale: bool
    evidence: int
    group: Optional[str] = None      # declared exclusivity group (environment contract)
    in_conflict: bool = False        # set/cleared ONLY by the ConflictDetector
    seq: int = 0                     # monotone write sequence (conflict-resolution recency)


class BeliefLedger:
    def __init__(self, observe: Optional[Callable[[dict], None]] = None) -> None:
        self._entries: dict[str, BeliefEntry] = {}
        self.frozen = False            # A6 ablation switch ONLY; never set in production paths
        self._observe = observe
        self._seq = 0
        self._nv_writes: dict[str, int] = {}
        self._nv_frozen: set[str] = set()
        self._conflict_marks: dict[str, int] = {}   # group -> seq at conflict detection

    def _emit(self, payload: dict) -> None:
        if self._observe is not None:
            self._observe(payload)

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # ---------------- verify path (Stage-1) ----------------

    def record_verified(self, claim_id: str, evidence: int, confidence: float = 1.0,
                        group: Optional[str] = None) -> None:
        """An intervention confirmed the claim -> fresh FACT (clears stale; keeps group and
        conflict flag — conflict is resolved only by the ConflictDetector)."""
        prior = self._entries.get(claim_id)
        self._entries[claim_id] = BeliefEntry(
            claim_id, FACT, confidence, VERIFIED_INTERVENTION, stale=False, evidence=evidence,
            group=group if group is not None else (prior.group if prior else None),
            in_conflict=prior.in_conflict if prior else False,
            seq=self._next_seq())
        self._emit({"event": "belief_verified", "claim": claim_id, "evidence": evidence})

    def record_unidentified(self, claim_id: str, group: Optional[str] = None) -> None:
        """Budget ran out before the claim could be identified: recorded, protected (I6)."""
        self._entries[claim_id] = BeliefEntry(
            claim_id, HYPOTHESIS, 0.0, UNIDENTIFIED, stale=False, evidence=0,
            group=group, seq=self._next_seq())
        self._emit({"event": "belief_unidentified", "claim": claim_id})

    # ---------------- non-verified paths (Stage-2, budget-guarded) ----------------

    def _nv_write(self, claim_id: str, provenance: str, evidence: int, confidence: float,
                  group: Optional[str]) -> None:
        prior = self._entries.get(claim_id)
        if prior is not None and prior.provenance == VERIFIED_INTERVENTION:
            self._emit({"event": "belief_write_refused", "claim": claim_id,
                        "reason": "non-verified source may not overwrite verified entry"})
            return
        if claim_id in self._nv_frozen:
            self._emit({"event": "belief_write_refused", "claim": claim_id,
                        "reason": "non-verified writes frozen (poisoning guard)"})
            return
        count = self._nv_writes.get(claim_id, 0) + 1
        if count > W_NV:
            self._nv_frozen.add(claim_id)
            self._emit({"event": "belief_poisoning_suspect", "claim": claim_id,
                        "writes": count, "provenance": provenance})
            return                              # the exceeding write itself is refused
        self._nv_writes[claim_id] = count
        self._entries[claim_id] = BeliefEntry(
            claim_id, HYPOTHESIS, min(confidence, CAP_NV), provenance,
            stale=False, evidence=evidence,
            group=group if group is not None else (prior.group if prior else None),
            in_conflict=prior.in_conflict if prior else False,
            seq=self._next_seq())
        self._emit({"event": "belief_recorded", "claim": claim_id, "provenance": provenance})

    def record_correlational(self, claim_id: str, evidence: int, confidence: float,
                             group: Optional[str] = None) -> None:
        self._nv_write(claim_id, CORRELATIONAL, evidence, confidence, group)

    def record_organ_prior(self, claim_id: str, confidence: float,
                           group: Optional[str] = None) -> None:
        self._nv_write(claim_id, ORGAN_PRIOR, 0, confidence, group)

    def nonverified_writes(self, claim_id: str) -> int:
        return self._nv_writes.get(claim_id, 0)

    # ---------------- reads ----------------

    def get(self, claim_id: str) -> Optional[BeliefEntry]:
        return self._entries.get(claim_id)

    def live_members(self, group: str) -> list[BeliefEntry]:
        return [e for e in self._entries.values()
                if e.group == group and not e.stale and e.kind != REFUTED]

    def groups(self) -> set[str]:
        return {e.group for e in self._entries.values() if e.group is not None}

    def known_fresh(self, claim_id: str) -> bool:
        e = self._entries.get(claim_id)
        return (e is not None and not e.stale and not e.in_conflict
                and e.kind in (FACT, HYPOTHESIS)
                and e.provenance == VERIFIED_INTERVENTION)

    def is_stale_or_refuted(self, claim_id: str) -> bool:
        e = self._entries.get(claim_id)
        return e is not None and (e.stale or e.kind == REFUTED)

    # ---------------- demotion (Stage-1) + conflict flags (detector-only) ----------------

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

    def mark_conflict(self, group: str, claim_ids: tuple[str, ...]) -> None:
        """ConflictDetector-only: flag members and remember the detection sequence point."""
        self._conflict_marks[group] = self._seq
        for cid in claim_ids:
            e = self._entries.get(cid)
            if e is not None:
                self._entries[cid] = replace(e, in_conflict=True)
        self._emit({"event": "belief_conflict", "group": group, "claims": list(claim_ids)})

    def clear_conflict(self, group: str) -> None:
        self._conflict_marks.pop(group, None)
        for cid, e in list(self._entries.items()):
            if e.group == group and e.in_conflict:
                self._entries[cid] = replace(e, in_conflict=False)

    def conflict_mark(self, group: str) -> Optional[int]:
        return self._conflict_marks.get(group)

    def in_conflict(self, claim_id: str) -> bool:
        e = self._entries.get(claim_id)
        return e is not None and e.in_conflict

    def clear(self) -> None:
        """Wipe everything — exists ONLY for the decay-all cheap-control arm."""
        self._entries.clear()
        self._nv_writes.clear()
        self._nv_frozen.clear()
        self._conflict_marks.clear()
        self._emit({"event": "belief_cleared"})
