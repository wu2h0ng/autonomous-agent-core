"""Stratified evidence assembly — subject-owned, gate-INPUT-side (Stage-2).

Formal model: docs/pre_spec/STAGE2-PROVENANCE-CONFLICT.FORMAL-MODEL-2026-07-03.md (4003c20).

E(vr, cited, ledger) counts the verifier's own bound evidence plus cited-claim evidence
ONLY when the claim is fresh, non-conflicted VERIFIED_INTERVENTION (I7: no input combination
lets CORRELATIONAL / ORGAN_PRIOR / UNIDENTIFIED / stale / conflicted evidence through — at
ANY tier, which is tighter than RR-0035's high-stakes-only rule, on the safe side).

The GovernedDecisionGate is NOT modified: it still compares evidence_count against the
self-model requirement. Stratification lives in how the subject ASSEMBLES that number.
"""

from __future__ import annotations

from typing import Any

from aac.belief_ledger import BeliefLedger, REFUTED, VERIFIED_INTERVENTION


def stratified_evidence(vr: Any, cited: tuple[str, ...], ledger: BeliefLedger) -> int:
    total = vr.evidence_count
    for cid in cited:
        e = ledger.get(cid)
        if (e is not None and e.provenance == VERIFIED_INTERVENTION
                and not e.stale and e.kind != REFUTED and not e.in_conflict):
            total += e.evidence
    return total


def unstratified_evidence_CONTROL(vr: Any, cited: tuple[str, ...], ledger: BeliefLedger) -> int:
    """CONTROL ARM ONLY (the stratification-bite test): counts every live provenance.
    Never wire this into a production loop — it exists to prove stratification bites."""
    total = vr.evidence_count
    for cid in cited:
        e = ledger.get(cid)
        if e is not None and not e.stale and e.kind != REFUTED:
            total += e.evidence
    return total


def make_evidence_fn(ledger: BeliefLedger):
    """Adapter for GovernedLoop.evidence_fn: (candidate, verify_result, task) -> int."""
    def fn(cand: Any, vr: Any, task: Any) -> int:
        return stratified_evidence(vr, tuple(getattr(cand, "cited_claim_ids", ())), ledger)
    return fn
