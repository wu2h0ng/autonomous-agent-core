"""AGDE-T3 SEPARATION measurement + arithmetic derivation (calibration; no freeze, no judgment).
Measure, per calib family and do-node: distribution of max-node |pred_truth - pred_j| over j != truth
(the quantity the prune needs above tol). Predictions are ~linear in do_value -> derive the needed
do_value arithmetically: c_needed = c_now * (target_sep / median_sep), target = 2*tol. Then verify by
re-running the cost/gap pilot at the derived c (pilot v4)."""
from __future__ import annotations

import json
import statistics

import experiments.svar_scm as sv
from experiments.agde_t3_pilot import fit_hyp, predict_clamp

TOL = 0.5
FAMS = list(range(9000, 9004))


def measure_separation():
    seps = []
    for s in FAMS:
        env = sv.SvarEnv(s)
        obs = env.obs(0)
        coefs = [fit_hyp(env, hyp, obs) for hyp in env.pool]
        ct = coefs[env.truth_index]
        ht = env.pool[env.truth_index]
        for k in range(env.n):
            pt = predict_clamp(env, ht, ct, k)
            for j, (hyp, cj) in enumerate(zip(env.pool, coefs)):
                if j == env.truth_index:
                    continue
                pj = predict_clamp(env, hyp, cj, k)
                seps.append(max(abs(pt[i] - pj[i]) for i in range(env.n)))
    return seps


def main():
    seps = measure_separation()
    seps.sort()
    med = seps[len(seps) // 2]
    q25 = seps[len(seps) // 4]
    frac_above_tol = sum(1 for x in seps if x > TOL) / len(seps)
    c_now = sv.SVAR_PARAMS["do_value"]
    c_needed = round(c_now * (2 * TOL / max(med, 1e-9)), 1)
    out = {"n_pairs": len(seps), "sep_median": round(med, 3), "sep_q25": round(q25, 3),
           "frac_above_tol_now": round(frac_above_tol, 3),
           "c_now": c_now, "c_derived_for_2tol_median": c_needed}
    print(json.dumps(out, indent=2))
    # pilot v4 at the derived c (bounded to <=8.0 for sanity)
    c_use = min(c_needed, 8.0)
    sv.SVAR_PARAMS["do_value"] = c_use
    from experiments.agde_t3_costgap import run_t3
    a_id, r_id, a_cost = [], [], []
    for s in FAMS:
        env = sv.SvarEnv(s)
        for rs in (0, 1):
            ia, ca = run_t3(env, rs, 5, "active")
            ok = ia is not None and ia == env.truth_index
            a_id.append(1.0 if ok else 0.0)
            if ok:
                a_cost.append(ca)
            ir, _ = run_t3(env, rs, 5, "random")
            r_id.append(1.0 if (ir is not None and ir == env.truth_index) else 0.0)
    out["pilot_v4"] = {"do_value_used": c_use, "budget": 5,
                       "active_id": round(statistics.mean(a_id), 3),
                       "active_cost": round(statistics.mean(a_cost), 2) if a_cost else None,
                       "random_id": round(statistics.mean(r_id), 3),
                       "gap": round(statistics.mean(a_id) - statistics.mean(r_id), 3)}
    sv.SVAR_PARAMS["do_value"] = c_now
    open("experiments/agde_t3_separation.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out["pilot_v4"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
