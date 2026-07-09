"""IGI-REAL-SACHS-2 — real biology with an INTERVENTIONAL ground truth (the day's law applied to the
真实域 gap): SACHS-2 replaces the imperfect human-CONSENSUS DAG (which SACHS-1's aggregate NULL was
dominated by) with the operational definition of causal ancestry — do(X) significantly shifts T's
distribution. Truth is now the WORLD's answer (held-out interventional split), not a contested paper.

The question this isolates: given a TRUSTED interventional truth, does the governed ACTIVE selection
beat the confounded CORRELATIONAL prior on real data — i.e., is the 'strong' commitment (causal not
correlational) real on real biology once the referee is the world? Split the real interventional rows
50/50: DISCOVERY half (the agent chooses which do() to consult, budgeted) vs TRUTH half (defines
ancestry by a held-out effect test, no agent access). Same governed machinery, same data.

Frozen decision: PASS iff ACTIVE ancestry-F1 vs interventional-truth >= CORREL + 0.15 AND >= RANDOM AND
governance passes. Budget 3; effect threshold 0.30 on the DISCOVERY half; truth threshold 0.30 on the
TRUTH half. Honest scope: interventional-truth is the RIGHT causal referee but only covers the 5
intervenable nodes' ancestry of the 6 targets; still real data, still not live actuation (seam item)."""
from __future__ import annotations

import json
import random
import statistics

from experiments.sachs_task import PROTEINS, INTERVENABLE, load_int, load_obs, correlation
from aac.governed_gate import GovernedDecisionGate, ALLOW
from aac.discovery_loop import default_self_model
from aac.self_model import ActionRequest

THR = 0.30
BUDGET = 3
TARGETS = [p for p in PROTEINS if p not in INTERVENABLE]


class _Shell:
    def __init__(self, paused=False):
        self.paused = paused; self.forbidden = ()


def _split(intdata, seed=7):
    by = {"base": [], **{n: [] for n in INTERVENABLE}}
    inv = {code: n for n, code in INTERVENABLE.items()}
    for v, c in intdata:
        if c == 0:
            by["base"].append(v)
        elif c in inv:
            by[inv[c]].append(v)
    r = random.Random(seed)
    disc, truth = {}, {}
    for k, rows in by.items():
        rr = list(rows); r.shuffle(rr)
        h = len(rr) // 2
        disc[k], truth[k] = rr[:h], rr[h:]
    return disc, truth


def eff(split, tidx, node):
    base = [v[tidx] for v in split["base"]][:400]
    samp = [v[tidx] for v in split[node]][:400]
    if len(base) < 2 or len(samp) < 2:
        return 0.0
    sd = (statistics.pstdev(base) + statistics.pstdev(samp)) / 2 or 1e-9
    return abs(statistics.mean(samp) - statistics.mean(base)) / sd


def run_target(disc, obs, target, policy, shell=None):
    gate = GovernedDecisionGate(default_self_model())
    shell = shell or _Shell()
    tidx = PROTEINS.index(target)
    cands = [n for n in INTERVENABLE if n != target]
    rng = random.Random(f"s2|{target}|{policy}")
    de = {n: eff(disc, tidx, n) for n in cands}
    if policy == "correl":
        cor = {n: abs(correlation(obs, tidx, PROTEINS.index(n))) for n in cands}
        thr = statistics.median(cor.values())
        return {n for n in cands if cor[n] > thr}, []
    order = sorted(cands, key=lambda n: -de[n]) if policy == "active" else rng.sample(cands, len(cands))
    pred, trace = set(), []
    for n in order[:BUDGET]:
        d = gate.decide(ActionRequest(action="do_node", risk_tier=1, confidence=1.0,
                                      verified=True, evidence_count=1), shell_view=shell)
        trace.append(f"do({n})->{d.verdict}")
        if d.verdict != ALLOW:
            return set(), trace
        if de[n] >= THR:
            pred.add(n)
    return pred, trace


def f1(pred, truth):
    if not pred and not truth:
        return 1.0
    tp = len(pred & truth)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(truth) if truth else 1.0
    return 2 * p * r / (p + r) if (p + r) else 0.0


def main():
    obs = load_obs()
    disc, truthsplit = _split(load_int())
    scores = {"active": [], "random": [], "correl": []}
    halt_ok = det_ok = gate_ok = True
    detail = {}
    for target in TARGETS:
        tidx = PROTEINS.index(target)
        truth = {n for n in INTERVENABLE if n != target and eff(truthsplit, tidx, n) >= THR}
        detail[target] = {"interventional_truth": sorted(truth)}
        for policy in scores:
            pred, tr = run_target(disc, obs, target, policy)
            scores[policy].append(f1(pred, truth))
            if policy == "active":
                detail[target]["active_pred"] = sorted(pred)
                if any(not t.endswith("ALLOW") for t in tr):
                    gate_ok = False
                if run_target(disc, obs, target, "active")[0] != pred:
                    det_ok = False
                pr, trp = run_target(disc, obs, target, "active", shell=_Shell(paused=True))
                if pr or any(t.endswith("ALLOW") for t in trp):
                    halt_ok = False
    m = {k: round(statistics.mean(v), 3) for k, v in scores.items()}
    controls = {"halt_100pct": halt_ok, "determinism": det_ok, "gate_all_approved": gate_ok}
    ok = all(controls.values())
    met = ok and m["active"] >= m["correl"] + 0.15 and m["active"] >= m["random"]
    out = {"gate": "IGI-REAL-SACHS-2", "referee": "held-out interventional truth (not consensus DAG)",
           "ancestry_F1": m, "per_target": detail, "controls": controls,
           "verdict": "INVALID" if not ok else ("MET" if met else "NULL")}
    open("experiments/igi_real_sachs2.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "per_target"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
