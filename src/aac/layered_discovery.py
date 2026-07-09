"""Layered Discovery — spectral clustering for n>20 causal discovery.

For n > 20, the DAG search space (2^(n²)) exceeds particle coverage. Layered
discovery partitions nodes via spectral clustering on the CI skeleton, then
runs GovernedDiBS independently on each cluster (n_eff ≤ 12, tractable).

Approach:
1. CI skeleton: partial correlation matrix → adjacency graph
2. Spectral clustering: normalized Laplacian → k clusters
3. Per-cluster GovernedDiBS: independent discovery on each subgraph
4. Merge: union of edges across clusters (loses cross-cluster edges but
   preserves within-cluster structure)

Product-level target: n=50 → 5 clusters of ~10 nodes each → 45 edge pairs
per cluster → 40 particles each → tractable.

Pure stdlib. Pluggable into GovernedDiscoveryLoop.
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass

from .cwm_organ import _standardize_cols, _cov, _inv
from .bayesian_dag_posterior import GovernedDiBS


def build_skeleton_adjacency(
    obs: list[list[float]], tau: float = 0.02,
) -> tuple[list[list[float]], set[frozenset]]:
    """Build undirected skeleton from partial correlation CI test."""
    n = len(obs[0])
    try:
        std = _standardize_cols(obs); prec = _inv(_cov(std))
    except (ValueError, ZeroDivisionError):
        return [[1.0 if i != j else 0.0 for j in range(n)] for i in range(n)], set()
    W = [[0.0] * n for _ in range(n)]
    edges = set()
    for i in range(n):
        for j in range(i + 1, n):
            denom = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
            pcorr = abs(prec[i][j]) / denom
            W[i][j] = W[j][i] = pcorr
            if pcorr > tau:
                edges.add(frozenset({i, j}))
    return W, edges


def spectral_cluster(
    W: list[list[float]], n_clusters: int,
) -> list[list[int]]:
    """Spectral clustering on weighted adjacency W.

    Uses normalized Laplacian L = I - D^(-1/2) W D^(-1/2).
    Computes k smallest eigenvectors, clusters via k-means on spectral embedding.
    Pure stdlib: power iteration for eigenvectors, k-means for clustering.
    """
    n = len(W)
    if n <= n_clusters:
        return [[i] for i in range(n)]

    degree = [max(sum(abs(W[i][j]) for j in range(n)), 1e-9) for i in range(n)]
    D_inv_sqrt = [[0.0] * n for _ in range(n)]
    for i in range(n):
        D_inv_sqrt[i][i] = 1.0 / math.sqrt(degree[i])
    L_sym = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            L_sym[i][j] = -D_inv_sqrt[i][i] * W[i][j] * D_inv_sqrt[j][j]
        L_sym[i][i] += 1.0

    eigenvectors = []
    for _ in range(n_clusters):
        v = [random.Random(_ + 42).uniform(-1, 1) for _ in range(n)]
        norm = math.sqrt(sum(x*x for x in v)) or 1e-9
        v = [x / norm for x in v]
        for _ in range(50):
            Av = [sum(L_sym[i][j] * v[j] for j in range(n)) for i in range(n)]
            for prev in eigenvectors:
                dot = sum(prev[i] * Av[i] for i in range(n))
                Av = [Av[i] - dot * prev[i] for i in range(n)]
            norm = math.sqrt(sum(x*x for x in Av)) or 1e-9
            v = [x / norm for x in Av]
        eigenvectors.append(v)

    embedding = [[eigenvectors[k][i] for k in range(n_clusters)] for i in range(n)]

    centroids = [list(embedding[i]) for i in range(0, n, max(1, n // n_clusters))[:n_clusters]]
    for _ in range(30):
        labels = []
        for emb in embedding:
            best_c = min(range(n_clusters), key=lambda c: sum((emb[d]-centroids[c][d])**2 for d in range(n_clusters)))
            labels.append(best_c)
        new_centroids = [[0.0] * n_clusters for _ in range(n_clusters)]
        counts = [0] * n_clusters
        for i, c in enumerate(labels):
            counts[c] += 1
            for d in range(n_clusters):
                new_centroids[c][d] += embedding[i][d]
        for c in range(n_clusters):
            if counts[c] > 0:
                centroids[c] = [v / counts[c] for v in new_centroids[c]]

    clusters = [[] for _ in range(n_clusters)]
    for i, c in enumerate(labels):
        clusters[c].append(i)
    return clusters


def layered_discover(
    obs: list[list[float]],
    n_clusters: int | None = None,
    max_cluster_size: int = 12,
    tau: float = 0.02,
    **di_kwargs,
) -> dict:
    """Layered discovery: cluster → per-cluster GovernedDiBS → merge.

    Args:
        obs: observational data.
        n_clusters: number of clusters (auto-computed if None).
        max_cluster_size: target max nodes per cluster (~12 for tractable DiBS).
        tau: CI test threshold for skeleton.
        **di_kwargs: passed to GovernedDiBS per cluster.

    Returns:
        dict with 'edges' (merged MAP DAG), 'clusters', 'per_cluster_stats'.
    """
    n = len(obs[0])
    if n_clusters is None:
        n_clusters = max(2, (n + max_cluster_size - 1) // max_cluster_size)

    if n <= max_cluster_size:
        di = GovernedDiBS(n_nodes=n, adaptive_particles=True, **di_kwargs)
        di.update(obs); di.svgd_step(obs, n_gradient_edges=15)
        di.hippocampal_replay(obs, replay_rounds=1)
        return {"edges": di.MAP_dag(), "clusters": [list(range(n))], "per_cluster": [{"n": n}],
                "n_clusters": 1}

    W, sk_edges = build_skeleton_adjacency(obs, tau)
    clusters = spectral_cluster(W, n_clusters)
    cluster_edges = []

    for c_idx, nodes in enumerate(clusters):
        if len(nodes) <= 1:
            continue
        sub_obs = [[obs[t][ni] for ni in nodes] for t in range(len(obs))]
        di = GovernedDiBS(n_nodes=len(nodes), adaptive_particles=True, **di_kwargs)
        di.update(sub_obs); di.svgd_step(sub_obs, n_gradient_edges=15)
        di.hippocampal_replay(sub_obs, replay_rounds=1)
        sub_map = di.MAP_dag()
        mapped_edges = frozenset({(nodes[u], nodes[v]) for u, v in sub_map})
        cluster_edges.append(mapped_edges)

    merged = frozenset()
    for ce in cluster_edges:
        merged = merged | ce
    return {"edges": merged, "clusters": clusters,
            "per_cluster": [{"n": len(nodes)} for nodes in clusters],
            "n_clusters": n_clusters}
