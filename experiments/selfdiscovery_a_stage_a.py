"""SELFDISCOVERY-A Stage A — Spearman-rank skeleton probe.

Tests whether CI-test linearity is the recall ceiling on real Sachs. ~5 lines over the
existing GGM precision-matrix pipeline: rank-transform columns, feed into the UNCHANGED
pipeline, compare skeleton recall at matched precision vs the linear (Pearson) version.

THIS IS A VERIFY-DON'T-ASSERT PROBE, NOT A BUILD. If rank recall <= linear recall at
every matched-precision point, test-linearity is NOT the cap — do not build a kernel/HSIC
arm, and Stages B/C do not proceed on the recall premise.

Design (from formal-model-and-algorithm-spec):
- spearman_rank_transform: average-rank ties, monotone-invariant. Pure stdlib.
- propose_skeleton_linear: GGM precision-matrix pipeline on original (standardized) data.
- propose_skeleton_rank: same pipeline on rank-transformed columns.
- stage_a_probe: iterate thresholds, record recall/precision per arm, set GATE_pass.
- Writes selfdiscovery_a_stage_a.result.json (raw data only, no verdict).

Boundaries:
- No :106 oracle; ground-truth skeleton used ONLY to compute recall/precision as REPORT.
- No hyperparameter tuned against Sachs recall; tau_grid preregistered at freeze.
- Pure stdlib. Deterministic (no random seeds in the probe — the CI test is deterministic).
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path


def spearman_rank_transform(obs: list[list[float]]) -> list[list[float]]:
    """Convert each data column to ranks (average-rank for ties).

    Pure stdlib. For n columns x m rows, output is m rows of rank values (1-indexed).
    Ranks are monotone-invariant: any monotone-increasing transformation of a column
    produces the same rank vector. This captures monotone nonlinear dependence that
    the linear Pearson partial correlation misses.

    Args:
        obs: list-of-lists, obs[row_idx][col_idx]. All rows same length.
    Returns:
        ranked: same shape, each column replaced by its Spearman rank values.
    """
    if not obs:
        raise ValueError("obs must be non-empty")
    n_cols = len(obs[0])
    ranked = [[0.0] * n_cols for _ in obs]
    for c in range(n_cols):
        col_vals = [(obs[r][c], r) for r in range(len(obs))]
        col_vals.sort(key=lambda x: x[0])
        i = 0
        while i < len(col_vals):
            j = i
            while j < len(col_vals) and col_vals[j][0] == col_vals[i][0]:
                j += 1
            avg_rank = (i + j + 1) / 2.0  # 1-indexed average
            for k in range(i, j):
                ranked[col_vals[k][1]][c] = avg_rank
            i = j
    return ranked


def _standardize(obs: list[list[float]]) -> list[list[float]]:
    cols = list(zip(*obs))
    means = [statistics.mean(c) for c in cols]
    sds = [statistics.pstdev(c) or 1.0 for c in cols]
    n = len(cols)
    return [[(obs[r][j] - means[j]) / sds[j] for j in range(n)] for r in range(len(obs))]


def _cov(rows: list[list[float]]) -> list[list[float]]:
    m = len(rows)
    n = len(rows[0])
    means = [sum(r[j] for r in rows) / m for j in range(n)]
    return [[sum((rows[t][i] - means[i]) * (rows[t][j] - means[j]) for t in range(m)) / (m - 1)
             for j in range(n)] for i in range(n)]


def _inv(A: list[list[float]]) -> list[list[float]]:
    n = len(A)
    M = [[A[i][j] + (1e-6 if i == j else 0.0) for j in range(n)] + [1.0 if i == j else 0.0 for j in range(n)]
          for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[piv] = M[piv], M[col]
        p = M[col][col] or 1e-12
        M[col] = [v / p for v in M[col]]
        for r in range(n):
            if r != col and M[r][col] != 0.0:
                f = M[r][col]
                M[r] = [M[r][j] - f * M[col][j] for j in range(2 * n)]
    return [row[n:] for row in M]


def _partial_correlation(prec: list[list[float]], i: int, j: int) -> float:
    denom = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
    return abs(prec[i][j]) / denom


def propose_skeleton_linear(obs: list[list[float]], tau: float = 0.1) -> set[frozenset[int]]:
    """GGM precision-matrix skeleton proposer on standardized (linear) data."""
    n = len(obs[0])
    prec = _inv(_cov(_standardize(obs)))
    edges = set()
    for i in range(n):
        for j in range(i + 1, n):
            if _partial_correlation(prec, i, j) > tau:
                edges.add(frozenset({i, j}))
    return edges


def propose_skeleton_rank(obs: list[list[float]], tau: float = 0.1) -> set[frozenset[int]]:
    """GGM precision-matrix skeleton proposer on rank-transformed data. ~5 lines change."""
    ranked = spearman_rank_transform(obs)
    std_ranked = _standardize(ranked)
    prec = _inv(_cov(std_ranked))
    n = len(obs[0])
    edges = set()
    for i in range(n):
        for j in range(i + 1, n):
            if _partial_correlation(prec, i, j) > tau:
                edges.add(frozenset({i, j}))
    return edges


def skeleton_recall_precision(
    proposed: set[frozenset[int]], true_skeleton: set[frozenset[int]]
) -> tuple[float, float]:
    """Compute recall and precision of proposed skeleton vs ground-truth."""
    if not true_skeleton:
        return (0.0, 0.0)
    tp = len(proposed & true_skeleton)
    recall = tp / len(true_skeleton)
    precision = tp / len(proposed) if proposed else 0.0
    return (recall, precision)


def stage_a_probe(
    obs: list[list[float]],
    true_skeleton: set[frozenset[int]],
    tau_grid: list[float] | None = None,
    matched_precisions: list[float] | None = None,
) -> dict:
    """Run Stage A probe: compare linear vs rank skeleton recall at matched precision.

    GATE_pass = True if there exists a threshold where recall_rank > recall_linear
    at matched or better precision. This is a measurement, never hard-coded.

    Args:
        obs: observational data rows x cols.
        true_skeleton: ground-truth undirected edges (REPORT ONLY, never in the pipeline).
        tau_grid: thresholds to sweep. Default: fine grid from 0.02 to 0.40.
        matched_precisions: precision points to report at. Default: [0.625, 0.889, 1.0].
    Returns:
        dict with recall_linear, recall_rank, precision_linear, precision_rank
        (each a dict from threshold to value), GATE_pass (bool), tau_grid.
    """
    if tau_grid is None:
        tau_grid = [round(x, 3) for x in
                    [0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30, 0.35, 0.40]]
    if matched_precisions is None:
        matched_precisions = [0.625, 0.889, 1.0]

    n = len(obs[0])
    result_raw = {
        "n_nodes": n,
        "n_obs": len(obs),
        "true_edges": len(true_skeleton),
        "tau_grid": tau_grid,
        "linear": {},
        "rank": {},
    }

    for tau in tau_grid:
        sk_lin = propose_skeleton_linear(obs, tau)
        rec_lin, prec_lin = skeleton_recall_precision(sk_lin, true_skeleton)
        result_raw["linear"][str(tau)] = {"recall": rec_lin, "precision": prec_lin}

        sk_rank = propose_skeleton_rank(obs, tau)
        rec_rank, prec_rank = skeleton_recall_precision(sk_rank, true_skeleton)
        result_raw["rank"][str(tau)] = {"recall": rec_rank, "precision": prec_rank}

    gate_pass = False
    for tau in tau_grid:
        tau_s = str(tau)
        prec_lin = result_raw["linear"][tau_s]["precision"]
        prec_rank = result_raw["rank"][tau_s]["precision"]
        rec_lin = result_raw["linear"][tau_s]["recall"]
        rec_rank = result_raw["rank"][tau_s]["recall"]
        for mp in matched_precisions:
            if prec_rank >= mp and prec_lin >= mp:
                if rec_rank > rec_lin:
                    gate_pass = True
                    break
        if gate_pass:
            break

    recall_linear = {tau_s: result_raw["linear"][tau_s]["recall"] for tau_s in result_raw["linear"]}
    recall_rank = {tau_s: result_raw["rank"][tau_s]["recall"] for tau_s in result_raw["rank"]}
    precision_linear = {tau_s: result_raw["linear"][tau_s]["precision"] for tau_s in result_raw["linear"]}
    precision_rank = {tau_s: result_raw["rank"][tau_s]["precision"] for tau_s in result_raw["rank"]}

    return {
        "recall_linear": recall_linear,
        "recall_rank": recall_rank,
        "precision_linear": precision_linear,
        "precision_rank": precision_rank,
        "GATE_pass": gate_pass,
        "tau_grid": tau_grid,
        "_raw": result_raw,
    }


def write_result_file(result: dict, path: str = "selfdiscovery_a_stage_a.result.json") -> None:
    """Write raw probe results to JSON. This is a RECORD, not a verdict."""
    record = {
        "prereg_id": "SELFDISCOVERY-A",
        "stage": "A",
        "GATE_pass": result["GATE_pass"],
        "tau_grid": result["tau_grid"],
        "recall_linear": result["recall_linear"],
        "recall_rank": result["recall_rank"],
        "precision_linear": result["precision_linear"],
        "precision_rank": result["precision_rank"],
        "note": "Stage A verify-don't-assert probe. GATE_pass=True means rank recall > linear "
                "at matched-or-better precision at some threshold. If GATE_pass=False, "
                "test-linearity is NOT the recall cap — do not build kernel/HSIC; "
                "Stages B/C do not proceed on the recall premise.",
    }
    out_path = Path(path)
    if not out_path.is_absolute():
        out_path = Path(__file__).parent / path
    out_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from experiments.sachs_task import load_obs, GROUND_TRUTH, PROTEINS
    obs = load_obs()
    true_sk = {frozenset({PROTEINS.index(a), PROTEINS.index(b)}) for a, b in GROUND_TRUTH}
    result = stage_a_probe(obs, true_sk)
    write_result_file(result)
    gate = "PASS" if result["GATE_pass"] else "FAIL"
    print(f"Stage A probe complete. GATE: {gate}")
    for tau in result["tau_grid"]:
        tau_s = str(tau)
        rl = result["recall_linear"].get(tau_s, "N/A")
        rr = result["recall_rank"].get(tau_s, "N/A")
        print(f"  tau={tau_s}: linear recall={rl}, rank recall={rr}")
