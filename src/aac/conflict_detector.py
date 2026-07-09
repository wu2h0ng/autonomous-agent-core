"""ConflictDetector — deterministic contradiction scan + convergence rule (Stage-2).

Formal model: docs/pre_spec/STAGE2-PROVENANCE-CONFLICT.FORMAL-MODEL-2026-07-03.md (4003c20).

scan(): a declared exclusivity group with >= 2 live members is a contradiction — both are
flagged (privileges stripped: no fresh ranking, no evidence contribution) and audited.
Conflict STRIPS, never deletes: truth re-enters only through the verify path.

resolve() — the deterministic convergence rule (I10):
  - a member re-verified AFTER the conflict mark (seq > mark) wins; every other live member
    is demoted through the Stage-1 one-way lattice; the group converges to the
    intervention-verified claim (the A2 requirement);
  - VI-vs-VI with no post-mark re-verification (e.g. pre/post mechanism-flip truths): BOTH
    are demoted+staled and re-verification is REQUIRED — never a silent preference;
  - mixed VI-vs-non-verified with no post-mark re-verification: stays pending (privileges
    stay stripped until the verify path speaks).

Writes go through ledger.demote / ledger.mark_conflict / ledger.clear_conflict only (I1).
"""

from __future__ import annotations

from aac.belief_ledger import BeliefLedger, VERIFIED_INTERVENTION


class ConflictDetector:
    def __init__(self, ledger: BeliefLedger) -> None:
        self.ledger = ledger

    def scan(self) -> tuple[str, ...]:
        """Flag every declared group holding >= 2 live members. Returns the conflicted groups."""
        conflicted: list[str] = []
        for group in sorted(self.ledger.groups()):
            live = self.ledger.live_members(group)
            if len(live) >= 2:
                conflicted.append(group)
                if self.ledger.conflict_mark(group) is None:
                    self.ledger.mark_conflict(group, tuple(e.claim_id for e in live))
        return tuple(conflicted)

    def resolve(self) -> dict:
        """Apply the convergence rule to every marked group. Deterministic; returns a report."""
        resolved: list[str] = []
        pending: list[str] = []
        reverify_required = False
        for group in sorted(self.ledger.groups()):
            mark = self.ledger.conflict_mark(group)
            if mark is None:
                continue
            live = self.ledger.live_members(group)
            post_mark_vi = [e for e in live
                            if e.provenance == VERIFIED_INTERVENTION and e.seq > mark]
            if post_mark_vi:
                winner = max(post_mark_vi, key=lambda e: e.seq)   # latest re-verification wins
                losers = tuple(e.claim_id for e in live if e.claim_id != winner.claim_id)
                self.ledger.demote(losers)
                self.ledger.clear_conflict(group)
                resolved.append(group)
                continue
            vi_live = [e for e in live if e.provenance == VERIFIED_INTERVENTION]
            if len(vi_live) >= 2:
                # two verified truths cannot coexist: the world moved — stale BOTH, force
                # re-verification, never silently prefer either (formal model I10)
                self.ledger.demote(tuple(e.claim_id for e in vi_live))
                self.ledger.clear_conflict(group)
                reverify_required = True
                resolved.append(group)
                continue
            pending.append(group)
        return {"resolved": resolved, "pending": pending,
                "reverify_required": reverify_required}
