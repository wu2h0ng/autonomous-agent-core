"""Structure scorer for held-out interventions.

Computes AP and SHD for a predicted causal structure against an empirical
truth derived from held-out interventions. Never reads the ground-truth DAG.

Pure stdlib.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ScoreResult:
    """Result of scoring a predicted structure."""

    ap: float
    shd: int
    n_true: int
    n_predicted: int
    n_intersections: int
    empirical_truth: frozenset[tuple[int, int]]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    """Sample standard deviation using Welford's algorithm.

    Numerically stable for the larger k values used in Stage 3, where the
    naive two-pass formula can overflow on outlier-heavy intervention data.
    """
    if len(values) < 2:
        return 0.0
    count = 0
    mean = 0.0
    m2 = 0.0
    for x in values:
        count += 1
        delta = x - mean
        mean += delta / count
        delta2 = x - mean
        m2 += delta * delta2
    var = m2 / (count - 1) if count > 1 else 0.0
    return var ** 0.5


def empirical_truth_from_interventions(
    held_out_interventions: dict[tuple[int, float], list[list[float]]],
    observational_data: list[list[float]],
    effect_threshold: float = 1.5,
    use_sem_threshold: bool = True,
) -> frozenset[tuple[int, int]]:
    """Infer empirical true edges from held-out interventions.

    For each held-out do(X_i = x), compare the marginal mean of each other
    node X_j under the intervention to its observational mean. If the
    standardized effect exceeds the threshold, (i, j) is declared an
    empirical true edge.

    Args:
        held_out_interventions: dict mapping (target_node, value) -> data rows.
        observational_data: observational data rows.
        effect_threshold: minimum standardized effect to call an edge real.
        use_sem_threshold: if True, use mean / SEM; if False, use raw mean diff.

    Returns:
        frozenset of empirical true directed edges (i, j).
    """
    if not observational_data:
        return frozenset()
    n_nodes = len(observational_data[0])
    obs_mean = [_mean([row[j] for row in observational_data]) for j in range(n_nodes)]
    obs_std = [_std([row[j] for row in observational_data]) for j in range(n_nodes)]

    empirical: set[tuple[int, int]] = set()
    for (target, value), data in held_out_interventions.items():
        if not data:
            continue
        for j in range(n_nodes):
            if j == target:
                continue
            interv_values = [row[j] for row in data]
            interv_mean = _mean(interv_values)
            diff = abs(interv_mean - obs_mean[j])
            if use_sem_threshold:
                sem = _std(interv_values) / (len(interv_values) ** 0.5)
                denom = sem if sem > 1e-9 else 1.0
                score = diff / denom
            else:
                denom = obs_std[j] if obs_std[j] > 1e-9 else 1.0
                score = diff / denom
            if score >= effect_threshold:
                empirical.add((target, j))
    return frozenset(empirical)


def score_structure(
    predicted_edge_scores: dict[tuple[int, int], float],
    held_out_interventions: dict[tuple[int, float], list[list[float]]],
    observational_data: list[list[float]],
    effect_threshold: float = 0.2,
    score_threshold: float = 0.5,
) -> ScoreResult:
    """Score predicted structure by AP and SHD on held-out interventions.

    The ground-truth DAG is never read. Truth is empirical: edges that produce
    detectable shifts in held-out interventions.

    Args:
        predicted_edge_scores: dict (i, j) -> confidence score in [0, 1].
        held_out_interventions: held-out do() data.
        observational_data: observational data for baseline comparison.
        effect_threshold: threshold for empirical truth detection.
        score_threshold: threshold above which a predicted edge counts.

    Returns:
        ScoreResult with AP, SHD, and counts.
    """
    empirical_truth = empirical_truth_from_interventions(
        held_out_interventions, observational_data, effect_threshold
    )

    # binary prediction at threshold
    predicted_edges = {e for e, s in predicted_edge_scores.items() if s >= score_threshold}

    # AP: average precision over all possible edges, ranked by predicted score
    n_nodes = len(observational_data[0]) if observational_data else 0
    all_possible = {(i, j) for i in range(n_nodes) for j in range(n_nodes) if i != j}
    ranked = sorted(all_possible, key=lambda e: predicted_edge_scores.get(e, 0.0), reverse=True)

    tp_cum = 0
    fp_cum = 0
    precisions: list[float] = []
    for e in ranked:
        if e in empirical_truth:
            tp_cum += 1
        else:
            fp_cum += 1
        if e in predicted_edges:
            precisions.append(tp_cum / (tp_cum + fp_cum))

    ap = sum(precisions) / len(empirical_truth) if empirical_truth else 0.0

    # SHD: symmetric difference between predicted and empirical truth
    shd = len(predicted_edges ^ set(empirical_truth))

    return ScoreResult(
        ap=ap,
        shd=shd,
        n_true=len(empirical_truth),
        n_predicted=len(predicted_edges),
        n_intersections=len(predicted_edges & set(empirical_truth)),
        empirical_truth=empirical_truth,
    )


def score_against_true_dag(
    predicted_edge_scores: dict[tuple[int, int], float],
    true_dag: frozenset[tuple[int, int]],
    score_threshold: float = 0.5,
) -> ScoreResult:
    """Score predicted structure against the true DAG.

    This is for SYNTHETIC validation only, where the true DAG is known and
    used only by the scorer, never by the discovery arms. In real-data mode,
    use score_structure with held-out interventions.
    """
    n_nodes = max(max(u, v) for u, v in true_dag) + 1 if true_dag else 0
    all_possible = {(i, j) for i in range(n_nodes) for j in range(n_nodes) if i != j}
    ranked = sorted(all_possible, key=lambda e: predicted_edge_scores.get(e, 0.0), reverse=True)

    predicted_edges = {e for e, s in predicted_edge_scores.items() if s >= score_threshold}
    truth_set = set(true_dag)

    tp_cum = 0
    fp_cum = 0
    precisions: list[float] = []
    for e in ranked:
        if e in truth_set:
            tp_cum += 1
        else:
            fp_cum += 1
        if e in predicted_edges:
            precisions.append(tp_cum / (tp_cum + fp_cum))

    ap = sum(precisions) / len(truth_set) if truth_set else 0.0
    shd = len(predicted_edges ^ truth_set)

    return ScoreResult(
        ap=ap,
        shd=shd,
        n_true=len(truth_set),
        n_predicted=len(predicted_edges),
        n_intersections=len(predicted_edges & truth_set),
        empirical_truth=true_dag,
    )


def score_oracle_wrong_parameters(
    true_dag: frozenset[tuple[int, int]],
    held_out_interventions: dict[tuple[int, float], list[list[float]]],
    observational_data: list[list[float]],
    effect_threshold: float = 0.2,
) -> ScoreResult:
    """Sanity arm: know the true DAG but use wrong/random parameters.

    This should score poorly when using held-out interventions, proving the
    metric cannot be won by structure alone without correct mechanism
    parameters. In practice it may also score poorly in true-DAG mode if the
    scorer is threshold-free.
    """
    predicted = {e: 1.0 for e in true_dag}
    return score_structure(
        predicted,
        held_out_interventions,
        observational_data,
        effect_threshold=effect_threshold,
        score_threshold=0.5,
    )


if __name__ == "__main__":
    import random
    import sys
    sys.path.insert(0, "experiments")
    from scm_generator import generate_scm, SCMConfig

    world = generate_scm(SCMConfig(n_nodes=6, n_obs=500, seed=42))
    # split interventions into consultable and held-out
    all_keys = list(world.interventions.keys())
    rng = random.Random(123)
    rng.shuffle(all_keys)
    held_out_keys = all_keys[: len(all_keys) // 2]
    held_out = {k: world.interventions[k] for k in held_out_keys}

    # perfect prediction: use empirical truth itself
    truth = empirical_truth_from_interventions(held_out, world.observational, effect_threshold=1.5)
    scores = {e: 1.0 for e in truth}
    result = score_structure(scores, held_out, world.observational, effect_threshold=1.5)
    print("Perfect prediction:", result)

    # oracle with wrong params (still uses true DAG)
    oracle_result = score_oracle_wrong_parameters(world.dag, held_out, world.observational, effect_threshold=1.5)
    print("Oracle with wrong params:", oracle_result)
