"""nonlinear_discovery_diagnosis — localize the OPEN nonlinear-discovery failure (RR-0046 §16: tanh id
0.167-0.333; skeleton-proposer and saturation fixes already refuted). Two candidates remain:
  (B) minimality breakdown: under a nonlinear basis a spurious edge gets small-but-NONZERO weight, so the
      truth may not be the UNIQUE minimal survivor (or a non-truth wins). Instrument every failure like the
      big-n / open-world diagnostics: truth_pruned? truth_in_survivors? unique_min? nontruth_min_wins?
  (A) mean-field do-propagation error: predict_do_means_nl uses f(E[parents]) but the true do-mean is
      E[f(parents)]; the bias could false-reject the truth. Tested by swapping in a MONTE-CARLO do-predictor
      (sample fitted residuals, propagate through the nonlinear mechanism, average) and re-measuring id.
Measure first, then fix the mode the data points to. NOT a freeze; toy-scale diagnosis."""
from __future__ import annotations

import json
import math
import random
import statistics

from aac.structure_consistency import _topo
from aac.structure_nonlinear import fit_mechanisms_nl, predict_do_means_nl, prune_nl, _basis, Exhausted
from aac.hypothesis_pool import canon
from experiments.openworld_skeleton_pilot import propose_skeleton, subset_pool
from experiments.universality_zero_rebuild import _make_variant

N = 5
C_NOBS = 300
TH = 0.05
C = 2.0
TOL = 0.6


def _edges(pa):
    return sum(len(v) for v in pa.values())


def _resid_stds(n, pa, obs, mech):
    """per-node residual std of the nonlinear basis fit (for the Monte-Carlo propagator)."""
    out = {}
    for j in range(n):
        w, parents, typ = mech[j]
        if typ == "root":
            m = w
            out[j] = math.sqrt(sum((r[j] - m) ** 2 for r in obs) / max(1, len(obs) - 1))
        else:
            preds = [w[0] + sum(w[i + 1] * f for i, f in enumerate(_basis([r[p] for p in parents])))
                     for r in obs]
            out[j] = math.sqrt(sum((obs[t][j] - preds[t]) ** 2 for t in range(len(obs)))
                               / max(1, len(obs) - len(w)))
    return out


def predict_do_montecarlo(n, pa, mech, rstd, k, c, draws=200):
    """Monte-Carlo do-mean: sample node noise, propagate through the NONLINEAR mechanism, average (correct
    E[f(X)] instead of mean-field f(E[X]))."""
    order = _topo(n, pa)
    acc = [0.0] * n
    for d in range(draws):
        rng = random.Random(f"mc|{k}|{c}|{d}")
        x = [0.0] * n
        for j in order:
            if j == k:
                x[j] = c
                continue
            w, parents, typ = mech[j]
            if typ == "root":
                x[j] = w + rng.gauss(0, rstd.get(j, 0.0))
            else:
                feats = _basis([x[p] for p in parents])
                x[j] = w[0] + sum(w[i + 1] * feats[i] for i in range(len(feats))) + rng.gauss(0, rstd.get(j, 0.0))
        for j in range(n):
            acc[j] += x[j]
    return [a / draws for a in acc]


def _govern(env, pool, obs, predict_fn, prune_fn, mechs, rstd_list=None):
    """instrumented govern-to-fixedpoint; returns (survivors, truth_index, truth_pruned_step)."""
    n = env.n
    ti = next((i for i, h in enumerate(pool) if canon(h) == canon(env.true_pa)), None)
    alive = list(range(len(pool)))
    budget = math.ceil(math.log2(max(2, len(pool)))) + 3
    tp = None
    for step in range(budget):
        if len(alive) <= 1:
            break
        best_k, best_worst = None, None
        for kk in range(n):
            blocks = {}
            for idx in alive:
                pv = (predict_fn(n, pool[idx], mechs[idx], rstd_list[idx], kk, C) if rstd_list
                      else predict_fn(n, pool[idx], mechs[idx], kk, C))
                sig = tuple(round(pv[j] / (2 * TOL)) for j in range(n))
                blocks.setdefault(sig, []).append(idx)
            worst = max(len(b) for b in blocks.values())
            if best_worst is None or worst < best_worst:
                best_k, best_worst = kk, worst
        if best_worst == len(alive):
            break
        rows = env.do(best_k, step)
        before = list(alive)
        try:
            if rstd_list:
                keep, _ = prune_fn(n, [pool[i] for i in alive], [mechs[i] for i in alive],
                                   [rstd_list[i] for i in alive], best_k, C, rows, TOL)
            else:
                keep, _ = prune_fn(n, [pool[i] for i in alive], [mechs[i] for i in alive], best_k, C, rows, TOL)
            alive = [alive[i] for i in keep]
        except Exhausted:
            if ti in before and tp is None:
                tp = step
            alive = []
            break
        if ti in before and ti not in alive and tp is None:
            tp = step
        if not alive:
            break
    return alive, ti, tp


def _prune_mc(n, survivors, mechs, rstds, k, c, do_rows, tol):
    measured = [sum(r[j] for r in do_rows) / len(do_rows) for j in range(n)]
    keep, kill = [], []
    for i, (pa, mech, rstd) in enumerate(zip(survivors, mechs, rstds)):
        pred = predict_do_montecarlo(n, pa, mech, rstd, k, c)
        (keep if max(abs(pred[j] - measured[j]) for j in range(n)) <= tol else kill).append(i)
    if not keep:
        raise Exhausted("all refuted (mc)")
    return keep, kill


def main():
    envs, seed = [], 500
    while len(envs) < 20:
        try:
            e = _make_variant("tanh_nonlinear", seed, N)
            if e.truth_index is not None and len(e.pool) >= 2:
                envs.append(e)
        except Exception:
            pass
        seed += 1

    modes = {"truth_pruned": 0, "truth_not_unique_min": 0, "nontruth_min_wins": 0, "ok": 0}
    id_mf, id_mc = [], []
    for e in envs:
        obs = e.obs(7, C_NOBS)
        pool = subset_pool(N, propose_skeleton(obs, N, TH))
        mechs = [fit_mechanisms_nl(N, pa, obs) for pa in pool]
        # --- mean-field arm (the current organ) ---
        alive, ti, tp = _govern(e, pool, obs, predict_do_means_nl, prune_nl, mechs)
        es = [(_edges(pool[i]), i) for i in alive]
        pick = None
        if es:
            mn = min(x for x, _ in es)
            minimal = [i for x, i in es if x == mn]
            pick = minimal[0] if len(minimal) == 1 else None
        correct = pick is not None and pick == ti
        id_mf.append(1.0 if correct else 0.0)
        if not correct:
            if ti not in alive:
                modes["truth_pruned"] += 1
            else:
                mn = min(_edges(pool[i]) for i in alive)
                uniq = _edges(pool[ti]) == mn and sum(1 for i in alive if _edges(pool[i]) == mn) == 1
                if not uniq:
                    modes["truth_not_unique_min"] += 1
                else:
                    modes["nontruth_min_wins"] += 1
        else:
            modes["ok"] += 1
        # --- Monte-Carlo arm (tests candidate A: mean-field bias) ---
        rstds = [_resid_stds(N, pa, obs, m) for pa, m in zip(pool, mechs)]
        aliveM, tiM, _ = _govern(e, pool, obs, predict_do_montecarlo, _prune_mc, mechs, rstds)
        esM = [(_edges(pool[i]), i) for i in aliveM]
        pickM = None
        if esM:
            mnM = min(x for x, _ in esM)
            minM = [i for x, i in esM if x == mnM]
            pickM = minM[0] if len(minM) == 1 else None
        id_mc.append(1.0 if (pickM is not None and pickM == tiM) else 0.0)

    out = {"gate": "nonlinear-discovery-diagnosis", "n": N, "n_domains": len(envs),
           "id_mean_field": round(statistics.mean(id_mf), 3),
           "id_monte_carlo": round(statistics.mean(id_mc), 3),
           "failure_modes_mean_field": modes}
    out["monte_carlo_lift"] = round(out["id_monte_carlo"] - out["id_mean_field"], 3)
    dominant = max(("truth_pruned", "truth_not_unique_min", "nontruth_min_wins"), key=lambda k: modes[k])
    out["dominant_failure_mode"] = dominant
    out["conclusion"] = (
        f"dominant nonlinear-discovery failure = {dominant}. "
        + ("MC lift " + str(out["monte_carlo_lift"]) + " -> mean-field do-propagation bias is "
           + ("A REAL cause (candidate A)" if out["monte_carlo_lift"] >= 0.15 else "NOT the main cause")) + ". "
        + ("minimality-breakdown (candidate B) confirmed: truth survives but is not uniquely minimal / a "
           "non-truth wins -> nonlinear spurious edges carry nonzero basis weight, breaking the linear-case "
           "'truth = unique minimal' property."
           if dominant in ("truth_not_unique_min", "nontruth_min_wins") else
           "false-rejection dominates (like big-n): the truth is pruned -> fit/propagation error, not minimality."))
    open("experiments/nonlinear_discovery_diagnosis.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
