"""AGDE-T3 PILOT (pre-freeze; pilots-before-bars rule). Measures on calib families (9000+):
K1 stability-rejection rate; K2 tolerance (truth survival on own clamp data >= 0.99 at candidate tols);
K3 Granger-vacuity: fraction of the pool resolvable from OBSERVATION alone (lag half expected to
resolve; orientation must NOT — else vacuous); t1 active cost + id rate at budget 8 (room-for-choice).
No verdicts; numbers feed next session's freeze."""
from __future__ import annotations

import json
import statistics

from experiments.svar_scm import SvarEnv, SVAR_PARAMS
from aac.structure_consistency import _ols

TOLS = [0.5, 0.7, 0.9]
BUDGET = 8


def fit_hyp(env, hyp, obs_traj):
    pa, lagset = hyp
    n = env.n
    coefs = {}
    for j in range(n):
        cps = sorted(pa.get(j, ()))
        lps = sorted(src for (src, dst) in lagset if dst == j)
        X, y = [], []
        for t in range(1, len(obs_traj)):
            X.append([obs_traj[t][p_] for p_ in cps] + [obs_traj[t - 1][s_] for s_ in lps])
            y.append(obs_traj[t][j])
        if X and X[0]:
            w = _ols(X, y)
            coefs[j] = (w[0], {("c", p_): w[1 + i] for i, p_ in enumerate(cps)} |
                        {("l", s_): w[1 + len(cps) + i] for i, s_ in enumerate(lps)})
        else:
            m = statistics.mean(r[j] for r in obs_traj)
            coefs[j] = (m, {})
    return coefs


def predict_clamp(env, hyp, coefs, k):
    pa, lagset = hyp
    n = env.n
    mean = [0.0] * n
    for _ in range(80):
        new = [0.0] * n
        for v in range(n):
            if v == k:
                new[v] = SVAR_PARAMS["do_value"]
            else:
                b0, ws = coefs[v]
                val = b0
                for (kind, src), w in ws.items():
                    val += w * (new[src] if kind == "c" and src != v else mean[src] if kind == "l" else
                                new[src])
                new[v] = val
        # contemporaneous propagation needs topo consistency; iterate inner fixed point
        for _ in range(6):
            nxt = [0.0] * n
            for v in range(n):
                if v == k:
                    nxt[v] = SVAR_PARAMS["do_value"]
                else:
                    b0, ws = coefs[v]
                    val = b0
                    for (kind, src), w in ws.items():
                        val += w * (nxt[src] if kind == "c" else mean[src])
                        # note: use current inner iterate for contemporaneous
                    nxt[v] = val
            new = nxt
        mean = new
    return mean


def obs_resolution(env, obs_traj, eps=0.05):
    """Fraction of pool surviving an SSE-based observational screen (min-SSE * (1+eps))."""
    sses = []
    for hyp in env.pool:
        coefs = fit_hyp(env, hyp, obs_traj)
        sse = 0.0
        for t in range(1, len(obs_traj)):
            for j in range(env.n):
                b0, ws = coefs[j]
                pred = b0
                for (kind, src), w in ws.items():
                    pred += w * (obs_traj[t][src] if kind == "c" else obs_traj[t - 1][src])
                sse += (obs_traj[t][j] - pred) ** 2
        sses.append(sse)
    m = min(sses)
    surv = [i for i, s in enumerate(sses) if s <= m * (1 + eps)]
    return surv


def main():
    fams = [SvarEnv(s) for s in range(9000, 9005)]
    out = {"families": len(fams), "pool_size": len(fams[0].pool)}
    # K2 tolerance: truth survival on own clamp data
    k2 = {}
    for tol in TOLS:
        ok, tot, kills = 0, 0, 0
        for env in fams[:3]:
            obs = env.obs(0)
            coefs_true = fit_hyp(env, env.pool[env.truth_index], obs)
            for k in range(env.n):
                measured = env.do_window(k, 1, k)
                pred = predict_clamp(env, env.pool[env.truth_index], coefs_true, k)
                tot += 1
                ok += max(abs(pred[j] - measured[j]) for j in range(env.n)) <= tol
        k2[tol] = round(ok / tot, 3)
    out["K2_truth_survival_by_tol"] = k2
    # K3 observational resolution
    fracs, truth_in = [], 0
    orient_resolved = 0
    from aac.hypothesis_pool import canon
    for env in fams:
        surv = obs_resolution(env, env.obs(0))
        fracs.append(len(surv) / len(env.pool))
        truth_in += env.truth_index in surv
        orients = {canon(env.pool[i][0]) for i in surv}
        orient_resolved += len(orients) == 1
    out["K3_obs_surviving_fraction"] = round(statistics.mean(fracs), 3)
    out["K3_truth_survives_obs_screen"] = f"{truth_in}/{len(fams)}"
    out["K3_orientation_resolved_by_obs_VACUITY"] = f"{orient_resolved}/{len(fams)}"
    out["kill_fired"] = bool(orient_resolved > len(fams) / 2)
    open("experiments/agde_t3_pilot.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
