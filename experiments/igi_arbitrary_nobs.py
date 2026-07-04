"""Big-n dip FIX via n_obs scaling (RR-0044 bet: OLS fit bias shrinks ~1/sqrt(n_obs), so truth
self-rejection and thus false-pruning should vanish with more obs samples for more parents). Same
big-n random domains; sweep n_obs in {400,1200,2400} (fresh draws, not repetition). Measures truth
self-rejection rate and identification. No freeze — mechanism-calibration for next session's n_obs=c*n."""
from __future__ import annotations

import json
import statistics

import experiments.igi_e2e_2 as base
from experiments.igi_arbitrary_bign import BigEnv
from experiments.igi_e2e_2 import P
from aac.e2e_agent import run
from aac.structure_consistency import fit_mechanisms, predict_do_means

NOBS = [400, 1200, 2400]
RUNS = [130, 131]


def truth_self_reject(env, rs):
    mech = fit_mechanisms(env.n, env.pool[env.truth_index], env.obs(rs))
    fails = 0
    for k in range(env.n):
        pred = predict_do_means(env.n, env.pool[env.truth_index], mech, k, 2.0)
        meas = env.do_rows(k, rs, k)
        mm = [statistics.mean(r[j] for r in meas) for j in range(env.n)]
        if max(abs(pred[j] - mm[j]) for j in range(env.n)) > 0.5:
            fails += 1
    return fails


def collect_big():
    d, s = [], 30000
    while len(d) < 20 and s < 30800:
        try:
            e = BigEnv(s)
        except Exception:
            s += 1; continue
        s += 1
        if e.n >= 9:
            d.append(e)
    return d


def main():
    keep = P["n_obs"]
    out = {}
    for nobs in NOBS:
        P["n_obs"] = nobs
        domains = collect_big()
        import math
        ids, sr = [], []
        for env in domains:
            budget = math.ceil(math.log2(len(env.pool))) + 3
            for rs in RUNS:
                obs = env.obs(rs)
                r1 = run(env.n, env.pool, env.truth_index, obs,
                         lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                         env.target, env.band, budget, P["grid"], seed=rs)
                ids.append(1.0 if (r1.identified and r1.correct_structure) else 0.0)
                sr.append(truth_self_reject(env, rs))
        out[f"n_obs_{nobs}"] = {"n_domains": len(domains),
                                "identification_n9plus": round(statistics.mean(ids), 3),
                                "mean_truth_self_reject_donodes": round(statistics.mean(sr), 2)}
        print(nobs, json.dumps(out[f"n_obs_{nobs}"]))
    P["n_obs"] = keep
    ids = [out[f"n_obs_{n}"]["identification_n9plus"] for n in NOBS]
    out["dip_closes_with_samples"] = bool(ids[-1] >= 0.80 and ids[-1] > ids[0] + 0.10)
    open("experiments/igi_arbitrary_nobs.result.json", "w").write(json.dumps(out, indent=2))
    print("dip closes with n_obs:", out["dip_closes_with_samples"], "id curve:", ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
