"""Strong-locus crossover — synthetic SCM world generator.

Generates nonlinear / heteroscedastic / saturating SCMs that the loop's
linear-Gaussian (or poly2) likelihood does NOT correctly parametrize.
Also generates a placebo world: same marginal statistics, but the
"interventions" are arbitrary conditional resets with no stable causal
structure.

Pure stdlib. No numpy/scipy/torch.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional


def _topological_order(n_nodes: int, edges: frozenset[tuple[int, int]]) -> list[int]:
    """Return a topological order of the DAG."""
    parents = {j: [] for j in range(n_nodes)}
    for u, v in edges:
        parents[v].append(u)
    indeg = {j: len(parents[j]) for j in range(n_nodes)}
    order = []
    remaining = list(range(n_nodes))
    while remaining:
        ready = [j for j in remaining if indeg[j] == 0]
        if not ready:
            # cycle or bug — fall back to raw order
            order.extend(remaining)
            break
        ready.sort()
        j = ready[0]
        order.append(j)
        remaining.remove(j)
        for u, v in edges:
            if u == j and v in remaining:
                indeg[v] -= 1
    return order


def random_dag(
    n_nodes: int,
    edge_prob: float = 0.3,
    seed: Optional[int] = None,
) -> frozenset[tuple[int, int]]:
    """Generate a random DAG by shuffling a node order."""
    rng = random.Random(seed)
    order = list(range(n_nodes))
    rng.shuffle(order)
    edges = set()
    for i in range(n_nodes):
        for j in range(i + 1, n_nodes):
            if rng.random() < edge_prob:
                edges.add((order[i], order[j]))
    return frozenset(edges)


@dataclass(frozen=True)
class SCMConfig:
    """Configuration for a nonlinear/heteroscedastic/saturating SCM."""

    n_nodes: int = 10
    edge_prob: float = 0.3
    n_obs: int = 500
    noise_std_base: float = 0.3
    saturation: bool = True
    heteroscedastic: bool = True
    interactions: bool = True
    non_gaussian_noise: bool = True
    seed: Optional[int] = None


@dataclass
class SCMWorld:
    """A generated SCM world."""

    dag: frozenset[tuple[int, int]]
    edges: frozenset[tuple[int, int]] = field(repr=False)
    coefficients: dict[tuple[int, int], float]
    observational: list[list[float]]
    interventions: dict[tuple[int, float], list[list[float]]]
    intervention_effects: dict[int, list[tuple[int, float]]]
    rng_seed: int


def _mixture_noise(rng: random.Random, std: float) -> float:
    """Non-Gaussian noise: 50/50 mixture of two Gaussians with different means."""
    if rng.random() < 0.5:
        return rng.gauss(-0.4 * std, 0.7 * std)
    return rng.gauss(0.4 * std, 1.3 * std)


def _saturation(x: float) -> float:
    """Saturating transformation: bounded core + mild linear tails."""
    if x > 3.0:
        return 3.0 + 0.1 * (x - 3.0)
    if x < -3.0:
        return -3.0 + 0.1 * (x + 3.0)
    # Bounded, numerically stable saturation on the core interval.
    return 3.0 * math.tanh(x / 3.0)


def generate_scm(config: Optional[SCMConfig] = None) -> SCMWorld:
    """Generate a nonlinear/heteroscedastic/saturating SCM world.

    The mechanism is intentionally NOT linear-Gaussian:
      - parent effects are saturated;
      - noise can be heteroscedastic (depends on parent values);
      - interactions and quadratic terms are present;
      - noise is a Gaussian mixture when non_gaussian_noise=True.

    The loop's linear-Gaussian / poly2 likelihood therefore mismatches the
    true generative family.
    """
    config = config or SCMConfig()
    rng = random.Random(config.seed)
    n = config.n_nodes

    dag = random_dag(n, config.edge_prob, seed=rng.randrange(1 << 30))
    parents = {j: [] for j in range(n)}
    for u, v in dag:
        parents[v].append(u)

    # assign random edge coefficients
    coefs: dict[tuple[int, int], float] = {}
    for u, v in dag:
        coefs[(u, v)] = rng.uniform(0.4, 1.0) * rng.choice([1.0, -1.0])

    # precompute interaction terms for child nodes with >=2 parents
    interactions: dict[int, list[tuple[int, int, float]]] = {
        j: [] for j in range(n)
    }
    if config.interactions:
        for j in range(n):
            pa = parents[j]
            if len(pa) >= 2:
                for a in range(len(pa)):
                    for b in range(a + 1, len(pa)):
                        w = rng.uniform(-0.5, 0.5)
                        interactions[j].append((pa[a], pa[b], w))

    order = _topological_order(n, dag)

    def _row() -> list[float]:
        row = [0.0] * n
        for j in order:
            pa = parents[j]
            if not pa:
                val = rng.gauss(0.0, config.noise_std_base)
                if config.non_gaussian_noise:
                    val = _mixture_noise(rng, config.noise_std_base)
            else:
                # saturated linear combination
                linear = sum(coefs[(p, j)] * row[p] for p in pa)
                if config.saturation:
                    linear = _saturation(linear)

                # quadratic self-effect on parents
                quad = 0.0
                if config.interactions:
                    quad = sum(
                        0.15 * (row[p] ** 2 - 1.0) * rng.choice([1.0, -1.0])
                        for p in pa
                    )

                # interaction terms
                inter = 0.0
                for a, b, w in interactions[j]:
                    inter += w * row[a] * row[b]

                # heteroscedastic noise: variance grows with |linear|
                std = config.noise_std_base
                if config.heteroscedastic:
                    std *= (1.0 + 0.3 * abs(linear))

                noise = _mixture_noise(rng, std) if config.non_gaussian_noise else rng.gauss(0.0, std)
                val = linear + quad + inter + noise
                # Hard output clamp: the saturated core is bounded, but the
                # quadratic/interaction tails can explode for large k; clamp
                # after each node so downstream computations stay finite.
                val = max(-10.0, min(10.0, val))
            row[j] = val
        return row

    observational = [_row() for _ in range(config.n_obs)]

    # intervention library: do(X_i = x) for each node and a few values
    interventions: dict[tuple[int, float], list[list[float]]] = {}
    intervention_values = [-2.0, 0.0, 2.0]
    for target in range(n):
        for value in intervention_values:
            data: list[list[float]] = []
            for _ in range(config.n_obs // len(intervention_values)):
                row = [0.0] * n
                for j in order:
                    pa = parents[j]
                    if j == target:
                        # do-operator: set node to value, ignore parents
                        row[j] = value + rng.gauss(0.0, config.noise_std_base)
                    elif not pa:
                        noise = _mixture_noise(rng, config.noise_std_base) if config.non_gaussian_noise else rng.gauss(0.0, config.noise_std_base)
                        row[j] = noise
                    else:
                        linear = sum(coefs[(p, j)] * row[p] for p in pa)
                        if config.saturation:
                            linear = _saturation(linear)
                        quad = 0.0
                        if config.interactions:
                            quad = sum(
                                0.15 * (row[p] ** 2 - 1.0) * rng.choice([1.0, -1.0])
                                for p in pa
                            )
                        inter = 0.0
                        for a, b, w in interactions[j]:
                            inter += w * row[a] * row[b]
                        std = config.noise_std_base
                        if config.heteroscedastic:
                            std *= (1.0 + 0.3 * abs(linear))
                        noise = _mixture_noise(rng, std) if config.non_gaussian_noise else rng.gauss(0.0, std)
                        row[j] = linear + quad + inter + noise
                        # Keep intervention samples in the same finite range.
                        row[j] = max(-10.0, min(10.0, row[j]))
                data.append(row)
            interventions[(target, value)] = data

    # precompute true causal effects: for each target, list of (descendant, effect)
    effects: dict[int, list[tuple[int, float]]] = {j: [] for j in range(n)}
    for target in range(n):
        descendants = _descendants(target, dag)
        for desc in descendants:
            # rough effect size: sum of products of coefficients along directed paths
            eff = _total_effect(target, desc, dag, coefs, config.saturation)
            effects[target].append((desc, eff))

    return SCMWorld(
        dag=dag,
        edges=dag,
        coefficients=coefs,
        observational=observational,
        interventions=interventions,
        intervention_effects=effects,
        rng_seed=config.seed if config.seed is not None else 0,
    )


def _descendants(node: int, dag: frozenset[tuple[int, int]]) -> set[int]:
    children = {j for u, j in dag if u == node}
    result = set(children)
    for c in list(children):
        result |= _descendants(c, dag)
    return result


def _total_effect(
    source: int,
    target: int,
    dag: frozenset[tuple[int, int]],
    coefs: dict[tuple[int, int], float],
    saturation: bool,
    max_paths: int = 20,
) -> float:
    """Approximate total effect of do(source) on target by summing path products.

    Saturation makes true effects nonlinear; this is a linearized approximation
    used only for diagnostic / ground-truth labeling, not for scoring.
    """
    children = {j: [] for j in range(max(dag, key=lambda e: max(e))[0] + 1) if dag}
    if not dag:
        return 0.0
    n_nodes = max(max(u, v) for u, v in dag) + 1
    children = {j: [] for j in range(n_nodes)}
    for u, v in dag:
        children[u].append(v)

    paths: list[list[int]] = []

    def dfs(current: int, path: list[int]):
        if len(paths) >= max_paths:
            return
        if current == target:
            paths.append(list(path))
            return
        for child in children.get(current, []):
            if child not in path:
                path.append(child)
                dfs(child, path)
                path.pop()

    dfs(source, [source])

    total = 0.0
    for path in paths:
        prod = 1.0
        for i in range(len(path) - 1):
            prod *= coefs.get((path[i], path[i + 1]), 0.0)
            if saturation:
                # crude saturation penalty per hop
                prod *= 0.6
        total += prod
    return total


def residual_linear_gaussian_fit(
    data: list[list[float]],
    dag: frozenset[tuple[int, int]],
) -> dict[int, float]:
    """Fit a linear-Gaussian SCM and return per-node R^2.

    Low R^2 indicates mismatch between the world and a linear-Gaussian model.
    Pure stdlib OLS.
    """
    n_nodes = len(data[0])
    parents = {j: [] for j in range(n_nodes)}
    for u, v in dag:
        parents[v].append(u)

    r2s: dict[int, float] = {}
    for j in range(n_nodes):
        pa = parents[j]
        y = [row[j] for row in data]
        y_mean = sum(y) / len(y)
        tss = sum((yi - y_mean) ** 2 for yi in y)
        if not pa:
            r2s[j] = 0.0
            continue
        # OLS via normal equations (XtX beta = Xty)
        X = [[row[p] for p in pa] for row in data]
        XtX = [[sum(X[t][a] * X[t][b] for t in range(len(X))) for b in range(len(pa))] for a in range(len(pa))]
        Xty = [sum(X[t][a] * y[t] for t in range(len(X))) for a in range(len(pa))]
        beta = _solve_linear_system(XtX, Xty)
        preds = [sum(beta[a] * X[t][a] for a in range(len(pa))) for t in range(len(X))]
        rss = sum((y[t] - preds[t]) ** 2 for t in range(len(y)))
        r2s[j] = 1.0 - rss / tss if tss > 0 else 0.0
    return r2s


def _solve_linear_system(A: list[list[float]], b: list[float]) -> list[float]:
    """Solve Ax = b for small symmetric positive-definite A via Gaussian elimination."""
    n = len(A)
    M = [A[i][:] + [b[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[piv] = M[piv], M[col]
        p = M[col][col] or 1e-12
        M[col] = [v / p for v in M[col]]
        for r in range(n):
            if r != col and M[r][col] != 0.0:
                f = M[r][col]
                M[r] = [M[r][j] - f * M[col][j] for j in range(n + 1)]
    return [row[n] for row in M]


if __name__ == "__main__":
    # quick smoke test
    world = generate_scm(SCMConfig(n_nodes=6, n_obs=200, seed=42))
    print("DAG:", sorted(world.dag))
    print("obs shape:", len(world.observational), "x", len(world.observational[0]))
    r2 = residual_linear_gaussian_fit(world.observational, world.dag)
    print("linear-Gaussian R^2 per node:", [round(r2[j], 3) for j in range(len(r2))])
    avg_r2 = sum(r2.values()) / len(r2)
    print("avg R^2:", round(avg_r2, 3))
    if avg_r2 > 0.95:
        print("WARNING: world is too linear-Gaussian; mismatch may be weak")
    else:
        print("OK: linear-Gaussian likelihood mismatches the world")
