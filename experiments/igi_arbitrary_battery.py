"""IGI-ARBITRARY-BATTERY — 'arbitrary novel domain' as a DISTRIBUTION, not a hand-picked list.

Directly answers 'only 6 specific tested classes, not arbitrary domains': the EXISTING e2e_agent loop
(zero code changes) on RANDOMLY-DRAWN causal structures the code has never seen — random n in {5..9},
random edge density (Erdos-Renyi-style over a random topological order), random weights/noise. Each
family is a fresh 'novel domain'; the loop is handed the MEC of a random DAG and must self-generate its
epistemic subgoal, discover, act on a random reachable preference, under governance. 60 random domains.

'Generality at toy scale' is demonstrated iff identification/achievement/governance hold ACROSS THE
RANDOM DISTRIBUTION (not just 6 curated shapes). Budget = ceil(log2 MEC)+2.

Frozen decision (mechanical): PASS iff mean identification >= 0.70 AND mean achievement|id >= 0.70 AND
halt 100% AND the result holds within each size bucket (no size where id collapses < 0.5)."""
from __future__ import annotations

import json
import math
import random
import statistics

from aac.e2e_agent import run, _ShellView
from aac.hypothesis_pool import mec, canon
from experiments.igi_e2e_2 import P

N_DOMAINS = 60
RUNS = [120, 121]


class RandomEnv:
    def __init__(self, seed):
        r = random.Random(f"ARB|{seed}")
        n = r.randint(5, 9)
        p_edge = r.uniform(0.25, 0.6)
        order = list(range(n)); r.shuffle(order)
        pos = {v: i for i, v in enumerate(order)}
        edges = set()
        # ensure connected-ish: spanning tree + random extras
        for i in range(1, n):
            edges.add(tuple(sorted((order[i], order[r.randrange(i)]))))
        for a in range(n):
            for b in range(a + 1, n):
                if tuple(sorted((a, b))) not in edges and r.random() < p_edge * 0.5:
                    edges.add((a, b))
        self.skeleton = sorted(edges)
        pa = {}
        for a, b in self.skeleton:
            s_, d_ = (a, b) if pos[a] < pos[b] else (b, a)
            pa.setdefault(d_, set()).add(s_)
        self.true_pa = {k: frozenset(v) for k, v in pa.items()}
        self.w = {(s_, d_): r.uniform(0.5, 1.6) * r.choice((-1, 1))
                  for d_, ps in self.true_pa.items() for s_ in ps}
        self.pool = mec(n, self.skeleton, self.true_pa)
        self.truth_index = next((i for i, h in enumerate(self.pool) if canon(h) == canon(self.true_pa)), None)
        self.n, self.seed, self.order = n, seed, order
        self.target = max(range(n), key=lambda v: (len(self.true_pa.get(v, ())), v))
        best = max((self._tdm(nd, vl) for nd in range(n) if nd != self.target for vl in P["grid"]),
                   key=lambda m: abs(m))
        self.band = (best - P["band_half"], best + P["band_half"])

    def _tdm(self, node, val):
        m = [0.0] * self.n
        for v in self.order:
            m[v] = val if v == node else sum(self.w[(s_, v)] * m[s_] for s_ in self.true_pa.get(v, ()))
        return m[self.target]

    def _s(self, r, do, val):
        x = [0.0] * self.n
        for v in self.order:
            x[v] = val if v == do else sum(self.w[(s_, v)] * x[s_] for s_ in self.true_pa.get(v, ())) + r.gauss(0, P["noise_sd"])
        return x

    def obs(self, rs):
        r = random.Random(f"ARBobs|{self.seed}|{rs}")
        return [self._s(r, None, 0.0) for _ in range(P["n_obs"])]

    def do_rows(self, k, rs, st):
        r = random.Random(f"ARBdo|{self.seed}|{rs}|{k}|{st}")
        return [self._s(r, k, 2.0) for _ in range(P["n_do"])]

    def act(self, node, val, rs):
        r = random.Random(f"ARBact|{self.seed}|{rs}|{node}|{val}")
        return statistics.mean(self._s(r, node, val)[self.target] for _ in range(200))


def main():
    domains, s = [], 20000
    while len(domains) < N_DOMAINS and s < 20600:
        e = RandomEnv(s)
        s += 1
        if e.truth_index is not None and len(e.pool) >= 2:
            domains.append(e)
    ids, achs, halts = [], [], True
    by_n = {}
    for env in domains:
        budget = math.ceil(math.log2(len(env.pool))) + 2
        for rs in RUNS:
            obs = env.obs(rs)
            r1 = run(env.n, env.pool, env.truth_index, obs,
                     lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                     env.target, env.band, budget, P["grid"], seed=rs)
            ok = 1.0 if (r1.identified and r1.correct_structure) else 0.0
            ids.append(ok)
            by_n.setdefault(env.n, []).append(ok)
            if r1.identified:
                achs.append(1.0 if r1.achieved else 0.0)
            rp = run(env.n, env.pool, env.truth_index, obs,
                     lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                     env.target, env.band, budget, P["grid"], seed=rs, shell=_ShellView(paused=True))
            if rp.interventions or rp.acted:
                halts = False
    m_id, m_ach = statistics.mean(ids), (statistics.mean(achs) if achs else 0.0)
    bucket = {n: round(statistics.mean(v), 3) for n, v in sorted(by_n.items())}
    bucket_ok = all(v >= 0.5 for v in bucket.values())
    met = m_id >= 0.70 and m_ach >= 0.70 and halts and bucket_ok
    out = {"gate": "IGI-ARBITRARY-BATTERY", "n_random_domains": len(domains),
           "distinct_structures": len({tuple(e.skeleton) for e in domains}),
           "mec_range": [min(len(e.pool) for e in domains), max(len(e.pool) for e in domains)],
           "identification": round(m_id, 3), "achievement_given_id": round(m_ach, 3),
           "id_by_node_count": bucket, "halt_100pct": halts,
           "verdict": "MET" if met else ("INVALID" if not halts else "NULL")}
    open("experiments/igi_arbitrary_battery.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
