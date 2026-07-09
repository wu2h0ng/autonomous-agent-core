"""Online Intervention Value Optimization — BOSS-style Bayesian optimization.

Replaces the fixed intervention value grid [-σ, -0.5σ, 0, 0.5σ, σ] with
online optimization: at each round, use the current posterior's particle
weights to identify intervention values that maximize expected divergence
between the highest-weighted candidate DAGs.

BOSS (Tigas+2022, NeurIPS): Bayesian Optimal experimental design for
Structure learning at Scale. Uses expected information gain to select both
intervention target AND intervention value simultaneously.

Our adaptation: takes the GovernedDiBS posterior + observational data,
computes per-node divergence curves across candidate values, and returns
the optimal (node, value) pair that maximizes expected posterior entropy
reduction.

Pure stdlib. Pluggable into GovernedDiscoveryLoop or GovernedDiBS.
"""
from __future__ import annotations

import math
import random
import statistics

from .bayesian_dag_posterior import GovernedDiBS, _parent_adjacency, _ols_coefficients


def fit_mechanism_for_dag(
    dag: frozenset, obs: list[list[float]], target_node: int,
) -> dict:
    n = len(obs[0])
    parents = _parent_adjacency(n, dag)
    pa = parents[target_node]
    if not pa:
        return {"type": "root", "mean": statistics.mean([obs[t][target_node] for t in range(len(obs))])}
    X = [[obs[t][p] for p in pa] for t in range(len(obs))]
    y = [obs[t][target_node] for t in range(len(obs))]
    try:
        beta = _ols_coefficients(X, y)
    except (ValueError, ZeroDivisionError):
        return {"type": "constant", "mean": statistics.mean(y)}
    rss = sum((y[t] - sum(beta[pi]*X[t][pi] for pi in range(len(pa))))**2 for t in range(len(y)))
    sigma = math.sqrt(max(rss / max(len(y)-len(pa), 1), 1e-9))
    return {"type": "linear", "beta": beta, "sigma": sigma, "parents": pa}


def predict_under_intervention(
    mechanism: dict, intervention_value: float, baseline_means: dict[int, float],
) -> float:
    if mechanism["type"] == "root":
        return mechanism["mean"]
    if mechanism["type"] == "constant":
        return mechanism["mean"]
    pa = mechanism["parents"]
    inp = [intervention_value if p in [k for k in range(100)][:len(pa)] and pa[p_idx]==p
           else baseline_means.get(p, 0.0)
           for p_idx, p in enumerate(pa)]
    return sum(mechanism["beta"][pi] * inp[pi] for pi in range(len(inp)))


def optimize_intervention_values(
    di: GovernedDiBS,
    obs: list[list[float]],
    intervenable_nodes: set[int],
    n_values: int = 5,
    n_samples: int = 20,
) -> dict[int, list[float]]:
    """BOSS-style: optimize intervention values per node from posterior.

    For each intervenable node, evaluates candidate values against the
    top-weighted DAG particles. Returns values that maximize expected
    prediction divergence between high-weight DAGs — which maximizes
    per-intervention information gain.

    Args:
        di: GovernedDiBS posterior with current particle weights.
        obs: observational data.
        intervenable_nodes: legal intervention targets.
        n_values: number of values to return per node.
        n_samples: number of candidate values to evaluate per node.

    Returns:
        dict[node -> [values]] — optimal intervention values per node.
    """
    n = len(obs[0])
    legal = {k for k in intervenable_nodes if k < n}
    if not legal:
        return {}

    top_particles = []
    for p_idx in range(di.P):
        if di.weights[p_idx] > 1e-6:
            top_particles.append((di.particles[p_idx], di.weights[p_idx]))
    top_particles.sort(key=lambda x: x[1], reverse=True)
    if not top_particles:
        return {}
    top_particles = top_particles[:min(len(top_particles), 10)]

    baseline_means = {}
    for k in range(n):
        col = [obs[t][k] for t in range(len(obs))]
        baseline_means[k] = statistics.mean(col)

    result: dict[int, list[float]] = {}
    for k in legal:
        col = [obs[t][k] for t in range(len(obs))]
        mu = statistics.mean(col); sd = statistics.pstdev(col) or 1.0
        candidates = [mu + a * sd for a in
                       [-2.0, -1.5, -1.0, -0.7, -0.5, -0.3, -0.1, 0.0, 0.1, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0]]

        children_k = set()
        for dag, _ in top_particles:
            for u, v in dag:
                if u == k: children_k.add(v)

        scored = []
        for val in candidates:
            div_sum = 0.0
            for child in children_k:
                preds = []
                for dag, w in top_particles:
                    mech = fit_mechanism_for_dag(dag, obs, child)
                    if mech["type"] == "linear":
                        pr = predict_under_intervention(mech, val, baseline_means)
                        preds.append((pr, w))
                if len(preds) >= 2:
                    pred_vals = [p[0] for p in preds]
                    div_sum += statistics.pstdev(pred_vals) if len(pred_vals) > 1 else 0
            scored.append((val, div_sum))
        scored.sort(key=lambda x: x[1], reverse=True)
        top_vals = [round(v, 2) for v, s in scored[:n_values] if s > 0]
        if not top_vals:
            top_vals = [round(mu + a * sd, 2) for a in [-1.0, -0.5, 0.0, 0.5, 1.0]][:n_values]
        result[k] = top_vals
    return result
