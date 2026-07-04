"""AGDE-T3 COST/GAP PILOT (calibration only, no freeze): with the SOUND exact predictor, measure on
calib families: active-vs-random identification and cost at candidate budgets B in {3,4,5,6}, tol=0.5.
Feeds next session's bar-setting directly. Loop = clamp-signature min-max chooser + trajectory verifier."""
from __future__ import annotations

import json
import random
import statistics

from experiments.svar_scm import SvarEnv, SVAR_PARAMS
from experiments.agde_t3_pilot import fit_hyp, predict_clamp

TOL = 0.5
BUDGETS = [3, 4, 5, 6]
FAMS = list(range(9000, 9006))
RUNS = [0, 1]


def signatures(env, hyps, coefs_list, k):
    sigs = []
    for hyp, coefs in zip(hyps, coefs_list):
        pred = predict_clamp(env, hyp, coefs, k)
        sigs.append(tuple(round(pred[j] / (2 * TOL)) for j in range(env.n)))
    return sigs


def run_t3(env, rs, budget, policy):
    obs = env.obs(rs)
    coefs = [fit_hyp(env, hyp, obs) for hyp in env.pool]
    alive = list(range(len(env.pool)))
    rng = random.Random(f"T3run|{env.seed}|{rs}|{policy}")
    cost = 0
    for step in range(budget):
        if len(alive) <= 1:
            break
        if policy == "active":
            best_k, best_worst = None, None
            for k in range(env.n):
                sigs = signatures(env, [env.pool[i] for i in alive], [coefs[i] for i in alive], k)
                blocks = {}
                for i, s_ in enumerate(sigs):
                    blocks.setdefault(s_, []).append(i)
                worst = max(len(b) for b in blocks.values())
                if best_worst is None or worst < best_worst:
                    best_k, best_worst = k, worst
            k = best_k
        else:
            k = rng.randrange(env.n)
        measured = env.do_window(k, rs, step)
        cost += 1
        keep = []
        for i in alive:
            pred = predict_clamp(env, env.pool[i], coefs[i], k)
            if max(abs(pred[j] - measured[j]) for j in range(env.n)) <= TOL:
                keep.append(i)
        if not keep:
            return None, cost
        alive = keep
    return (alive[0] if len(alive) == 1 else None), cost


def main():
    envs = [SvarEnv(s) for s in FAMS]
    out = {"tol": TOL, "families": len(envs), "pool": len(envs[0].pool), "budgets": {}}
    for B in BUDGETS:
        a_id, a_cost, r_id = [], [], []
        for env in envs:
            for rs in RUNS:
                ia, ca = run_t3(env, rs, B, "active")
                ok_a = ia is not None and ia == env.truth_index
                a_id.append(1.0 if ok_a else 0.0)
                if ok_a:
                    a_cost.append(ca)
                ir, _ = run_t3(env, rs, B, "random")
                r_id.append(1.0 if (ir is not None and ir == env.truth_index) else 0.0)
        out["budgets"][B] = {"active_id": round(statistics.mean(a_id), 3),
                             "active_cost_when_id": round(statistics.mean(a_cost), 2) if a_cost else None,
                             "random_id": round(statistics.mean(r_id), 3),
                             "gap": round(statistics.mean(a_id) - statistics.mean(r_id), 3)}
        print(B, json.dumps(out["budgets"][B]))
    open("experiments/agde_t3_costgap.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "budgets"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
