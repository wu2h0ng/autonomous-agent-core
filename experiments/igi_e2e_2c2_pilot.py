"""E2E-2c-v2 ARENA PILOT — the SPACE lever (big CLEAN hypothesis spaces), replacing the failed noise
lever (2c pilot: noise-coarsening killed identification along with cost). Construction: n=13 skeletons
dominated by LONG UNDIRECTED PATHS (path orientations multiply the MEC: two 5-node paths + tail ->
MEC ~ 5*5*2 = 50-200), LOW noise (verifier stays sound), tol 0.6. Expect: t1 >= 3.5 dos (ceil log_k MEC)
with identification >= 0.7. Pilot on calib seeds 3000+; winner frozen into E2E-2c."""
from __future__ import annotations

import json
import random
import statistics

from aac.e2e_agent import run
from aac.hypothesis_pool import mec, canon
from experiments.igi_e2e_2 import P

N = 13
N_ENVS = 6
RUNS = [0, 1]
BUDGET = 10


def _stream(tag):
    return random.Random(f"E2E2c2|{tag}")


class PathEnv:
    """Skeleton = two disjoint 5-node paths + one 3-node path (12 edges? 4+4+2=10 edges, 13 nodes).
    Path MECs multiply -> big clean spaces."""

    def __init__(self, seed):
        r = _stream(f"gen|{seed}")
        lab = list(range(N)); r.shuffle(lab)
        paths = [lab[0:5], lab[5:10], lab[10:13]]
        edges = []
        for pth in paths:
            for i in range(len(pth) - 1):
                edges.append(tuple(sorted((pth[i], pth[i + 1]))))
        self.skeleton = sorted(edges)
        pa = {}
        for pth in paths:
            root = r.randrange(len(pth))          # orient outward from a random root: no colliders
            for i in range(len(pth) - 1):
                a, b = pth[i], pth[i + 1]
                if i + 1 <= root:
                    pa.setdefault(a, set()).add(b)
                else:
                    pa.setdefault(b, set()).add(a)
        self.true_pa = {k: frozenset(v) for k, v in pa.items()}
        self.w = {(s_, d_): r.uniform(P["w_lo"], P["w_hi"]) * r.choice((-1, 1))
                  for d_, ps in self.true_pa.items() for s_ in ps}
        self.pool = mec(N, self.skeleton, self.true_pa)
        self.truth_index = next((i for i, h in enumerate(self.pool) if canon(h) == canon(self.true_pa)), None)
        self.n, self.seed = N, seed
        self.order = self._topo()
        self.target = max(range(N), key=lambda v: (len(self.true_pa.get(v, ())), v))
        best = max((self._tdm(node, val) for node in range(N) if node != self.target
                    for val in P["grid"]), key=lambda m: abs(m))
        self.band = (best - P["band_half"], best + P["band_half"])

    def _topo(self):
        indeg = {j: len(self.true_pa.get(j, ())) for j in range(N)}
        ch = {}
        for j, ps in self.true_pa.items():
            for p_ in ps:
                ch.setdefault(p_, []).append(j)
        out, st = [], sorted(j for j in range(N) if indeg[j] == 0)
        while st:
            u = st.pop(0); out.append(u)
            for v in sorted(ch.get(u, ())):
                indeg[v] -= 1
                if indeg[v] == 0:
                    st.append(v)
        return out

    def _tdm(self, node, val):
        mean = [0.0] * N
        for v in self.order:
            mean[v] = val if v == node else sum(self.w[(s_, v)] * mean[s_] for s_ in self.true_pa.get(v, ()))
        return mean[self.target]

    def _sample(self, r, do_node, val):
        x = [0.0] * N
        for v in self.order:
            if v == do_node:
                x[v] = val
            else:
                x[v] = sum(self.w[(s_, v)] * x[s_] for s_ in self.true_pa.get(v, ())) + r.gauss(0, 0.8)
        return x

    def obs(self, rs):
        r = _stream(f"obs|{self.seed}|{rs}")
        return [self._sample(r, None, 0.0) for _ in range(P["n_obs"])]

    def do_rows(self, k, rs, step):
        r = _stream(f"do|{self.seed}|{rs}|{k}|{step}")
        return [self._sample(r, k, 2.0) for _ in range(150)]

    def act(self, node, val, rs):
        r = _stream(f"act|{self.seed}|{rs}|{node}|{val}")
        return statistics.mean(self._sample(r, node, val)[self.target] for _ in range(200))


def main():
    envs, s = [], 3000
    while len(envs) < N_ENVS and s < 3400:
        e = PathEnv(s)
        s += 1
        if e.truth_index is not None and len(e.pool) >= 40:
            envs.append(e)
    costs, ids = [], []
    mecs = [len(e.pool) for e in envs]
    for env in envs:
        for rs in RUNS:
            r = run(env.n, env.pool, env.truth_index, env.obs(rs),
                    lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                    env.target, env.band, BUDGET, P["grid"], seed=rs, tol=0.6)
            ids.append(1.0 if (r.identified and r.correct_structure) else 0.0)
            if r.identified:
                costs.append(len(r.interventions))
    out = {"pilot": "E2E-2c-v2 (space lever)", "mec_sizes": mecs,
           "t1_mean": round(statistics.mean(costs), 3) if costs else None,
           "identification": round(statistics.mean(ids), 3),
           "valid": bool(costs and statistics.mean(costs) >= 3.5 and statistics.mean(ids) >= 0.7)}
    out["action"] = "FREEZE E2E-2c on this arena" if out["valid"] else "space lever insufficient too — record"
    open("experiments/igi_e2e_2c2_pilot.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
