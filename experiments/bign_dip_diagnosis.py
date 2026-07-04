"""bign_dip_diagnosis — INSTRUMENT the n>=8 identification dip before choosing a fix (verify, don't assert).
For each failing big-n domain, replicate the e2e discovery loop and inspect the terminal survivor set:
  - edge counts of survivors (all equal => Markov-equivalence-class; edge-minimality can't split them)
  - GENUINE interventional equivalence: does ANY (node,value) in the grid split the survivors within tol?
    (if none splits => a true equivalence class the chooser cannot break => budget is irrelevant)
  - is the truth among survivors, and is it uniquely minimal by (a) edge count, (b) any available signal?
This tells us whether AGDE-T3-style minimality collapse applies here, or whether the dip is fit-induced
(needs n_obs), NOT a knob to guess. No edit to e2e_agent.py; pure read-only replication."""
from __future__ import annotations

import json
import math
import statistics

from aac.structure_consistency import fit_mechanisms, predict_do_means, prune, Exhausted
from aac.hypothesis_pool import mec  # noqa: F401  (used via BigEnv)
from experiments.igi_arbitrary_bign import BigEnv
from experiments.igi_e2e_2 import P

TOL, C = 0.6, 2.0
GRID = P["grid"]
N_OBS = P["n_obs"]


def _edges(pa):
    return sum(len(v) for v in pa.values())


def _choose_split(n, survivors, mechs):
    """the chooser's best splitting node: the node whose do maximally partitions survivor predictions.
    returns (best_node, worst_block_size). worst_block==len(survivors) => no node splits them."""
    best_k, best_worst = None, None
    for k in range(n):
        blocks = {}
        for i, (pa, m) in enumerate(zip(survivors, mechs)):
            sig = tuple(round(predict_do_means(n, pa, m, k, C)[j] / (2 * TOL)) for j in range(n))
            blocks.setdefault(sig, []).append(i)
        worst = max(len(b) for b in blocks.values())
        if best_worst is None or worst < best_worst:
            best_k, best_worst = k, worst
    return best_k, best_worst


def _splittable(n, survivors, mechs):
    """does ANY (node,value) in the grid separate two survivors by > tol in predicted do-means?"""
    for k in range(n):
        for v in GRID:
            preds = [predict_do_means(n, pa, m, k, v) for pa, m in zip(survivors, mechs)]
            for a in range(len(preds)):
                for b in range(a + 1, len(preds)):
                    if max(abs(preds[a][j] - preds[b][j]) for j in range(n)) > TOL:
                        return True
    return False


def _run_and_inspect(env, rs):
    n, pool = env.n, env.pool
    ti = env.truth_index
    mechs = [fit_mechanisms(n, pa, env.obs(rs)) for pa in pool]
    alive = list(range(len(pool)))
    budget = math.ceil(math.log2(len(pool))) + 2
    truth_pruned_step = None            # the step at which the TRUE hypothesis is (false-)rejected
    reason = "converged"
    for step in range(budget):
        if len(alive) <= 1:
            break
        k, worst = _choose_split(n, [pool[i] for i in alive], [mechs[i] for i in alive])
        if worst == len(alive):
            reason = "fixed_point"      # chooser cannot split survivors -> budget irrelevant
            break
        rows = env.do_rows(k, rs, step)
        before = list(alive)
        try:
            keep, kill = prune(n, [pool[i] for i in alive], [mechs[i] for i in alive], k, C, rows, TOL)
            alive = [alive[i] for i in keep]
        except Exhausted:
            if ti in before and truth_pruned_step is None:
                truth_pruned_step = step
            alive = []
            reason = "exhausted"
            break
        if ti in before and ti not in alive and truth_pruned_step is None:
            truth_pruned_step = step     # the TRUTH was pruned here (false-rejection if fit-biased)
        if not alive:
            reason = "empty"
            break
    truth_alive = ti in alive
    surv = [pool[i] for i in alive] if alive else []
    surv_edges = sorted(_edges(pa) for pa in surv)
    min_e = min(surv_edges) if surv_edges else None
    truth_is_unique_min = truth_alive and _edges(pool[ti]) == min_e and surv_edges.count(min_e) == 1
    return {"identified": len(alive) == 1, "correct": len(alive) == 1 and alive[0] == ti,
            "alive": len(alive), "mec": len(pool), "n": n, "reason": reason,
            "surv_edge_counts": surv_edges, "all_equal_edges": len(set(surv_edges)) <= 1 if surv_edges else True,
            "splittable": _splittable(n, surv, [mechs[i] for i in alive]) if len(alive) > 1 else False,
            "truth_alive": truth_alive, "truth_pruned_step": truth_pruned_step,
            "truth_is_unique_min_edges": truth_is_unique_min}


def _id_at_tol(env, rs, tol):
    """rerun identification at a given prune tolerance; report (correct, truth_alive)."""
    n, pool = env.n, env.pool
    ti = env.truth_index
    mechs = [fit_mechanisms(n, pa, env.obs(rs)) for pa in pool]
    alive = list(range(len(pool)))
    budget = math.ceil(math.log2(len(pool))) + 2
    for step in range(budget):
        if len(alive) <= 1:
            break
        k, worst = _choose_split(n, [pool[i] for i in alive], [mechs[i] for i in alive])
        if worst == len(alive):
            break
        rows = env.do_rows(k, rs, step)
        try:
            keep, _ = prune(n, [pool[i] for i in alive], [mechs[i] for i in alive], k, C, rows, tol)
            alive = [alive[i] for i in keep]
        except Exhausted:
            alive = []
            break
        if not alive:
            break
    return (len(alive) == 1 and alive[0] == ti), (ti in alive)


def main():
    recs = []
    envs = []
    seed = 200
    while len(recs) < 24:
        try:
            env = BigEnv(seed)
        except Exception:
            seed += 1
            continue
        r = _run_and_inspect(env, rs=7)
        r["seed"] = seed
        recs.append(r)
        envs.append(env)
        seed += 1
    # tol-sweep: if the dip is fit-bias false-rejection, LOOSENING the prune band (carrying fit uncertainty)
    # should keep the truth alive and recover id — up to a point (too loose -> can't discriminate MEC members).
    TOLS = [0.6, 0.9, 1.2, 1.5, 2.0]
    sweep = {}
    for t in TOLS:
        cor = [_id_at_tol(e, 7, t) for e in envs]
        sweep[t] = {"id_rate": round(statistics.mean(1.0 if c else 0.0 for c, _ in cor), 3),
                    "truth_alive_rate": round(statistics.mean(1.0 if ta else 0.0 for _, ta in cor), 3)}
    fails = [r for r in recs if not r["correct"]]
    id_rate = statistics.mean(1.0 if r["correct"] else 0.0 for r in recs)
    # the decisive split: among FAILURES, was the truth false-rejected (pruned) vs surviving-but-unsplittable?
    fail_truth_pruned = sum(1 for r in fails if r.get("truth_pruned_step") is not None)
    fail_truth_survives_unsplittable = sum(1 for r in fails
                                           if r["truth_alive"] and r["alive"] > 1 and not r["splittable"])
    fail_truth_unique_min = sum(1 for r in fails if r["truth_is_unique_min_edges"])
    out = {"n_domains": len(recs), "id_rate": round(id_rate, 3), "n_fail": len(fails),
           "tol_sweep_fixed_nobs": sweep,
           "DECISIVE": {
               "fail_truth_PRUNED_false_reject": fail_truth_pruned,
               "fail_truth_survives_but_unsplittable": fail_truth_survives_unsplittable,
               "fail_truth_would_be_fixed_by_minimality": fail_truth_unique_min},
           "interpretation": ("if truth_PRUNED dominates -> minimality is WRONG/harmful (truth not among "
                              "survivors); fix is fit-bias/n_obs. if survives_but_unsplittable dominates AND "
                              "truth_unique_min -> minimality collapse is the correct fix."),
           "fail_examples": [{k: r.get(k) for k in ("seed", "n", "alive", "reason", "truth_alive",
                              "truth_pruned_step", "all_equal_edges", "splittable",
                              "truth_is_unique_min_edges")} for r in fails[:8]]}
    open("experiments/bign_dip_diagnosis.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
