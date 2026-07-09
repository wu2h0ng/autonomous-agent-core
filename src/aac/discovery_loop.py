"""DiscoveryLoop — AGDE-1's governed active-discovery cycle (packet §3):
proposer(enumerated pool) -> verifier(structure_consistency PRUNE) -> chooser(policy; ACTIVE = min-max)
-> executor(GovernedDecisionGate.decide on every do() proposal; hard budget) -> BeliefLedger transitions
-> loop. Fail-closed: budget out or Exhausted -> UNIDENTIFIED (never coerced). do() information enters
ONLY as discrete prune operations (RR-0044 typed routing)."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from aac.belief_ledger import BeliefLedger
from aac.governed_gate import ALLOW, GovernedDecisionGate
from aac.intervention_chooser import choose, partition_blocks
from aac.self_model import ActionRequest, AgentSelfModel
from aac.structure_consistency import Exhausted, fit_mechanisms, predict_do_means, prune


def _no_do_means(n, pa, mech):
    return predict_do_means(n, pa, mech, k=-1, c=0.0)   # k=-1 never matches a node -> pure propagation


@dataclass
class LoopResult:
    survivors: list
    identified: bool
    correct: bool
    steps_to_id: int          # first step count when a unique survivor appeared; -1 if never
    interventions: list[int]  # approved+executed do() nodes, in order
    gate_trace: list[str]
    outcome: str              # IDENTIFIED | UNIDENTIFIED | EXHAUSTED
    ledger: BeliefLedger = field(repr=False, default=None)


def default_self_model() -> AgentSelfModel:
    return AgentSelfModel(allowed_tools=frozenset({"do_node"}), denied_tools=frozenset(),
                          risk_ceiling=3, approval_required_at_or_above=4,
                          evidence_requirements={1: 1}, confidence_thresholds={1: 0.5})


def run_discovery(n, pool, obs_rows, env_do, budget, policy, seed, tol, c,
                  force_full_budget=True) -> LoopResult:
    """policy in {'active','random','roundrobin','oracle'}; env_do(k, step) -> do-regime rows;
    'oracle' requires env_do.truth_index (index into pool) — ceiling arm only."""
    gate = GovernedDecisionGate(default_self_model())
    ledger = BeliefLedger()
    mechs = [fit_mechanisms(n, pa, obs_rows) for pa in pool]
    baselines = [_no_do_means(n, pa, mech) for pa, mech in zip(pool, mechs)]
    ids = [f"structure:h{i}" for i in range(len(pool))]
    for cid in ids:
        ledger.record_unidentified(cid, group="structure")

    alive = list(range(len(pool)))
    rng = random.Random(f"AGDE1|{policy}|{seed}")
    admissible = list(range(n))
    trace, done_steps, steps_to_id = [], [], -1
    outcome = "UNIDENTIFIED"

    for step in range(budget):
        surv_pa = [pool[i] for i in alive]
        surv_me = [mechs[i] for i in alive]
        surv_bl = [baselines[i] for i in alive]
        if policy == "active":
            k = choose(n, surv_pa, surv_me, admissible, c, surv_bl, tol)
        elif policy == "random":
            k = rng.choice(admissible)
        elif policy == "roundrobin":
            k = admissible[step % len(admissible)]
        elif policy == "oracle":
            ti = getattr(env_do, "truth_index")
            best_k, best = None, None
            for kk in sorted(admissible):
                blocks = partition_blocks(n, surv_pa, surv_me, kk, c, surv_bl, tol)
                sz = next((len(b) for b in blocks.values()
                           if any(alive[i] == ti for i in b)), len(alive))
                if best is None or sz < best:
                    best_k, best = kk, sz
            k = best_k
        else:
            raise ValueError(policy)

        req = ActionRequest(action="do_node", risk_tier=1, confidence=1.0, verified=True, evidence_count=1)
        d = gate.decide(req)
        trace.append(f"do({k})->{d.verdict}")
        if d.verdict != ALLOW:                      # governance refusal is terminal, never bypassed
            outcome = "UNIDENTIFIED"
            break
        rows = env_do(k, step)
        try:
            keep, kill = prune(n, surv_pa, surv_me, k, c, rows, tol)
        except Exhausted:
            ledger.demote(tuple(ids[i] for i in alive))
            return LoopResult([], False, False, -1, done_steps + [k], trace, "EXHAUSTED", ledger)
        ledger.demote(tuple(ids[alive[i]] for i in kill))
        alive = [alive[i] for i in keep]
        done_steps.append(k)
        if len(alive) == 1 and steps_to_id < 0:
            steps_to_id = step + 1
            if not force_full_budget:
                break

    if len(alive) == 1:
        outcome = "IDENTIFIED"
        ledger.record_verified(ids[alive[0]], evidence=max(1, len(done_steps)))
    ti = getattr(env_do, "truth_index", None)
    correct = (ti is not None and alive == [ti]) if len(alive) == 1 else False
    return LoopResult([pool[i] for i in alive], len(alive) == 1, correct, steps_to_id,
                      done_steps, trace, outcome, ledger)
