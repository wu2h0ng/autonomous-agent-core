"""AGDE-1 pre-freeze calibration + the three kill experiments (packet §7; calibration family seeds
1000.., DISJOINT from scored family seeds 100-129). Any kill fires -> back to design, nothing scored.

K1 arena-invalid: measured oracle-random gap < GAP_MIN at every B in {1,2,3}.
K2 tolerance-invalid: no tol in the sweep keeps truth alive >=99% on its own do() data while killing
   at least one wrong hypothesis under an informative do().
K3 family-scarcity: cannot assemble >=20 valid families (MEC>=4, informative fraction <=1/3).
Outputs the frozen candidates: tol, N_int, B, family list -> into the prereg."""
from __future__ import annotations

import json
import statistics

import experiments.intervention_scm as scm
from aac.discovery_loop import run_discovery
from aac.structure_consistency import Exhausted, fit_mechanisms, prune

GAP_MIN = 0.10
TOLS = [0.4, 0.6, 0.8]
N_INTS = [100, 200]
CAL_RUN_SEEDS = [0, 1, 2]


def collect_families(n_needed=25, tol=0.6, start=1000, limit=1400):
    fams, s = [], start
    while len(fams) < n_needed and s < limit:
        f = scm.Family(s)
        if scm.valid_family(f, tol):
            fams.append(f)
        s += 1
    return fams


def score(res, truth_index, pool):
    if len(res.survivors) == 0:
        return 0.0
    alive_idx = [i for i, h in enumerate(pool) if any(h is s or h == s for s in res.survivors)]
    if truth_index not in alive_idx:
        return 0.0
    return 1.0 / len(alive_idx)


def k2_tolerance(fams, n_int):
    """For each tol: truth-survival rate on its own do() data; wrong-kill achieved anywhere."""
    out = {}
    for tol in TOLS:
        surv, kills = 0, 0
        trials = 0
        for f in fams[:10]:
            obs = f.sample_obs(0)
            mechs = [fit_mechanisms(f.n, h, obs) for h in f.pool]
            for k in range(f.n):
                rows = f.sample_do(k, 0, 0, n_int)
                trials += 1
                try:
                    keep, kill = prune(f.n, f.pool, mechs, k, scm.SCM_PARAMS["do_value"], rows, tol)
                    surv += f.truth_index in keep
                    kills += len(kill) > 0
                except Exhausted:
                    pass
        out[tol] = {"truth_survival": round(surv / trials, 4), "wrong_kill_rate": round(kills / trials, 4)}
    return out


def gap_measure(fams, tol, n_int, budgets=(1, 2, 3)):
    res = {}
    for B in budgets:
        o_scores, r_scores, a_scores = [], [], []
        for f in fams:
            for rs in CAL_RUN_SEEDS:
                obs = f.sample_obs(rs)

                def env(k, step, _f=f, _rs=rs):
                    return _f.sample_do(k, _rs, step, n_int)
                env.truth_index = f.truth_index
                for pol, acc in (("oracle", o_scores), ("random", r_scores), ("active", a_scores)):
                    r = run_discovery(f.n, f.pool, obs, env, B, pol, seed=rs, tol=tol, c=scm.SCM_PARAMS["do_value"])
                    acc.append(score(r, f.truth_index, f.pool))
        res[B] = {"oracle": round(statistics.mean(o_scores), 4),
                  "random": round(statistics.mean(r_scores), 4),
                  "active_preview": round(statistics.mean(a_scores), 4),
                  "gap": round(statistics.mean(o_scores) - statistics.mean(r_scores), 4)}
    return res


def main():
    fams = collect_families()
    K3 = len(fams) >= 20
    out = {"n_valid_families": len(fams), "K3_pass": K3,
           "mec_sizes": [len(f.pool) for f in fams][:25]}
    if K3:
        out["K2_tolerance_sweep"] = {str(n): k2_tolerance(fams, n) for n in N_INTS}
        # pick provisional tol/N_int: smallest passing (truth_survival>=0.99, wrong_kill>0.2)
        chosen = None
        for n in N_INTS:
            for tol in TOLS:
                cell = out["K2_tolerance_sweep"][str(n)][tol]
                if cell["truth_survival"] >= 0.99 and cell["wrong_kill_rate"] > 0.2:
                    chosen = {"tol": tol, "n_int": n}
                    break
            if chosen:
                break
        out["K2_pass"] = chosen is not None
        out["chosen"] = chosen
        if chosen:
            gaps = gap_measure(fams, chosen["tol"], chosen["n_int"])
            out["gap_by_budget"] = gaps
            out["K1_pass"] = any(v["gap"] >= GAP_MIN for v in gaps.values())
            if out["K1_pass"]:
                out["chosen"]["B"] = max((b for b, v in gaps.items() if v["gap"] >= GAP_MIN),
                                         key=lambda b: gaps[b]["gap"])
    out["all_kills_clear"] = bool(out.get("K1_pass") and out.get("K2_pass") and K3)
    with open("experiments/agde_1_calibration.result.json", "w") as fjson:
        json.dump(out, fjson, indent=2, default=str)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
