"""SVAR arena for AGDE-T3 (design: AGDE-T3.DESIGN-2026-07-04). x_t = C x_t + A x_{t-1} + eps:
contemporaneous DAG C (orientation = the observation-unidentified MEC fraction) + sparse lag matrix A
(3 frozen candidate lag-pairs; true support a random subset). do(k) = clamp for a window; the verifier
consumes TRAJECTORIES (late-window means under clamp depend on BOTH C-orientation and A-support).
Stability enforced (spectral radius < 1 via weight scaling). Pure stdlib, named streams."""
from __future__ import annotations

import random

from aac.hypothesis_pool import canon, mec

SVAR_PARAMS = {
    "n": 6, "w_lo": 0.4, "w_hi": 0.8, "lag_w": 0.5, "noise_sd": 0.6,
    "n_lag_candidates": 3, "T_obs": 400, "T_do": 120, "late_frac": 0.5,
    "do_value": 2.0, "mec_min": 4, "scale_cap": 0.85,
}


def _stream(tag):
    return random.Random(f"T3|{tag}")


class SvarEnv:
    def __init__(self, seed):
        p = SVAR_PARAMS
        n = p["n"]
        r = _stream(f"gen|{seed}")
        order = list(range(n)); r.shuffle(order)
        pos = {v: i for i, v in enumerate(order)}
        edges = set()
        for i in range(1, n):
            edges.add(tuple(sorted((order[i], order[r.randrange(i)]))))
        for _ in range(12):
            a, b = r.sample(range(n), 2)
            e = tuple(sorted((a, b)))
            if e not in edges:
                edges.add(e)
                break
        self.skeleton = sorted(edges)
        pa = {}
        for a, b in self.skeleton:
            s_, d_ = (a, b) if pos[a] < pos[b] else (b, a)
            pa.setdefault(d_, set()).add(s_)
        self.true_pa = {k: frozenset(v) for k, v in pa.items()}
        self.C = {(s_, d_): r.uniform(p["w_lo"], p["w_hi"]) * r.choice((-1, 1))
                  for d_, ps in self.true_pa.items() for s_ in ps}
        cands = []
        while len(cands) < p["n_lag_candidates"]:
            a, b = r.sample(range(n), 2)
            if (a, b) not in cands:
                cands.append((a, b))
        self.lag_candidates = cands
        self.true_lag = frozenset(c for c in cands if r.random() < 0.5)
        self.A = {c: p["lag_w"] * r.choice((-1, 1)) for c in self.true_lag}
        # stability: scale all weights if needed (row-sum proxy)
        for v in range(n):
            s = sum(abs(w) for (src, dst), w in self.C.items() if dst == v) + \
                sum(abs(w) for (src, dst), w in self.A.items() if dst == v)
            if s > p["scale_cap"]:
                f = p["scale_cap"] / s
                for k2 in list(self.C):
                    if k2[1] == v:
                        self.C[k2] *= f
                for k2 in list(self.A):
                    if k2[1] == v:
                        self.A[k2] *= f
        self.mec_c = mec(n, self.skeleton, self.true_pa)
        self.pool = [(h, fs) for h in self.mec_c
                     for fs in _subsets(cands)]
        self.truth_index = next(i for i, (h, fs) in enumerate(self.pool)
                                if canon(h) == canon(self.true_pa) and fs == self.true_lag)
        self.n, self.seed = n, seed
        self.order = order

    def _step(self, prev, r, do_node):
        p = SVAR_PARAMS
        x = [0.0] * self.n
        for v in self.order:
            if v == do_node:
                x[v] = p["do_value"]
            else:
                val = sum(self.C[(s_, v)] * x[s_] for s_ in self.true_pa.get(v, ()))
                val += sum(w * prev[src] for (src, dst), w in self.A.items() if dst == v)
                x[v] = val + r.gauss(0, p["noise_sd"])
        return x

    def trajectory(self, rs, T, do_node=None, tag="obs"):
        r = _stream(f"{tag}|{self.seed}|{rs}|{do_node}")
        x = [0.0] * self.n
        out = []
        for _ in range(T):
            x = self._step(x, r, do_node)
            out.append(x)
        return out

    def obs(self, rs):
        return self.trajectory(rs, SVAR_PARAMS["T_obs"])

    def do_window(self, k, rs, step):
        traj = self.trajectory(rs * 100 + step, SVAR_PARAMS["T_do"], do_node=k, tag="do")
        late = traj[int(len(traj) * SVAR_PARAMS["late_frac"]):]
        return [sum(row[j] for row in late) / len(late) for j in range(self.n)]


def _subsets(cands):
    out = [frozenset()]
    for c in cands:
        out += [s | {c} for s in out]
    return sorted(set(out), key=lambda s: (len(s), sorted(s)))
