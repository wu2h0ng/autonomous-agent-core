"""E2EAgent — the first END-TO-END integrated governed-intelligence loop (IGI-E2E-1).

One run() wires every station that previously passed its own gate, with ZERO environment-specific
constants (the no-rebuild claim at toy scale):

  terminal preference (target node, band)             [supplied — bounded goal-formation, disclosed]
    -> EPISTEMIC SUBGOAL (self-generated): structure unknown -> choose own experiments
         AGDE discovery: min-max chooser -> GovernedDecisionGate -> do() -> discrete prune -> ledger
    -> INSTRUMENTAL SUBGOAL (self-generated): pick the action the DISCOVERED model predicts achieves
         the preference (deterministic argmin over a fixed action grid; gate-checked; budget-capped)
    -> ACT + LEARN FROM CONSEQUENCE: execute, measure the realized outcome, write the result to the
         belief ledger (achieved claim VERIFIED_INTERVENTION; miss recorded honestly)
    -> CORRECTABLE THROUGHOUT: a paused C7 shell halts any station's action; budget is hard.

Everything the agent believes is readable in the ledger trace at every step (inspectability)."""
from __future__ import annotations

from dataclasses import dataclass, field

from aac.belief_ledger import BeliefLedger
from aac.governed_gate import ALLOW, GovernedDecisionGate
from aac.intervention_chooser import choose
from aac.self_model import ActionRequest
from aac.discovery_loop import default_self_model
from aac.structure_consistency import Exhausted, fit_mechanisms, predict_do_means, prune


@dataclass
class E2EResult:
    identified: bool
    correct_structure: bool
    acted: bool
    achieved: bool
    outcome: float | None
    interventions: list
    action: tuple | None
    gate_trace: list
    halted_by_shell: bool = False
    ledger: BeliefLedger = field(default=None, repr=False)


class _ShellView:
    def __init__(self, paused=False):
        self.paused = paused
        self.forbidden = ()


def run(n, pool, truth_index, obs_rows, env_do, env_act, target, band, discovery_budget,
        action_grid, seed=0, tol=0.6, c=2.0, shell=None, cached_structure=None):
    """env_do(k, step)->rows (discovery); env_act(node, value)->realized target value (single governed
    action in the world). pool = hypothesis space (from the skeleton, no env constants). shell = C7 view;
    if paused at any point, the agent halts (correctability is unconditional)."""
    gate = GovernedDecisionGate(default_self_model())
    ledger = BeliefLedger()
    shell = shell or _ShellView()
    mechs = [fit_mechanisms(n, pa, obs_rows) for pa in pool]
    baselines = [predict_do_means(n, pa, m, -1, 0.0) for pa, m in zip(pool, mechs)]
    ids = [f"structure:h{i}" for i in range(len(pool))]
    for cid in ids:
        ledger.record_unidentified(cid, group="structure")
    alive = list(range(len(pool)))
    trace, done = [], []

    # ---- KNOWLEDGE REUSE (corrigible, never blind): a cached VERIFIED structure from a previous task
    # in this environment is re-confirmed with ONE do() (the chooser's best split) before being trusted;
    # if the world changed, the confirmation prunes the cache away and full discovery resumes. ----
    if cached_structure is not None and cached_structure in alive and discovery_budget >= 1:
        k = choose(n, [pool[i] for i in alive], [mechs[i] for i in alive], list(range(n)), c,
                   [baselines[i] for i in alive], tol)
        d = gate.decide(ActionRequest(action="do_node", risk_tier=1, confidence=1.0,
                                      verified=True, evidence_count=1), shell_view=shell)
        trace.append(f"confirm-do({k})->{d.verdict}")
        if d.verdict != ALLOW:
            return E2EResult(False, False, False, False, None, done, None, trace,
                             halted_by_shell=getattr(shell, "paused", False), ledger=ledger)
        rows = env_do(k, 0)
        try:
            keep, kill = prune(n, [pool[i] for i in alive], [mechs[i] for i in alive], k, c, rows, tol)
        except Exhausted:
            keep, kill = [], list(range(len(alive)))
        ledger.demote(tuple(ids[alive[i]] for i in kill))
        alive = [alive[i] for i in keep]
        done.append(k)
        if not alive:                # confirmation refuted the ENTIRE pool -> fail closed, honest
            return E2EResult(False, False, False, False, None, done, None, trace, ledger=ledger)
        if alive == [cached_structure]:
            pass                     # cache CONFIRMED with 1 intervention -> skip to action
        # else: cache refuted or not isolated -> fall through to full discovery on the survivors

    # ---- epistemic subgoal: identify structure by choosing own experiments ----
    for step in range(discovery_budget):
        if len(alive) <= 1:
            break
        k = choose(n, [pool[i] for i in alive], [mechs[i] for i in alive], list(range(n)), c,
                   [baselines[i] for i in alive], tol)
        d = gate.decide(ActionRequest(action="do_node", risk_tier=1, confidence=1.0,
                                      verified=True, evidence_count=1), shell_view=shell)
        trace.append(f"do({k})->{d.verdict}")
        if d.verdict != ALLOW:
            return E2EResult(False, False, False, False, None, done, None, trace,
                             halted_by_shell=getattr(shell, "paused", False), ledger=ledger)
        rows = env_do(k, step)
        try:
            keep, kill = prune(n, [pool[i] for i in alive], [mechs[i] for i in alive], k, c, rows, tol)
        except Exhausted:
            ledger.demote(tuple(ids[i] for i in alive))
            return E2EResult(False, False, False, False, None, done, None, trace, ledger=ledger)
        ledger.demote(tuple(ids[alive[i]] for i in kill))
        alive = [alive[i] for i in keep]
        done.append(k)

    identified = len(alive) == 1
    correct = identified and alive[0] == truth_index
    if identified:
        ledger.record_verified(ids[alive[0]], evidence=max(1, len(done)))
    if not identified:
        return E2EResult(False, False, False, False, None, done, None, trace, ledger=ledger)

    # ---- instrumental subgoal: use the DISCOVERED model to pick the achieving action ----
    h, m = pool[alive[0]], mechs[alive[0]]
    lo, hi = band
    best, best_dist = None, None
    for node in range(n):
        if node == target:
            continue
        for val in action_grid:
            pred = predict_do_means(n, h, m, node, val)[target]
            dist = 0.0 if lo <= pred <= hi else min(abs(pred - lo), abs(pred - hi))
            if best_dist is None or dist < best_dist or (dist == best_dist and (node, val) < best):
                best, best_dist = (node, val), dist
    d = gate.decide(ActionRequest(action="do_node", risk_tier=1, confidence=1.0,
                                  verified=True, evidence_count=max(1, len(done))), shell_view=shell)
    trace.append(f"act{best}->{d.verdict}")
    if d.verdict != ALLOW:
        return E2EResult(True, correct, False, False, None, done, best, trace,
                         halted_by_shell=getattr(shell, "paused", False), ledger=ledger)

    # ---- act in the world + learn from the consequence ----
    outcome = env_act(*best)
    achieved = lo <= outcome <= hi
    if achieved:
        ledger.record_verified(f"outcome:{target}:in_band", evidence=1)
    else:
        ledger.record_unidentified(f"outcome:{target}:in_band", group="outcome")   # honest miss
    return E2EResult(True, correct, True, achieved, outcome, done, best, trace, ledger=ledger)
