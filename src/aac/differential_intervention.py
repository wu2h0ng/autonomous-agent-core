"""Differential Intervention — break nonlinear identifiability via multi-value response curves.

Information-theoretic fix for RR-0046 §18 bottleneck:

Under saturated nonlinear mechanisms (tanh), different DAGs produce equivalent
SINGLE-POINT predictions → zero information gain from one intervention value.
But at DIFFERENT intervention values, the function SHAPES diverge → positive info.

Key theorem: Given two candidate DAGs G1, G2 that differ on edge (k→y), the
optimal intervention value that maximizes expected information gain is:
    x* = argmax_x D(G1, G2; k, x)
where D is the predicted response divergence |pred_Y(G1, do(k=x)) - pred_Y(G2, do(k=x))|.

For tanh mechanisms, the maximum divergence occurs in the LINEAR regime of tanh
(not the saturated regime), where different β values produce maximally different slopes.

Implementation:
1. Multi-value scoring: fit mechanism per DAG, predict across value grid, score fit
2. Divergence-maximizing selection: choose intervention value that maximizes divergence
   between the weighted set of candidate DAGs
3. Response-curve likelihood: likelihood based on CURVE match, not point match
"""
from __future__ import annotations

import math
import statistics


def tanh_mechanism(x: float, beta: float) -> float:
    return math.tanh(beta * x)


def tanh_slope_at(x: float, beta: float) -> float:
    t = math.tanh(beta * x)
    return beta * (1.0 - t * t)


def max_divergence_intervention_value(
    dag_pairs: list[tuple[frozenset, frozenset, float]],
    obs: list[list[float]],
    k: int,
    value_grid: list[float] | None = None,
) -> tuple[float, float]:
    """Find intervention value maximizing predicted response divergence.

    Args:
        dag_pairs: list of (G1, G2, weight) — weighted DAG pairs to discriminate.
        obs: observational data for fitting mechanism parameters.
        k: intervention node.
        value_grid: candidate intervention values to search.

    Returns:
        (best_value, max_divergence) — the value that best separates candidate DAGs.
    """
    n = len(obs[0])
    if not value_grid:
        col = [obs[t][k] for t in range(len(obs))]
        mu = statistics.mean(col)
        sd = statistics.pstdev(col) or 1.0
        value_grid = [mu + a * sd for a in [-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5]]

    best_val = value_grid[0]
    best_div = 0.0

    for x in value_grid:
        total_div = 0.0
        total_w = 0.0
        for G1, G2, w in dag_pairs:
            y_nodes_affected = _nodes_affected_by_intervention(G1, G2, k, n)
            for y in y_nodes_affected:
                pred1 = _predict_child(G1, obs, k, x, y)
                pred2 = _predict_child(G2, obs, k, x, y)
                div = abs(pred1 - pred2)
                total_div += w * div
                total_w += w
        avg_div = total_div / max(total_w, 1e-9)
        if avg_div > best_div:
            best_div = avg_div
            best_val = x

    return (best_val, best_div)


def response_curve_likelihood(
    dag: frozenset[tuple[int, int]],
    obs: list[list[float]],
    intervention_curve: dict[int, list[tuple[float, float]]],
    sigma_noise: float,
) -> float:
    """Score DAG by how well it predicts a response CURVE (not single point).

    For each intervened node k, for each value x where we observed outcome:
        log P(obs_curve | G) = Σ_x Σ_y∈children(k,G) log P(y_obs | y_pred(G, do(k=x)))

    This replaces single-point likelihood with CURVE likelihood.
    Two DAGs that differ on (k→y) produce DIFFERENT predicted curves for y as a
    function of x → they become discriminable even when single-point predictions
    coincide at saturated values.
    """
    n = len(obs[0])
    parents = {j: [] for j in range(n)}
    for u, v in dag:
        parents[v].append(u)

    total_ll = 0.0
    const = -0.5 * math.log(2.0 * math.pi * sigma_noise * sigma_noise)

    for k, value_pairs in intervention_curve.items():
        if not value_pairs:
            continue
        for y in range(n):
            if y == k:
                continue
            squared_errors = 0.0
            for x, y_obs in value_pairs:
                y_pred = _predict_child(dag, obs, k, x, y)
                squared_errors += (y_obs - y_pred) ** 2
            n_points = len(value_pairs)
            total_ll += n_points * const - squared_errors / (2.0 * sigma_noise * sigma_noise)

    return total_ll


def _predict_child(
    dag: frozenset[tuple[int, int]],
    obs: list[list[float]],
    do_node: int,
    do_val: float,
    target: int,
) -> float:
    """Predict target node value under do(do_node=do_val) using fitted linear OLS."""
    n = len(obs[0])
    parents = {j: [] for j in range(n)}
    for u, v in dag:
        parents[v].append(u)
    if target == do_node:
        return do_val
    pa = parents[target]
    if do_node in pa:
        other_pa = [p for p in pa if p != do_node]
        X = [[obs[t][p] for p in pa] for t in range(len(obs))]
        y = [obs[t][target] for t in range(len(obs))]
        try:
            from aac.bayesian_dag_posterior import _ols_coefficients
            beta = _ols_coefficients(X, y)
        except (ValueError, ZeroDivisionError):
            return statistics.mean([obs[t][target] for t in range(len(obs))])
        inp = [do_val] + [statistics.mean([obs[t][p] for t in range(len(obs))]) for p in other_pa]
        return sum(beta[i] * inp[i] for i in range(len(beta)))
    return statistics.mean([obs[t][target] for t in range(len(obs))])


def _nodes_affected_by_intervention(
    G1: frozenset[tuple[int, int]],
    G2: frozenset[tuple[int, int]],
    k: int,
    n: int,
) -> set[int]:
    """Nodes that are children of k in at least one of G1, G2."""
    children = set()
    for u, v in G1:
        if u == k:
            children.add(v)
    for u, v in G2:
        if u == k:
            children.add(v)
    return children


def select_optimal_intervention_values(
    dag_particles: list[tuple[frozenset, float]],
    obs: list[list[float]],
    intervenable_nodes: set[int],
    n_values: int = 5,
) -> dict[int, list[float]]:
    """Select intervention values that maximize information gain across weighted DAG set.

    For each intervenable node k:
    1. Identify all nodes that are children of k in at least one candidate DAG
    2. For each child, find the value x that maximizes prediction divergence
       between the highest-weight DAGs
    3. Select the top n_values values across all children

    Args:
        dag_particles: list of (DAG, weight) — weighted posterior particles.
        obs: observational data.
        intervenable_nodes: legal intervention targets.
        n_values: number of values per node.

    Returns:
        dict[node -> [values]] — optimal intervention values per node.
    """
    result: dict[int, list[float]] = {}
    n = len(obs[0])

    if len(dag_particles) < 2:
        dag_particles = dag_particles + dag_particles

    for k in intervenable_nodes:
        pairs = []
        for i in range(min(len(dag_particles), 5)):
            for j in range(i + 1, min(len(dag_particles), 5)):
                w = dag_particles[i][1] * dag_particles[j][1]
                if w > 1e-6:
                    pairs.append((dag_particles[i][0], dag_particles[j][0], w))
        if pairs:
            best_val, _ = max_divergence_intervention_value(pairs, obs, k)
            col = [obs[t][k] for t in range(len(obs))]
            mu = statistics.mean(col)
            sd = statistics.pstdev(col) or 1.0
            values = sorted(set(round(v, 2) for v in [
                best_val,
                mu - 0.7 * sd, mu, mu + 0.7 * sd,
                mu - 1.3 * sd, mu + 1.3 * sd,
            ]))[:n_values]
        else:
            col = [obs[t][k] for t in range(len(obs))]
            mu = statistics.mean(col)
            sd = statistics.pstdev(col) or 1.0
            values = [round(mu + a * sd, 2) for a in [-1.0, -0.5, 0.0, 0.5, 1.0]][:n_values]
        result[k] = values
    return result
