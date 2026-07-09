"""IGI-E2E-2c — compounding SAVING, on the pilot-validated space-lever arena (MEC 75, t1 ~4.8 dos).

Corrigible-reuse protocol for BIG pools (frozen; harness-level, mechanism files untouched): the cached
structure is tested by TWO confirm-do()s (the min-max chooser's best splits). Cache survives both ->
TRUSTED (surviving two maximally-discriminating fresh interventional tests among 75 hypotheses);
killed -> full rediscovery on the survivors. Saving = t1_cost - t2_cost.

Staleness arm: STRUCTURE perturbation (one path re-rooted -> different orientation -> truth index
changes) -> the stale cache must DIE within the confirm phase (>=0.8) and rediscovery must find the
new truth (>=0.7).

Frozen decision (mechanical), 8 envs x 2 runs, scored seeds 3500+ (pilot used 3000-3005), runs {85,86}:
  ARENA-VALID iff scored t1 mean >= 3.5 AND t1 identification >= 0.7 (else INVALID(ARENA), no verdict).
  PASS iff saving >= 2.0 AND achievement drop <= 0.10 AND stale-cache-refuted >= 0.8 AND new-truth
  id >= 0.7 AND halt 100%. FAIL else."""
from __future__ import annotations

import json
import random
import statistics

from aac.e2e_agent import run, _ShellView
from aac.hypothesis_pool import canon
from aac.intervention_chooser import choose
from aac.structure_consistency import Exhausted, fit_mechanisms, predict_do_means, prune
from experiments.igi_e2e_2 import P
from experiments.igi_e2e_2c2_pilot import PathEnv, _stream

RUNS = [85, 86]
N_ENVS = 8
BUDGET = 10
CONFIRMS = 2


class PerturbedPathEnv(PathEnv):
    """Same skeleton/weights family; one path re-rooted -> DIFFERENT orientation (structure change)."""

    def __init__(self, seed):
        super().__init__(seed)
        r = _stream(f"perturb|{seed}")
        # re-root the first 5-node path deterministically to a different root
        # (rebuild true_pa fully from paths with one shifted root)
        lab_r = _stream(f"gen|{seed}")
        lab = list(range(13)); lab_r.shuffle(lab)
        paths = [lab[0:5], lab[5:10], lab[10:13]]
        roots = []
        for pth in paths:
            roots.append(lab_r.randrange(len(pth)))
        roots[0] = (roots[0] + 2) % 5              # the structural change
        pa = {}
        for pth, root in zip(paths, roots):
            for i in range(len(pth) - 1):
                a, b = pth[i], pth[i + 1]
                if i + 1 <= root:
                    pa.setdefault(a, set()).add(b)
                else:
                    pa.setdefault(b, set()).add(a)
        self.true_pa = {k: frozenset(v) for k, v in pa.items()}
        wr = _stream(f"genw|{seed}")
        self.w = {(s_, d_): wr.uniform(P["w_lo"], P["w_hi"]) * wr.choice((-1, 1))
                  for d_, ps in self.true_pa.items() for s_ in ps}
        from aac.hypothesis_pool import mec as _mec
        self.pool = _mec(13, self.skeleton, self.true_pa)
        self.truth_index = next((i for i, h in enumerate(self.pool) if canon(h) == canon(self.true_pa)), None)
        self.order = self._topo()
        best = max((self._tdm(node, val) for node in range(13) if node != self.target
                    for val in P["grid"]), key=lambda m: abs(m))
        self.band = (best - P["band_half"], best + P["band_half"])


def cached_run(env, rs, cached_canon):
    """2-confirm corrigible reuse, then full discovery on survivors if cache dies / not isolated."""
    obs = env.obs(rs)
    mechs = [fit_mechanisms(env.n, h, obs) for h in env.pool]
    bases = [predict_do_means(env.n, h, m, -1, 0.0) for h, m in zip(env.pool, mechs)]
    alive = list(range(len(env.pool)))
    cost = 0
    cache_alive = lambda: any(canon(env.pool[i]) == cached_canon for i in alive)
    for stepc in range(CONFIRMS):
        if len(alive) == 1:
            break
        k = choose(env.n, [env.pool[i] for i in alive], [mechs[i] for i in alive],
                   list(range(env.n)), 2.0, [bases[i] for i in alive], 0.6)
        rows = env.do_rows(k, rs, stepc)
        cost += 1
        try:
            keep, _ = prune(env.n, [env.pool[i] for i in alive], [mechs[i] for i in alive],
                            k, 2.0, rows, 0.6)
        except Exhausted:
            return None, cost, False
        alive = [alive[i] for i in keep]
        if not cache_alive():
            break                                   # cache refuted -> rediscover
    if cache_alive() and len(alive) >= 1 and cost == CONFIRMS:
        # trusted: act on the cached structure
        ci = next(i for i in alive if canon(env.pool[i]) == cached_canon)
        return ci, cost, True
    # rediscovery on survivors
    for step in range(CONFIRMS, BUDGET):
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
    envs, s = [], 3500
    while len(envs) < N_ENVS and s < 3900:
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
            idx, cost2, trusted = cached_run(env, rs + 100, cc)
            t2c.append(cost2)
            ok2 = idx is not None and canon(env.pool[idx]) == cc
            t2a.append(1.0 if ok2 else 0.0)
            envp = PerturbedPathEnv(env.seed)
            if envp.truth_index is None or canon(envp.true_pa) == cc:
                continue
            idxp, costp, trustedp = cached_run(envp, rs + 200, cc)
            stale_ref.append(0.0 if (trustedp or (idxp is not None and canon(envp.pool[idxp]) == cc)) else 1.0)
            new_id.append(1.0 if (idxp is not None and canon(envp.pool[idxp]) == canon(envp.true_pa)) else 0.0)
            rp = run(env.n, env.pool, env.truth_index, env.obs(rs),
                     lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                     env.target, env.band, BUDGET, P["grid"], seed=rs,
                     shell=_ShellView(paused=True))
            if rp.interventions or rp.acted:
                halt_ok = False
    m_t1, m_t2 = statistics.mean(t1c), statistics.mean(t2c)
    arena_valid = m_t1 >= 3.5 and statistics.mean(t1id) >= 0.7
    saving = m_t1 - m_t2
    drop = statistics.mean(t1a) - statistics.mean(t2a)
    m_ref = statistics.mean(stale_ref) if stale_ref else 0.0
    m_nid = statistics.mean(new_id) if new_id else 0.0
    met = halt_ok and arena_valid and saving >= 2.0 and drop <= 0.10 and m_ref >= 0.8 and m_nid >= 0.7
    out = {"gate": "IGI-E2E-2c", "envs": len(envs), "mec_sizes": [len(e.pool) for e in envs],
           "t1_mean": round(m_t1, 3), "t1_identification": round(statistics.mean(t1id), 3),
           "t2_mean_with_cache": round(m_t2, 3), "compounding_saving": round(saving, 3),
           "achievement_drop": round(drop, 4),
           "stale_structure_cache_refuted": round(m_ref, 3), "new_truth_identification": round(m_nid, 3),
           "controls": {"halt_100pct": halt_ok, "arena_valid": arena_valid},
           "verdict": ("INVALID(ARENA)" if not arena_valid else
                       ("INVALID" if not halt_ok else ("PASS" if met else "FAIL")))}
    open("experiments/igi_e2e_2c.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
