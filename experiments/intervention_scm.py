"""AGDE-1 arena: linear-Gaussian SCM families with hard single-node interventions (packet §4.1).

Family = (given skeleton, hidden true orientation, weights). Hypothesis space handed to EVERY arm =
MEC(truth) (observational data cannot discriminate within it — the observation-unidentified fraction
this gate isolates). Family validity is MACHINE-CHECKED at calibration: MEC >= 4; informative-node
fraction <= 1/3 (scarcity: most single do()s must NOT split the MEC — favourable-to-active by design,
disclosed); measured oracle-random gap minimum enforced at the harness level. Named RNG streams."""
from __future__ import annotations

import random

from aac.hypothesis_pool import canon, mec
from aac.intervention_chooser import signature
from aac.structure_consistency import predict_do_means

SCM_PARAMS = {
    "n_nodes": 5,
    "w_lo": 0.7, "w_hi": 1.3,          # |weight| range, sign random
    "noise_sd": 1.0,
    "do_value": 2.0,                    # frozen intervention value c
    "n_obs": 400,
    "mec_min": 4,
    "informative_frac_max": 1.0 / 3.0 + 1e-9,
}


def _stream(tag: str) -> random.Random:
    return random.Random(f"AGDE1-SCM|{tag}")


class Family:
    def __init__(self, family_seed: int):
        p = SCM_PARAMS
        n = p["n_nodes"]
        rng = _stream(f"fam|{family_seed}")
        # skeleton: random spanning tree (+1 extra edge with prob 1/2), no multi-edges
        nodes = list(range(n))
        rng.shuffle(nodes)
        edges = set()
        for i in range(1, n):
            a = nodes[i]
            b = nodes[rng.randrange(i)]
            edges.add(tuple(sorted((a, b))))
        if rng.random() < 0.5:
            for _ in range(20):
                a, b = rng.sample(range(n), 2)
                e = tuple(sorted((a, b)))
                if e not in edges:
                    edges.add(e)
                    break
        self.skeleton = sorted(edges)
        # true orientation: random topological order
        order = list(range(n))
        rng.shuffle(order)
        pos = {v: i for i, v in enumerate(order)}
        pa: dict[int, set] = {}
        for a, b in self.skeleton:
            src, dst = (a, b) if pos[a] < pos[b] else (b, a)
            pa.setdefault(dst, set()).add(src)
        self.true_pa = {k: frozenset(v) for k, v in pa.items()}
        self.weights = {(src, dst): (rng.uniform(p["w_lo"], p["w_hi"]) * rng.choice((-1, 1)))
                        for dst, ps in self.true_pa.items() for src in ps}
        self.n = n
        self.family_seed = family_seed
        self.pool = mec(n, self.skeleton, self.true_pa)
        self.truth_index = next(i for i, h in enumerate(self.pool) if canon(h) == canon(self.true_pa))

    def _sample(self, rng: random.Random, do_node: int | None, c: float) -> list[float]:
        p = SCM_PARAMS
        x = [0.0] * self.n
        state = [0] * self.n
        order = []

        def visit(u):
            if state[u]:
                return
            state[u] = 1
            for q in self.true_pa.get(u, ()):
                visit(q)
            order.append(u)

        for u in range(self.n):
            visit(u)
        for u in order:
            if u == do_node:
                x[u] = c
            else:
                x[u] = sum(self.weights[(q, u)] * x[q] for q in self.true_pa.get(u, ())) \
                       + rng.gauss(0.0, p["noise_sd"])
        return x

    def sample_obs(self, run_seed: int, n_rows: int | None = None) -> list[list[float]]:
        rng = _stream(f"obs|{self.family_seed}|{run_seed}")
        n_rows = n_rows or SCM_PARAMS["n_obs"]
        return [self._sample(rng, None, 0.0) for _ in range(n_rows)]

    def sample_do(self, k: int, run_seed: int, step: int, n_rows: int) -> list[list[float]]:
        rng = _stream(f"do|{self.family_seed}|{run_seed}|{k}|{step}")
        return [self._sample(rng, k, SCM_PARAMS["do_value"]) for _ in range(n_rows)]


def true_mechs(fam: Family) -> dict[int, tuple]:
    return {j: (0.0, {q: fam.weights[(q, j)] for q in fam.true_pa.get(j, ())}) for j in range(fam.n)}


def informative_fraction(fam: Family, tol: float) -> float:
    """Fraction of nodes whose do() splits the MEC under TRUE mechanisms (validity check, not an arm)."""
    tm = true_mechs(fam)
    mechs = [ {j: (0.0, {q: fam.weights.get((q, j), _hyp_w(fam, h, q, j)) for q in h.get(j, ())})
               for j in range(fam.n)} for h in fam.pool ]
    # For validity we only need whether signatures DIFFER across the pool under each do(): use each
    # hypothesis's TRUE-weight-magnitude analog (orientation differs; weight magnitude reused).
    c = SCM_PARAMS["do_value"]
    base = [predict_do_means(fam.n, h, m, -1, 0.0) for h, m in zip(fam.pool, mechs)]
    split = 0
    for k in range(fam.n):
        sigs = {signature(fam.n, h, m, k, c, base[i], tol) for i, (h, m) in enumerate(zip(fam.pool, mechs))}
        if len(sigs) > 1:
            split += 1
    return split / fam.n


def _hyp_w(fam: Family, h: dict, q: int, j: int) -> float:
    """Weight magnitude for a hypothesis edge q->j: reuse the true weight of the underlying skeleton
    edge (orientation-flipped edges keep magnitude — validity heuristic only, never used by arms)."""
    return fam.weights.get((j, q), 1.0)


def valid_family(fam: Family, tol: float) -> bool:
    p = SCM_PARAMS
    return len(fam.pool) >= p["mec_min"] and informative_fraction(fam, tol) <= p["informative_frac_max"]
