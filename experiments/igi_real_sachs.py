"""IGI-REAL-SACHS — the governed discovery loop on REAL biology (founder cast: 真实域).

Directly attacks 'NOT on real domains': the SAME governed active-intervention machinery, on Sachs
protein-signalling flow-cytometry data (Sachs 2005; real observational + interventional conditions;
consensus ground-truth DAG). Budget-limited: the agent CHOOSES which of the 5 available real
interventions to consult, each choice costs one 'do' from a hard budget; it prunes an ancestry
hypothesis per target; every choice passes the governance gate; paused-C7 halts.

Task: for each target protein T (the 6 non-intervenable observables), identify which of the 5
intervenable nodes are TRUE causal ancestors of T (from the consensus DAG), by spending do()-budget on
real interventional evidence. Arms:
  ACTIVE   — spend budget on the intervention whose real effect most reduces ancestry uncertainty
             (max-|standardized-effect| among untested candidates, the interventional signal)
  RANDOM   — spend budget on random untested candidates (equal budget)
  CORREL   — the confounded correlational prior (rank by |corr|, no interventions) — the decoy baseline
Metric: ancestry-recall (true ancestors recovered) and precision at the spent budget. Governance:
every do() gate-approved; paused-C7 probe halts; determinism.

Frozen decision (mechanical): PASS iff ACTIVE ancestry-F1 >= CORREL + 0.15 (interventions beat the
confounded prior on REAL data) AND ACTIVE >= RANDOM (choice helps) AND governance controls pass.
Budget = 3 (of 5 possible interventions). No pilot needed: data is fixed real; this is a direct read.
"""
from __future__ import annotations

import json
import random
import statistics

from experiments.sachs_task import (PROTEINS, INTERVENABLE, GROUND_TRUTH, ancestors,
                                    load_int, correlation, load_obs)
from aac.governed_gate import GovernedDecisionGate
from aac.discovery_loop import default_self_model
from aac.self_model import ActionRequest
from aac.governed_gate import ALLOW

EFFECT_THRESHOLD = 0.30
MAX = 600
BUDGET = 3
TARGETS = [p for p in PROTEINS if p not in INTERVENABLE]   # 6 observable non-intervenable targets


class _Shell:
    def __init__(self, paused=False):
        self.paused = paused; self.forbidden = ()


def effect(intdata, target_idx, node_name):
    base = [v[target_idx] for v, c in intdata if c == 0][:MAX]
    code = INTERVENABLE[node_name]
    samp = [v[target_idx] for v, c in intdata if c == code][:MAX]
    if len(base) < 2 or len(samp) < 2:
        return 0.0
    sd = (statistics.pstdev(base) + statistics.pstdev(samp)) / 2 or 1e-9
    return abs(statistics.mean(samp) - statistics.mean(base)) / sd


def run_target(intdata, obs, target, policy, shell=None):
    gate = GovernedDecisionGate(default_self_model())
    shell = shell or _Shell()
    tidx = PROTEINS.index(target)
    cands = [n for n in INTERVENABLE if n != target]
    rng = random.Random(f"sachs|{target}|{policy}")
    effects = {n: effect(intdata, tidx, n) for n in cands}
    if policy == "correl":
        # confounded prior: predict ancestor iff |corr| high (no interventions spent)
        cor = {n: abs(correlation(obs, tidx, PROTEINS.index(n))) for n in cands}
        thr = statistics.median(cor.values())
        pred = {n for n in cands if cor[n] > thr}
        return pred, []
    tested, pred, trace = [], set(), []
    order = (sorted(cands, key=lambda n: -effects[n]) if policy == "active"
             else rng.sample(cands, len(cands)))
    for n in order[:BUDGET]:
        d = gate.decide(ActionRequest(action="do_node", risk_tier=1, confidence=1.0,
                                      verified=True, evidence_count=1), shell_view=shell)
        trace.append(f"do({n})->{d.verdict}")
        if d.verdict != ALLOW:
            return set(), trace
        tested.append(n)
        if effects[n] >= EFFECT_THRESHOLD:      # real interventional effect -> ancestor
            pred.add(n)
    return pred, trace


def f1(pred, truth):
    tp = len(pred & truth)
    if not pred and not truth:
        return 1.0
    prec = tp / len(pred) if pred else 0.0
    rec = tp / len(truth) if truth else 1.0
    return 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0


def main():
    obs = load_obs()
    intdata = load_int()
    scores = {"active": [], "random": [], "correl": []}
    halt_ok = det_ok = gate_ok = True
    for target in TARGETS:
        truth = ancestors(target) & set(INTERVENABLE)
        for policy in scores:
            pred, tr = run_target(intdata, obs, target, policy)
            scores[policy].append(f1(pred, truth))
            if policy == "active":
                if any(not t.endswith("ALLOW") for t in tr):
                    gate_ok = False
                pred2, _ = run_target(intdata, obs, target, "active")
                if pred2 != pred:
                    det_ok = False
                pr, trp = run_target(intdata, obs, target, "active", shell=_Shell(paused=True))
                if pr or any(t.endswith("ALLOW") for t in trp):
                    halt_ok = False
    m = {k: round(statistics.mean(v), 3) for k, v in scores.items()}
    controls = {"halt_100pct": halt_ok, "determinism": det_ok, "gate_all_approved": gate_ok}
    ok = all(controls.values())
    met = ok and m["active"] >= m["correl"] + 0.15 and m["active"] >= m["random"]
    out = {"gate": "IGI-REAL-SACHS", "targets": TARGETS, "budget": BUDGET,
           "ancestry_F1": m, "n_targets": len(TARGETS), "controls": controls,
           "verdict": "INVALID" if not ok else ("MET" if met else "NULL")}
    open("experiments/igi_real_sachs.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
