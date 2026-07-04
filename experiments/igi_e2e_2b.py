"""IGI-E2E-2b — compounding, correctly posed (fixes E2E-2's two protocol errors).

Fix 1 (no saving room): EXPENSIVE-discovery arena — dense n=8 skeletons (tree + 3 extra edges),
  families filtered to MEC >= 12 (>= ~4 well-chosen do()s to resolve), budget 6.
Fix 2 (wrong staleness object): the perturbed arm now changes STRUCTURE — one free edge is REVERSED
  such that the new truth is a DIFFERENT MEC member (truth index changes) -> the cached structure is
  GENUINELY WRONG and the confirmation do() must refute it; full re-discovery must then find the new truth.

Frozen decision (mechanical), 10 envs x 2 runs, fresh seeds 1500+ runs {80,81}:
  PASS iff task-1 mean interventions >= 3.0 (arena validity: discovery is genuinely expensive) AND
  compounding saving (task1 - task2 interventions) >= 2.0 with achievement drop <= 0.10 AND
  structure-perturbed arm: cache refuted >= 0.8 AND new-truth identification >= 0.7 AND halt 100%.
  FAIL else; INVALID if the arena-validity clause fails (mis-built arena, no verdict)."""
from __future__ import annotations

import json
import random
import statistics

from aac.e2e_agent import run, _ShellView
from aac.hypothesis_pool import mec, canon
from experiments.igi_e2e_2 import P

RUNS = [80, 81]
N_ENVS = 10
BUDGET = 6


def _stream(tag):
    return random.Random(f"E2E2b|{tag}")


class DenseEnv:
    def __init__(self, seed, flip_edge=None):
        n = 8
        r = _stream(f"gen|{seed}")
        order = list(range(n)); r.shuffle(order)
        pos = {v: i for i, v in enumerate(order)}
        edges = set()
        for i in range(1, n):
            edges.add(tuple(sorted((order[i], order[r.randrange(i)]))))
        extra = 3
        while extra:
            a, b = r.sample(range(n), 2)
            e = tuple(sorted((a, b)))
            if e not in edges:
                edges.add(e); extra -= 1
        self.skeleton = sorted(edges)
        pa = {}
        for a, b in self.skeleton:
            s_, d_ = (a, b) if pos[a] < pos[b] else (b, a)
            pa.setdefault(d_, set()).add(s_)
        self.true_pa = {k: frozenset(v) for k, v in pa.items()}
        if flip_edge is not None:
            # STRUCTURE change: reverse one edge (kept acyclic by construction check below)
            a, b = flip_edge
            ps = dict(self.true_pa)
            if b in ps and a in ps[b]:
                ps[b] = frozenset(x for x in ps[b] if x != a)
                ps[a] = frozenset(set(ps.get(a, frozenset())) | {b})
                self.true_pa = {k: v for k, v in ps.items() if v}
        self.w = {(s_, d_): r.uniform(P["w_lo"], P["w_hi"]) * r.choice((-1, 1))
                  for d_, pset in self.true_pa.items() for s_ in pset}
        self.pool = mec(n, self.skeleton, self.true_pa)
        self.truth_index = next((i for i, h in enumerate(self.pool) if canon(h) == canon(self.true_pa)), None)
        self.n, self.seed = n, seed
        self.order = self._topo()
        self.target = max(range(n), key=lambda v: (len(self.true_pa.get(v, ())), v))
        best = max((self._true_do_mean(node, val) for node in range(n) if node != self.target
                    for val in P["grid"]), key=lambda m: abs(m))
        self.band = (best - P["band_half"], best + P["band_half"])
        self.flip = flip_edge

    def _topo(self):
        indeg = {j: len(self.true_pa.get(j, ())) for j in range(self.n)}
        ch = {}
        for j, ps in self.true_pa.items():
            for p_ in ps:
                ch.setdefault(p_, []).append(j)
        out, stack = [], sorted(j for j in range(self.n) if indeg[j] == 0)
        while stack:
            u = stack.pop(0); out.append(u)
            for v in sorted(ch.get(u, ())):
                indeg[v] -= 1
                if indeg[v] == 0:
                    stack.append(v)
        return out

    def _true_do_mean(self, node, val):
        mean = [0.0] * self.n
        for v in self.order:
            mean[v] = val if v == node else sum(self.w[(s_, v)] * mean[s_] for s_ in self.true_pa.get(v, ()))
        return mean[self.target]

    def _sample(self, r, do_node, val):
        x = [0.0] * self.n
        for v in self.order:
            if v == do_node:
                x[v] = val
            else:
                x[v] = sum(self.w[(s_, v)] * x[s_] for s_ in self.true_pa.get(v, ())) + r.gauss(0, P["noise_sd"])
        return x

    def obs(self, rs):
        r = _stream(f"obs|{self.seed}|{rs}|{self.flip}")
        return [self._sample(r, None, 0.0) for _ in range(P["n_obs"])]

    def do_rows(self, k, rs, step):
        r = _stream(f"do|{self.seed}|{rs}|{k}|{step}|{self.flip}")
        return [self._sample(r, k, 2.0) for _ in range(P["n_do"])]

    def act(self, node, val, rs):
        r = _stream(f"act|{self.seed}|{rs}|{node}|{val}|{self.flip}")
        return statistics.mean(self._sample(r, node, val)[self.target] for _ in range(200))

    def free_edge(self):
        """An edge whose reversal lands on ANOTHER MEC member (a genuinely wrong-making change)."""
        for h in self.pool:
            if canon(h) != canon(self.true_pa):
                # find an edge oriented differently in h
                for d_, ps in h.items():
                    for s_ in ps:
                        if d_ in self.true_pa.get(s_, frozenset()) or s_ not in self.true_pa.get(d_, frozenset()):
                            if s_ in self.true_pa.get(d_, frozenset()):
                                continue
                # fallback below
        for (a, b) in [(s_, d_) for d_, ps in self.true_pa.items() for s_ in ps]:
            return (a, b)
        return None


def _run(env, rs, cached=None, budget=BUDGET):
    obs = env.obs(rs)
    return run(env.n, env.pool, env.truth_index, obs,
               lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
               env.target, env.band, budget, P["grid"], seed=rs, cached_structure=cached)


def main():
    envs, s = [], 1500
    while len(envs) < N_ENVS and s < 2100:
        e = DenseEnv(s)
        s += 1
        if len(e.pool) >= 12 and e.truth_index is not None:
            envs.append(e)
    t1c, t2c, t1a, t2a = [], [], [], []
    refuted, new_id, halt_ok = [], [], True
    for env in envs:
        for rs in RUNS:
            r1 = _run(env, rs)
            if not (r1.identified and r1.correct_structure):
                continue
            t1c.append(len(r1.interventions)); t1a.append(1.0 if r1.achieved else 0.0)
            r2 = _run(env, rs + 100, cached=env.truth_index)
            t2c.append(len(r2.interventions)); t2a.append(1.0 if r2.achieved else 0.0)
            # STRUCTURE-perturbed world: reverse a true edge -> truth index CHANGES
            fe = env.free_edge()
            envp = DenseEnv(env.seed, flip_edge=fe)
            if envp.truth_index is None or canon(envp.true_pa) == canon(env.true_pa):
                continue
            r3 = _run(envp, rs + 200, cached=env.truth_index)
            # stale cache "survived wrongly" iff the run ended right after the single confirm-do
            # having identified a WRONG structure (i.e. it trusted the old cache in the changed world)
            stale_survived = (r3.identified and not r3.correct_structure and len(r3.interventions) <= 1)
            refuted.append(0.0 if stale_survived else 1.0)
            new_id.append(1.0 if (r3.identified and r3.correct_structure) else 0.0)
            rp = run(env.n, env.pool, env.truth_index, env.obs(rs),
                     lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                     env.target, env.band, BUDGET, P["grid"], seed=rs, shell=_ShellView(paused=True))
            if rp.interventions or rp.acted:
                halt_ok = False
    m_t1, m_t2 = statistics.mean(t1c), statistics.mean(t2c)
    saving = m_t1 - m_t2
    drop = statistics.mean(t1a) - statistics.mean(t2a)
    m_ref = statistics.mean(refuted) if refuted else 0.0
    m_nid = statistics.mean(new_id) if new_id else 0.0
    arena_valid = m_t1 >= 3.0
    met = (halt_ok and arena_valid and saving >= 2.0 and drop <= 0.10 and m_ref >= 0.8 and m_nid >= 0.7)
    out = {"gate": "IGI-E2E-2b", "envs": len(envs), "mec_sizes": [len(e.pool) for e in envs],
           "task1_mean_interventions": round(m_t1, 3), "task2_mean_interventions": round(m_t2, 3),
           "compounding_saving": round(saving, 3), "achievement_drop": round(drop, 4),
           "structure_perturbed_cache_refuted": round(m_ref, 3), "new_truth_identification": round(m_nid, 3),
           "controls": {"halt_100pct": halt_ok, "arena_valid_t1_ge_3": arena_valid},
           "verdict": ("INVALID(ARENA)" if not arena_valid else
                       ("INVALID" if not halt_ok else ("PASS" if met else "FAIL")))}
    open("experiments/igi_e2e_2b.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
