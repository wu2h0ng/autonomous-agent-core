"""IGI-E2E-2e — REPLAY-BASED staleness (the demonstration principle applied to knowledge freshness).

Store the outcomes the world DEMONSTRATED during task-1 discovery (measured node-means per executed
do()); to reuse the cache later, REPLAY up to 2 of those original interventions and compare the fresh
measured means against the STORED means (tol 0.6, max-node). Same answers -> world unchanged where it
mattered -> trust; different -> world changed -> full rediscovery. Models never enter the comparison.

Frozen decision, space-lever arena, 8 envs x 2 runs, FRESH seeds 4300+, runs {77,78}: ARENA-VALID as
before. PASS iff saving >= 2.0 AND drop <= 0.10 AND stale-refuted >= 0.8 AND new-truth id >= 0.7 AND
halt 100%. Frozen prediction: replay compares world-to-world at exactly the dos that carried the
original identification (they sit ON the ambiguity paths) -> stale-refuted 0.85-1.0; fresh-world trust
preserved (same env, same do -> same means within tol; noise SE of 150-sample means ~0.07 << 0.6) ->
saving ~2.5; new-truth id 0.55-0.8 (persistent live risk). PASS ~60%."""
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

RUNS = [77, 78]
N_ENVS = 8
BUDGET = 10
REPLAYS = 2
TOL = 0.6


def discover_with_memory(env, rs):
    """Task-1 discovery that also RECORDS the demonstrated outcomes (do -> measured node means)."""
    obs = env.obs(rs)
    mechs = [fit_mechanisms(env.n, h, obs) for h in env.pool]
    bases = [predict_do_means(env.n, h, m, -1, 0.0) for h, m in zip(env.pool, mechs)]
    alive = list(range(len(env.pool)))
    memory = []
    for step in range(BUDGET):
        if len(alive) <= 1:
            break
        k = choose(env.n, [env.pool[i] for i in alive], [mechs[i] for i in alive],
                   list(range(env.n)), 2.0, [bases[i] for i in alive], TOL)
        rows = env.do_rows(k, rs, step)
        measured = [statistics.mean(r[j] for r in rows) for j in range(env.n)]
        memory.append((k, measured))
        try:
            keep, _ = prune(env.n, [env.pool[i] for i in alive], [mechs[i] for i in alive],
                            k, 2.0, rows, TOL)
        except Exhausted:
            return None, len(memory), memory
        alive = [alive[i] for i in keep]
    return (alive[0] if len(alive) == 1 else None), len(memory), memory


def cached_run_replay(env, rs, memory, cached_canon):
    """Task-2: replay up to REPLAYS stored dos; compare MEASURED means old-vs-new. Same -> trust cache;
    changed -> full rediscovery (fresh fits)."""
    cost = 0
    for (k, stored) in memory[:REPLAYS]:
        rows = env.do_rows(k, rs, 900 + cost)
        fresh = [statistics.mean(r[j] for r in rows) for j in range(env.n)]
        cost += 1
        if max(abs(fresh[j] - stored[j]) for j in range(env.n)) > TOL:
            idx, dcost, mem2 = discover_with_memory(env, rs + 50)      # world changed -> rediscover
            return idx, cost + dcost, False
    # world answered the same -> trust the cache
    ci = next((i for i, h in enumerate(env.pool) if canon(h) == cached_canon), None)
    return ci, cost, True


def main():
    envs, s = [], 4300
    while len(envs) < N_ENVS and s < 4700:
        e = PathEnv(s)
        s += 1
        if e.truth_index is not None and len(e.pool) >= 40:
            envs.append(e)
    t1c, t1id, t2c, t2ok = [], [], [], []
    stale_ref, new_id, halt_ok = [], [], True
    for env in envs:
        for rs in RUNS:
            idx1, cost1, memory = discover_with_memory(env, rs)
            ok1 = idx1 is not None and canon(env.pool[idx1]) == canon(env.true_pa)
            t1id.append(1.0 if ok1 else 0.0)
            if not ok1:
                continue
            t1c.append(cost1)
            cc = canon(env.pool[idx1])
            idx2, cost2, trusted = cached_run_replay(env, rs + 100, memory, cc)
            t2c.append(cost2)
            t2ok.append(1.0 if (idx2 is not None and canon(env.pool[idx2]) == cc) else 0.0)
            envp = PerturbedPathEnv(env.seed)
            if envp.truth_index is None or canon(envp.true_pa) == cc:
                continue
            idxp, costp, trustedp = cached_run_replay(envp, rs + 200, memory, cc)
            stale_ref.append(0.0 if trustedp else 1.0)
            new_id.append(1.0 if (idxp is not None and canon(envp.pool[idxp]) == canon(envp.true_pa)) else 0.0)
            rp = run(env.n, env.pool, env.truth_index, env.obs(rs),
                     lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                     env.target, env.band, BUDGET, P["grid"], seed=rs, shell=_ShellView(paused=True))
            if rp.interventions or rp.acted:
                halt_ok = False
    m_t1, m_t2 = statistics.mean(t1c), statistics.mean(t2c)
    arena_valid = m_t1 >= 3.5 and statistics.mean(t1id) >= 0.7
    saving = m_t1 - m_t2
    drop = 1.0 - statistics.mean(t2ok) if t2ok else 1.0
    m_ref = statistics.mean(stale_ref) if stale_ref else 0.0
    m_nid = statistics.mean(new_id) if new_id else 0.0
    met = halt_ok and arena_valid and saving >= 2.0 and drop <= 0.10 and m_ref >= 0.8 and m_nid >= 0.7
    out = {"gate": "IGI-E2E-2e", "envs": len(envs),
           "t1_mean": round(m_t1, 3), "t1_identification": round(statistics.mean(t1id), 3),
           "t2_mean": round(m_t2, 3), "compounding_saving": round(saving, 3),
           "t2_correct_rate": round(statistics.mean(t2ok), 4) if t2ok else 0.0,
           "stale_refuted_REPLAY": round(m_ref, 3), "lineage": {"2c_generic": 0.667, "2d_targeted": 0.533},
           "new_truth_identification": round(m_nid, 3),
           "controls": {"halt_100pct": halt_ok, "arena_valid": arena_valid},
           "verdict": ("INVALID(ARENA)" if not arena_valid else
                       ("INVALID" if not halt_ok else ("PASS" if met else "FAIL")))}
    open("experiments/igi_e2e_2e.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
