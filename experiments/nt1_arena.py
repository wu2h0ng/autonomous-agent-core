"""NT-1 arena — confounded multi-environment linear SCMs (RR-0045 discriminator construction).

Latent confounders (unobserved) each drive 2-3 observed nodes with strong weights -> marginal
correlation ranks confounded NON-edges above true edges (the screening proposer's structural blind
spot), while least-squares residual structure (NOTEARS) retains true edges. Environments differ in
per-node AND per-latent noise scales (soft variance interventions) -> confounded regression
coefficients SHIFT across envs while true mechanism coefficients stay invariant -> the discrete
invariance rule can kill confounded candidates. Named RNG streams; frozen params."""
from __future__ import annotations

import random

NT_PARAMS = {
    "d": 30, "n_per_env": 300, "n_envs": 3,
    "p_edge": 1.6,              # expected out-degree factor for the observed DAG
    "w_lo": 0.7, "w_hi": 1.3,
    "n_latents": 8, "latent_children": 3, "latent_w": 1.2,
    "noise_lo": 0.5, "noise_hi": 1.5,
    "env_scale_lo": 0.6, "env_scale_hi": 1.8,   # per-env multiplier on node AND latent noise
}


def _stream(tag):
    return random.Random(f"NT1|{tag}")


class Arena:
    def __init__(self, seed: int):
        p = NT_PARAMS
        r = _stream(f"gen|{seed}")
        d = p["d"]
        order = list(range(d))
        r.shuffle(order)
        pos = {v: i for i, v in enumerate(order)}
        self.edges = {}
        for a in range(d):
            for b in range(d):
                if pos[a] < pos[b] and r.random() < p["p_edge"] / d:
                    self.edges[(a, b)] = r.uniform(p["w_lo"], p["w_hi"]) * r.choice((-1, 1))
        self.latents = []
        for _ in range(p["n_latents"]):
            kids = r.sample(range(d), p["latent_children"])
            ws = [p["latent_w"] * r.choice((-1, 1)) for _ in kids]
            self.latents.append((kids, ws))
        self.node_sd = [r.uniform(p["noise_lo"], p["noise_hi"]) for _ in range(d)]
        self.env_scales = [[r.uniform(p["env_scale_lo"], p["env_scale_hi"]) for _ in range(d + p["n_latents"])]
                           for _ in range(p["n_envs"])]
        self.order, self.seed, self.d = order, seed, d

    def sample_env(self, e: int, n: int | None = None):
        p = NT_PARAMS
        n = n or p["n_per_env"]
        r = _stream(f"data|{self.seed}|{e}")
        rows = []
        for _ in range(n):
            z = [r.gauss(0, self.env_scales[e][self.d + k]) for k in range(p["n_latents"])]
            x = [0.0] * self.d
            for v in self.order:
                val = sum(w * x[a] for (a, b), w in self.edges.items() if b == v)
                for k, (kids, ws) in enumerate(self.latents):
                    if v in kids:
                        val += ws[kids.index(v)] * z[k]
                x[v] = val + r.gauss(0, self.node_sd[v] * self.env_scales[e][v])
            rows.append(x)
        return rows

    def true_edges(self):
        return set(self.edges.keys())


def standardize(X):
    d, n = len(X[0]), len(X)
    out = [[0.0] * d for _ in range(n)]
    for j in range(d):
        col = [X[i][j] for i in range(n)]
        m = sum(col) / n
        s = (sum((v - m) ** 2 for v in col) / n) ** 0.5 or 1.0
        for i in range(n):
            out[i][j] = (col[i] - m) / s
    return out
