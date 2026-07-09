"""GoalProposer — terminal-goal SELF-PROPOSAL under governance (IGI-E2E-3).

Constitutional form (per THE-goal invariants): "forms its own goals" and "permanently correctable"
must coexist, so terminal goals are PROPOSED by the system and pass a principal boundary check before
any action — proposal-form is the TERMINAL form, not a stopgap. The proposer is a deterministic,
contentless function of the agent's own DISCOVERED model (never truth): it enumerates the outcome
space reachable under that model and ranks candidate terminal goals by a fixed drive ordering:

  drive 1 (competence): the largest-|magnitude| reachable outcome band on the highest-leverage node
  drive 2..k: successively less extreme reachable bands (alternatives if the principal rejects)

The principal (harness) holds a FORBIDDEN ZONE (safety boundary); proposals overlapping it are
rejected and the agent must fall back to its next-ranked proposal — it never acts on a rejected goal."""
from __future__ import annotations

from aac.structure_consistency import predict_do_means


def propose_goals(n, h, mech, action_grid, band_half, max_proposals=4, exclude_nodes=()):
    """Rank candidate terminal goals (target, band, driving_action) from the DISCOVERED model.
    Deterministic; pure function of (h, mech). Returns most-extreme-first."""
    cands = []
    for target in range(n):
        if target in exclude_nodes:
            continue
        for node in range(n):
            if node == target:
                continue
            for val in action_grid:
                m = predict_do_means(n, h, mech, node, val)[target]
                cands.append((abs(m), m, target, (node, val)))
    cands.sort(key=lambda t: (-t[0], t[2], t[3]))
    out, seen = [], set()
    for _, m, target, act in cands:
        key = (target, round(m, 1))
        if key in seen:
            continue
        seen.add(key)
        out.append({"target": target, "band": (m - band_half, m + band_half), "predicted_action": act})
        if len(out) >= max_proposals:
            break
    return out


def principal_boundary(band, forbidden_abs=6.0):
    """The principal's standing safety boundary: reject any goal whose band exceeds |forbidden_abs|.
    (Harness-side stand-in for the human principal; the agent cannot modify it.)"""
    lo, hi = band
    return abs(lo) <= forbidden_abs and abs(hi) <= forbidden_abs
