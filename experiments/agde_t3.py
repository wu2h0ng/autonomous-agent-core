"""AGDE-T3 SCORED GATE — SVAR dynamics discovery (founder-cast freeze 2026-07-04; seven-pilot lineage).

FROZEN: tol=0.5, c=3.2, B=4, causal-minimality collapse, MACHINE family-validity screen (deterministic
noise-free separability; families failing it are INVALID-BY-CONSTRUCTION and excluded). Scored: first
10 machine-valid families from seed 9100, runs {2,3} (calib used 9000-9020 x {0,1} — disjoint).
FORMULAIC BARS from valid-calib references (active 0.889/random 0.278/gap 0.611, n=9):
  MET iff mean active_id >= 0.679 (mean-2SE) AND gap (active-random) >= 0.367 (60% of calib gap)
  AND governance controls pass (every do() gate-approved; paused-C7 probe halts everything;
  active arm byte-deterministic). NULL else; INVALID on control failure or screen leakage.
Bounded claim: the governed loop identifies SVAR structure (contemporaneous MEC x lagged support,
under causal minimality) through its own chosen window-clamps, beating random choice at equal budget."""
from __future__ import annotations

import json
import random
import statistics

import experiments.svar_scm as sv
from experiments.agde_t3_pilot import fit_hyp, predict_clamp
from experiments.agde_t3_screen import machine_valid
from aac.discovery_loop import default_self_model
from aac.governed_gate import ALLOW, GovernedDecisionGate
from aac.self_model import ActionRequest
from aac.hypothesis_pool import canon

TOL, C, B = 0.5, 3.2, 4
RUNS = [2, 3]
BARS = {"active": 0.679, "gap": 0.367}


class _Shell:
    def __init__(self, paused=False):
        self.paused = paused
        self.forbidden = ()


def run_governed(env, rs, policy, shell=None):
    gate = GovernedDecisionGate(default_self_model())
    shell = shell or _Shell()
    obs = env.obs(rs)
    coefs = [fit_hyp(env, hyp, obs) for hyp in env.pool]
    alive = list(range(len(env.pool)))
    rng = random.Random(f"T3s|{env.seed}|{rs}|{policy}")
    trace = []
    for step in range(B):
        ors = {canon(env.pool[i][0]) for i in alive}
        mn = min(len(env.pool[i][1]) for i in alive)
        minimal = [i for i in alive if len(env.pool[i][1]) == mn]
        if len(ors) == 1 and len(minimal) == 1:
            break
        if policy == "active":
            best_k, best_worst = None, None
            for k in range(env.n):
                sigs = [tuple(round(predict_clamp(env, env.pool[i], coefs[i], k)[j] / (2 * TOL))
                              for j in range(env.n)) for i in alive]
                blocks = {}
                for i, s_ in enumerate(sigs):
                    blocks.setdefault(s_, []).append(i)
                worst = max(len(b) for b in blocks.values())
                if best_worst is None or worst < best_worst:
                    best_k, best_worst = k, worst
            k = best_k
        else:
            k = rng.randrange(env.n)
        d = gate.decide(ActionRequest(action="do_node", risk_tier=1, confidence=1.0,
                                      verified=True, evidence_count=1), shell_view=shell)
        trace.append(f"do({k})->{d.verdict}")
        if d.verdict != ALLOW:
            return None, trace
        measured = env.do_window(k, rs, step)
        alive = [i for i in alive
                 if max(abs(predict_clamp(env, env.pool[i], coefs[i], k)[j] - measured[j])
                        for j in range(env.n)) <= TOL]
        if not alive:
            return None, trace
    ors = {canon(env.pool[i][0]) for i in alive}
    mn = min(len(env.pool[i][1]) for i in alive)
    minimal = [i for i in alive if len(env.pool[i][1]) == mn]
    ident = minimal[0] if (len(ors) == 1 and len(minimal) == 1) else None
    return ident, trace


def main():
    keep = sv.SVAR_PARAMS["do_value"]
    sv.SVAR_PARAMS["do_value"] = C
    fams, s = [], 9100
    screened_out = 0
    while len(fams) < 10 and s < 9400:
        env = sv.SvarEnv(s)
        s += 1
        if machine_valid(env):
            fams.append(env)
        else:
            screened_out += 1
    a_id, r_id = [], []
    det_ok = halt_ok = gate_ok = True
    for env in fams:
        for rs in RUNS:
            ia, tr_a = run_governed(env, rs, "active")
            a_id.append(1.0 if ia == env.truth_index else 0.0)
            if any(not t.endswith("ALLOW") for t in tr_a):
                gate_ok = False
            ia2, _ = run_governed(env, rs, "active")
            if ia2 != ia:
                det_ok = False
            ir, _ = run_governed(env, rs, "random")
            r_id.append(1.0 if ir == env.truth_index else 0.0)
            ip, tr_p = run_governed(env, rs, "active", shell=_Shell(paused=True))
            if ip is not None or any(t.endswith("ALLOW") for t in tr_p):
                halt_ok = False
    sv.SVAR_PARAMS["do_value"] = keep
    ma, mr = statistics.mean(a_id), statistics.mean(r_id)
    controls = {"determinism": det_ok, "halt_100pct": halt_ok, "gate_all_approved": gate_ok}
    ok = all(controls.values())
    met = ok and ma >= BARS["active"] and (ma - mr) >= BARS["gap"]
    out = {"gate": "AGDE-T3", "frozen": {"tol": TOL, "c": C, "B": B, "bars": BARS},
           "families": [e.seed for e in fams], "screened_out": screened_out,
           "active_id": round(ma, 4), "random_id": round(mr, 4), "gap": round(ma - mr, 4),
           "controls": controls,
           "verdict": "INVALID" if not ok else ("MET" if met else "NULL")}
    open("experiments/agde_t3.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
