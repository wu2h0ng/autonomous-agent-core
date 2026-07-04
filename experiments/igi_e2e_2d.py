"""IGI-E2E-2d — CACHE-TARGETED confirmation closes the compounding axis (fixes 2c's staleness
regression 0.667: generic pool-min-max confirms let a wrong-but-similar cache hide in a large
surviving block). New confirm rule (typed-routing shape: VERIFICATION MUST BE AIMED AT THE CLAIM
UNDER TEST): choose the do() maximizing the cache's WORST-CASE predicted separation from every
surviving alternative — the test is designed to expose exactly where the cache could hide.

Frozen decision (mechanical), space-lever arena (PathEnv MEC-75), 8 envs x 2 runs, FRESH scored seeds
3900+, runs {87,88}: ARENA-VALID iff t1 mean >= 3.5 AND t1 id >= 0.7. PASS iff saving >= 2.0 AND
achievement drop <= 0.10 AND stale-cache-refuted >= 0.8 AND new-truth id >= 0.7 AND halt 100%.
Frozen prediction: saving ~2.9 preserved (still 2 confirms); stale-refuted 0.85-1.0 (the targeted test
kills wrong-similar caches by design); new-truth id 0.6-0.8 (the live risk: rediscovery after 2 spent
confirms in a 75-space with budget 10 and fresh-seed variance). PASS ~65%."""
from __future__ import annotations

import json
import statistics

from aac.e2e_agent import run, _ShellView
from aac.hypothesis_pool import canon
from aac.intervention_chooser import choose
from aac.structure_consistency import Exhausted, fit_mechanisms, predict_do_means, prune
from experiments.igi_e2e_2 import P
from experiments.igi_e2e_2c import PerturbedPathEnv
from experiments.igi_e2e_2c2_pilot import PathEnv

RUNS = [87, 88]
N_ENVS = 8
BUDGET = 10
CONFIRMS = 2


def choose_targeted(n, cache_pos, survivors, mechs, admissible, c):
    """The cache-targeted confirm rule: maximize the cache's worst-case predicted separation from
    every surviving alternative; tie-break lowest node. Deterministic, contentless."""
    best_k, best_sep = None, None
    pred_cache = {}
    for k in admissible:
        pred_cache[k] = predict_do_means(n, survivors[cache_pos], mechs[cache_pos], k, c)
    for k in sorted(admissible):
        worst = None
        for j, (h, m) in enumerate(zip(survivors, mechs)):
            if j == cache_pos:
                continue
            pj = predict_do_means(n, h, m, k, c)
            sep = max(abs(pred_cache[k][t] - pj[t]) for t in range(n))
            worst = sep if worst is None else min(worst, sep)
        if worst is None:
            return sorted(admissible)[0]
        if best_sep is None or worst > best_sep:
            best_k, best_sep = k, worst
    return best_k


def cached_run_targeted(env, rs, cached_canon):
    obs = env.obs(rs)
    mechs = [fit_mechanisms(env.n, h, obs) for h in env.pool]
    bases = [predict_do_means(env.n, h, m, -1, 0.0) for h, m in zip(env.pool, mechs)]
    alive = list(range(len(env.pool)))
    cost = 0

    def cache_pos():
        for pos, i in enumerate(alive):
            if canon(env.pool[i]) == cached_canon:
                return pos
        return None

    for stepc in range(CONFIRMS):
        cp = cache_pos()
        if cp is None or len(alive) == 1:
            break
        k = choose_targeted(env.n, cp, [env.pool[i] for i in alive], [mechs[i] for i in alive],
                            list(range(env.n)), 2.0)
        rows = env.do_rows(k, rs, stepc)
        cost += 1
        try:
            keep, _ = prune(env.n, [env.pool[i] for i in alive], [mechs[i] for i in alive],
                            k, 2.0, rows, 0.6)
        except Exhausted:
            return None, cost, False
        alive = [alive[i] for i in keep]
    cp = cache_pos()
    if cp is not None and cost == CONFIRMS:
        return alive[cp], cost, True          # cache survived BOTH targeted tests -> trusted
    for step in range(cost, BUDGET):          # rediscovery
        if len(alive) <= 1:
            break
        k = choose(env.n, [env.pool[i] for i in alive], [mechs[i] for i in alive],
                   list(range(env.n)), 2.0, [bases[i] for i in alive], 0.6)
        rows = env.do_rows(k, rs, step)
        cost += 1
        try:
            keep, _ = prune(env.n, [env.pool[i] for i in alive], [mechs[i] for i in alive],
                            k, 2.0, rows, 0.6)
        except Exhausted:
            return None, cost, False
        alive = [alive[i] for i in keep]
    return (alive[0] if len(alive) == 1 else None), cost, False


def main():
    envs, s = [], 3900
    while len(envs) < N_ENVS and s < 4300:
        e = PathEnv(s)
        s += 1
        if e.truth_index is not None and len(e.pool) >= 40:
            envs.append(e)
    t1c, t1id, t2c, t1a, t2a = [], [], [], [], []
    stale_ref, new_id, halt_ok = [], [], True
    for env in envs:
        for rs in RUNS:
            r1 = run(env.n, env.pool, env.truth_index, env.obs(rs),
                     lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                     env.target, env.band, BUDGET, P["grid"], seed=rs, tol=0.6)
            t1id.append(1.0 if (r1.identified and r1.correct_structure) else 0.0)
            if not (r1.identified and r1.correct_structure):
                continue
            t1c.append(len(r1.interventions)); t1a.append(1.0 if r1.achieved else 0.0)
            cc = canon(env.pool[env.truth_index])
            idx, cost2, trusted = cached_run_targeted(env, rs + 100, cc)
            t2c.append(cost2)
            t2a.append(1.0 if (idx is not None and canon(env.pool[idx]) == cc) else 0.0)
            envp = PerturbedPathEnv(env.seed)
            if envp.truth_index is None or canon(envp.true_pa) == cc:
                continue
            idxp, costp, trustedp = cached_run_targeted(envp, rs + 200, cc)
            stale_ref.append(0.0 if (trustedp or (idxp is not None and canon(envp.pool[idxp]) == cc)) else 1.0)
            new_id.append(1.0 if (idxp is not None and canon(envp.pool[idxp]) == canon(envp.true_pa)) else 0.0)
            rp = run(env.n, env.pool, env.truth_index, env.obs(rs),
                     lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                     env.target, env.band, BUDGET, P["grid"], seed=rs, shell=_ShellView(paused=True))
            if rp.interventions or rp.acted:
                halt_ok = False
    m_t1, m_t2 = statistics.mean(t1c), statistics.mean(t2c)
    arena_valid = m_t1 >= 3.5 and statistics.mean(t1id) >= 0.7
    saving = m_t1 - m_t2
    drop = statistics.mean(t1a) - statistics.mean(t2a)
    m_ref = statistics.mean(stale_ref) if stale_ref else 0.0
    m_nid = statistics.mean(new_id) if new_id else 0.0
    met = halt_ok and arena_valid and saving >= 2.0 and drop <= 0.10 and m_ref >= 0.8 and m_nid >= 0.7
    out = {"gate": "IGI-E2E-2d", "envs": len(envs),
           "t1_mean": round(m_t1, 3), "t1_identification": round(statistics.mean(t1id), 3),
           "t2_mean": round(m_t2, 3), "compounding_saving": round(saving, 3),
           "achievement_drop": round(drop, 4),
           "stale_cache_refuted_TARGETED": round(m_ref, 3), "vs_2c_generic": 0.667,
           "new_truth_identification": round(m_nid, 3),
           "controls": {"halt_100pct": halt_ok, "arena_valid": arena_valid},
           "verdict": ("INVALID(ARENA)" if not arena_valid else
                       ("INVALID" if not halt_ok else ("PASS" if met else "FAIL")))}
    open("experiments/igi_e2e_2d.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
