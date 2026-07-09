"""Evaluation metrics for CWM discovery without a known ground-truth DAG.

These metrics use held-out observational and interventional data to score a
predicted causal graph.  They are deliberately cheap (linear baselines) so they
can be computed on real systems where the true DAG is unknown.
"""
from __future__ import annotations

import math
import statistics
from typing import Any


def _topological_order(n_nodes: int, edges: set[tuple[int, int]]) -> list[int]:
    """Return a topological order of nodes respecting ``edges``."""
    parents: dict[int, list[int]] = {j: [] for j in range(n_nodes)}
    for u, v in edges:
        parents[v].append(u)
    indeg = {j: len(parents[j]) for j in range(n_nodes)}
    queue = [j for j in range(n_nodes) if indeg[j] == 0]
    order: list[int] = []
    while queue:
        j = queue.pop(0)
        order.append(j)
        for u, v in edges:
            if u == j:
                indeg[v] -= 1
                if indeg[v] == 0:
                    queue.append(v)
    for j in range(n_nodes):
        if j not in order:
            order.append(j)
    return order


def _ols_coeffs(
    obs: list[list[float]], target: int, parents: set[int]
) -> tuple[float, dict[int, float]]:
    """Return ``(intercept, {parent: coefficient})`` for a linear model.

    Uses ordinary least squares via the normal equation with pure stdlib.
    If there are no parents, returns the mean of the target as intercept.
    """
    n = len(obs)
    if n == 0:
        return 0.0, {}
    parent_list = sorted(parents)
    p = len(parent_list)
    if p == 0:
        return statistics.mean(row[target] for row in obs), {}

    # Build X^T X and X^T y
    xtx: list[list[float]] = [[0.0] * (p + 1) for _ in range(p + 1)]
    xty: list[float] = [0.0] * (p + 1)
    for row in obs:
        x = [1.0] + [row[i] for i in parent_list]
        y = row[target]
        for i in range(p + 1):
            for j in range(p + 1):
                xtx[i][j] += x[i] * x[j]
            xty[i] += x[i] * y

    # Solve with Gaussian elimination and partial pivoting.
    beta = _solve_linear(xtx, xty)
    intercept = beta[0]
    coeffs = {parent_list[i]: beta[i + 1] for i in range(p)}
    return intercept, coeffs


def _solve_linear(a: list[list[float]], b: list[float]) -> list[float]:
    """Solve a square linear system ``a x = b`` with partial pivoting."""
    n = len(a)
    aug = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            continue
        aug[col], aug[pivot] = aug[pivot], aug[col]
        piv = aug[col][col]
        for j in range(col, n + 1):
            aug[col][j] /= piv
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col]
            for j in range(col, n + 1):
                aug[r][j] -= factor * aug[col][j]
    return [aug[i][n] for i in range(n)]


def _predict_row(
    row: list[float],
    do_node: int,
    do_value: float,
    models: dict[int, tuple[float, dict[int, float]]],
    order: list[int],
) -> list[float]:
    """Predict a full row under ``do(do_node=do_value)`` using fitted models."""
    pred = list(row)
    pred[do_node] = do_value
    for j in order:
        if j == do_node:
            continue
        intercept, coeffs = models[j]
        val = intercept
        for p, c in coeffs.items():
            val += c * pred[p]
        pred[j] = val
    return pred


def predictive_validation_score(
    obs: list[list[float]],
    int_data: list[tuple[int, float, list[float]]],
    predicted_edges: set[tuple[int, int]],
) -> dict[str, Any]:
    """Score ``predicted_edges`` by its ability to predict held-out interventions.

    For each node, a linear model is fit from observational data using the
    predicted parents.  Each interventional sample is then predicted by setting
    the intervened node to its value and propagating through the DAG in
    topological order.  The baseline predicts the observational marginal mean for
    every non-intervened node.

    Returns:
        dict with ``model_rmse``, ``baseline_rmse``, ``relative_improvement``,
        ``n_samples``.
    """
    n_nodes = len(obs[0]) if obs else 0
    if not int_data or n_nodes == 0:
        return {
            "model_rmse": None,
            "baseline_rmse": None,
            "relative_improvement": None,
            "n_samples": 0,
        }

    parent_map: dict[int, set[int]] = {j: set() for j in range(n_nodes)}
    for u, v in predicted_edges:
        if 0 <= u < n_nodes and 0 <= v < n_nodes:
            parent_map[v].add(u)

    models: dict[int, tuple[float, dict[int, float]]] = {}
    for j in range(n_nodes):
        models[j] = _ols_coeffs(obs, j, parent_map[j])

    order = _topological_order(n_nodes, predicted_edges)
    marginal_means = [statistics.mean(row[j] for row in obs) for j in range(n_nodes)]

    model_sq = 0.0
    baseline_sq = 0.0
    count = 0
    for do_node, do_value, outcome in int_data:
        pred_row = _predict_row(outcome, do_node, do_value, models, order)
        for j in range(n_nodes):
            if j == do_node:
                continue
            err = outcome[j] - pred_row[j]
            model_sq += err * err
            base_err = outcome[j] - marginal_means[j]
            baseline_sq += base_err * base_err
            count += 1

    model_rmse = math.sqrt(model_sq / count) if count else None
    baseline_rmse = math.sqrt(baseline_sq / count) if count else None
    rel = None
    if baseline_rmse and baseline_rmse > 0 and model_rmse is not None:
        rel = round((baseline_rmse - model_rmse) / baseline_rmse, 4)

    return {
        "model_rmse": round(model_rmse, 4) if model_rmse is not None else None,
        "baseline_rmse": round(baseline_rmse, 4) if baseline_rmse is not None else None,
        "relative_improvement": rel,
        "n_samples": len(int_data),
    }


def interventional_agreement_score(
    obs: list[list[float]],
    int_data: list[tuple[int, float, list[float]]],
    predicted_edges: set[tuple[int, int]],
) -> dict[str, Any]:
    """Score how well the predicted DAG agrees with the *direction* of shifts.

    For each intervention sample, the empirical shift relative to the
    observational mean is compared to the shift predicted by the fitted linear
    model.  Returns ``direction_accuracy`` (fraction of non-zero shifted
    dimensions where signs agree) and ``shift_rmse``.
    """
    n_nodes = len(obs[0]) if obs else 0
    if not int_data or n_nodes == 0:
        return {"direction_accuracy": None, "shift_rmse": None, "n_samples": 0}

    parent_map: dict[int, set[int]] = {j: set() for j in range(n_nodes)}
    for u, v in predicted_edges:
        if 0 <= u < n_nodes and 0 <= v < n_nodes:
            parent_map[v].add(u)

    models: dict[int, tuple[float, dict[int, float]]] = {}
    for j in range(n_nodes):
        models[j] = _ols_coeffs(obs, j, parent_map[j])

    order = _topological_order(n_nodes, predicted_edges)
    marginal_means = [statistics.mean(row[j] for row in obs) for j in range(n_nodes)]

    sign_matches = 0
    sign_count = 0
    sq = 0.0
    count = 0
    for do_node, do_value, outcome in int_data:
        pred_row = _predict_row(outcome, do_node, do_value, models, order)
        for j in range(n_nodes):
            if j == do_node:
                continue
            empirical_shift = outcome[j] - marginal_means[j]
            predicted_shift = pred_row[j] - marginal_means[j]
            sq += (empirical_shift - predicted_shift) ** 2
            count += 1
            if empirical_shift != 0.0:
                sign_count += 1
                if (empirical_shift > 0) == (predicted_shift > 0):
                    sign_matches += 1

    shift_rmse = math.sqrt(sq / count) if count else None
    accuracy = sign_matches / sign_count if sign_count else None
    return {
        "direction_accuracy": round(accuracy, 4) if accuracy is not None else None,
        "shift_rmse": round(shift_rmse, 4) if shift_rmse is not None else None,
        "n_samples": len(int_data),
    }
