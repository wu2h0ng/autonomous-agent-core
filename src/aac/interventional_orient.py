"""Interventional Orientation — use do() data to determine causal direction.

For Sachs: 5400 interventional rows on 5 nodes (Mek, PIP2, Akt, PKA, PKC).
do(X) → check if Y's distribution shifts vs observational baseline → X→Y.

This is the DIRECT method: intervention reveals causation that observation cannot.
Pure stdlib. Plugs into ProductDiscoveryEngine orientation step.
"""
from __future__ import annotations

import math
import os
import statistics
from pathlib import Path


INTERVENABLE_SACHS = {"Mek": 2, "PIP2": 4, "Akt": 7, "PKA": 8, "PKC": 9}
INV_INTERVENABLE = {v: k for k, v in INTERVENABLE_SACHS.items()}


def load_sachs_int() -> list[tuple[list[int], int]]:
    for candidate in [
        os.path.join(os.path.dirname(__file__), "..", "experiments", "data", "sachs_int.txt"),
        os.path.join(os.path.dirname(__file__), "..", "..", "experiments", "data", "sachs_int.txt"),
    ]:
        if os.path.exists(candidate):
            path = candidate
            break
    else:
        raise FileNotFoundError("Cannot find sachs_int.txt")
    out = []
    with open(path) as f:
        for ln in f.read().splitlines()[1:]:
            if not ln.strip():
                continue
            parts = ln.split()
            vals = [int(v) for v in parts[:11]]
            out.append((vals, int(parts[11])))
    return out


def interventional_orient(
    obs: list[list[float]],
    skeleton: frozenset[frozenset],
    int_data: list[tuple[list[int], int]] | None = None,
    effect_threshold: float = 0.3,
) -> tuple[frozenset, float, dict]:
    """Orient skeleton edges using interventional data.

    For each undirected edge {i,j} where at least one node is intervenable:
    - Group int_data by intervention code
    - Compare do(i) group vs observational baseline on node j
    - If |effect| > threshold → i→j
    - If do(j) affects i → j→i
    - If neither intervenable → mark as 'unoriented'

    Args:
        obs: observational baseline data.
        skeleton: undirected edges to orient.
        int_data: Sachs-format interventional data (values, code).
        effect_threshold: minimum standardized mean diff for 'real effect'.

    Returns:
        (directed_dag, confidence, edge_details) where confidence = fraction of
        skeleton edges that could be tested and were confidently oriented.
    """
    if int_data is None:
        try:
            int_data = load_sachs_int()
        except (FileNotFoundError, OSError):
            return frozenset(), 0.0, {}

    n = len(obs[0])
    obs_baseline = {}
    for j in range(n):
        col = [obs[t][j] for t in range(len(obs))]
        obs_baseline[j] = {"mean": statistics.mean(col), "std": statistics.pstdev(col) or 1.0}

    by_code: dict[int, list[list[int]]] = {}
    for vals, code in int_data:
        by_code.setdefault(code, []).append(vals)

    directed = set()
    edge_details = {}
    tested = 0
    resolved = 0

    for undir in skeleton:
        parts = list(undir)
        if len(parts) != 2:
            continue
        i, j = parts[0], parts[1]
        i_intervenable = i in INV_INTERVENABLE
        j_intervenable = j in INV_INTERVENABLE

        detail = {"i": i, "j": j, "i_effect": None, "j_effect": None, "direction": "unknown"}

        if i_intervenable:
            code_i = INTERVENABLE_SACHS[INV_INTERVENABLE[i]]
            do_rows = by_code.get(code_i, [])
            if len(do_rows) >= 10:
                do_vals_j = [r[j] for r in do_rows]
                do_mean = statistics.mean(do_vals_j)
                do_std = statistics.pstdev(do_vals_j) or 1.0
                pooled_std = (obs_baseline[j]["std"] + do_std) / 2
                effect_i_on_j = abs(do_mean - obs_baseline[j]["mean"]) / max(pooled_std, 1e-9)
                detail["i_effect"] = round(effect_i_on_j, 3)
                tested += 1

        if j_intervenable:
            code_j = INTERVENABLE_SACHS[INV_INTERVENABLE[j]]
            do_rows = by_code.get(code_j, [])
            if len(do_rows) >= 10:
                do_vals_i = [r[i] for r in do_rows]
                do_mean = statistics.mean(do_vals_i)
                do_std = statistics.pstdev(do_vals_i) or 1.0
                pooled_std = (obs_baseline[i]["std"] + do_std) / 2
                effect_j_on_i = abs(do_mean - obs_baseline[i]["mean"]) / max(pooled_std, 1e-9)
                detail["j_effect"] = round(effect_j_on_i, 3)
                tested += 1

        eff_i = detail.get("i_effect")
        eff_j = detail.get("j_effect")

        if eff_i is not None and eff_i > effect_threshold:
            directed.add((i, j)); resolved += 1; detail["direction"] = f"{i}→{j}"
        if eff_j is not None and eff_j > effect_threshold:
            directed.add((j, i)); resolved += 1; detail["direction"] = f"{j}→{i}"
        if eff_i is None and eff_j is None:
            detail["direction"] = "neither_intervenable"
        elif eff_i is not None and eff_j is not None:
            if eff_i > effect_threshold and eff_j > effect_threshold:
                detail["direction"] = "bidirectional"
            elif eff_i <= effect_threshold and eff_j <= effect_threshold:
                detail["direction"] = "no_effect"

        edge_details[f"{i},{j}"] = detail

    conf = resolved / max(tested, 1) if tested > 0 else 0.0
    return frozenset(directed), conf, edge_details
