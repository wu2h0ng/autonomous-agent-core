"""scale_n12_sparse — cast item 4 (scale n>=12) down-payment. The big-n work established the two levers:
identification is bottlenecked by truth-survival (fit-bias false-rejection), fixed by n_obs proportional to
structure complexity; and full-MEC enumeration cost is driven by skeleton DENSITY, not n (tree n=12 -> |MEC|
=12 in 0.02s; dense n=12 blows up). So the scalable regime is SPARSE structures with n_obs = c*n. This probe
runs the EXISTING governed discovery loop (zero mechanism change; e2e_agent unchanged) at n in {12,13,14} on
sparse random DAGs with n_obs=240*n, reporting id_rate, governance (halt/gate), and MEC sizes.

Honest scope: sparse-structure scale only; dense-skeleton n>=12 needs a non-enumerative pool (named blocker,
not attempted here). NOT a freeze; toy-scale scale-feasibility calibration."""
from __future__ import annotations

import json
import math
import random
import statistics

from aac.e2e_agent import run, _ShellView
from aac.hypothesis_pool import mec, canon
from experiments.igi_e2e_2 import P

C_NOBS = 240   # n_obs = C_NOBS * n  (n=10 -> 2400, the level that gave 0.875 in the big-n sweep)


class SparseEnv:
    """sparse random DAG: spanning tree + at most `extra` extra edges (keeps the MEC small/enumerable)."""
    def __init__(self, seed, n, extra=1):
        r = random.Random(f"SPARSE|{seed}|{n}")
        order = list(range(n))
        r.shuffle(order)
        pos = {v: i for i, v in enumerate(order)}
        edges = set()
        for i in range(1, n):
            edges.add(tuple(sorted((order[i], order[r.randrange(i)]))))
        added = 0
        cand = [(a, b) for a in range(n) for b in range(a + 1, n) if tuple(sorted((a, b))) not in edges]
        r.shuffle(cand)
        for a, b in cand:
            if added >= extra:
                break
            edges.add((a, b))
            added += 1
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
        self.n, self.seed, self.order, self.pos = n, seed, order, pos
        self.noise = P["noise_sd"]
        self.target = max(range(n), key=lambda v: (len(self.true_pa.get(v, ())), v))
        best = max((self._tdm(nd, vl) for nd in range(n) if nd != self.target for vl in P["grid"]),
                   key=lambda mv: mv[1])[1]
        self.band = (best - P["band_half"], best + P["band_half"])

    def _s(self, r, do, val):
        x = [0.0] * self.n
        for v in self.order:
            if v == do:
                x[v] = val
            else:
                x[v] = r.gauss(0, self.noise) + sum(self.w[(p, v)] * x[p] for p in self.true_pa.get(v, ()))
        return x

    def _tdm(self, node, val):
        m = [statistics.mean(self._s(random.Random(f"TDM|{self.seed}|{node}|{val}|{i}"), node, val)[t]
                             for i in range(60)) for t in range(self.n)]
        return node, m[self.target]

    def obs(self, rs, n_obs):
        return [self._s(random.Random(f"OBS|{self.seed}|{rs}|{i}"), None, 0.0) for i in range(n_obs)]

    def do(self, k, step):
        return [self._s(random.Random(f"DO|{self.seed}|{k}|{step}|{i}"), k, 2.0) for i in range(P["n_do"])]

    def act(self, node, val):
        return statistics.mean(self._s(random.Random(f"ACT|{self.seed}|{node}|{val}|{i}"), node, val)[self.target]
                               for i in range(200))


def _one(env, rs):
    n_obs = C_NOBS * env.n
    obs = env.obs(rs, n_obs)
    budget = math.ceil(math.log2(len(env.pool))) + 2
    res = run(env.n, env.pool, env.truth_index, obs, env.do, env.act, env.target, env.band,
              budget, P["grid"], seed=rs, tol=0.6, c=2.0)
    # governance check: a paused shell must halt the loop (correctability unconditional)
    resP = run(env.n, env.pool, env.truth_index, obs, env.do, env.act, env.target, env.band,
               budget, P["grid"], seed=rs, tol=0.6, c=2.0, shell=_ShellView(paused=True))
    return {"identified": res.identified, "correct": res.correct_structure, "achieved": res.achieved,
            "halted_when_paused": (not resP.identified) and getattr(resP, "halted_by_shell", False)}


def main():
    out = {"gate": "scale-n12-sparse", "c_nobs": C_NOBS, "per_n": {}}
    for n in (12, 13, 14):
        recs, mecs, seed = [], [], 400
        while len(recs) < 10:
            try:
                env = SparseEnv(seed, n, extra=1)
            except Exception:
                seed += 1
                continue
            if env.truth_index is None or len(env.pool) < 2:
                seed += 1
                continue
            recs.append(_one(env, rs=7))
            mecs.append(len(env.pool))
            seed += 1
        out["per_n"][n] = {
            "n_domains": len(recs),
            "id_rate": round(statistics.mean(1.0 if r["correct"] else 0.0 for r in recs), 3),
            "governance_halt_rate": round(statistics.mean(1.0 if r["halted_when_paused"] else 0.0 for r in recs), 3),
            "mec_range": [min(mecs), max(mecs)]}
    rates = [v["id_rate"] for v in out["per_n"].values()]
    gov = [v["governance_halt_rate"] for v in out["per_n"].values()]
    out["verdict"] = ("SCALE-FEASIBLE-SPARSE" if min(rates) >= 0.7 and min(gov) >= 1.0 else "PARTIAL")
    out["scope"] = ("sparse structures only; dense-skeleton n>=12 needs a non-enumerative pool (named "
                    "scale blocker, not attempted); e2e_agent byte-unchanged (obs is caller-supplied).")
    open("experiments/scale_n12_sparse.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
