"""S&P 500 Sector ETF Causal Discovery — GovernedDiBS on financial market data.

Runs GovernedDiBS (M-GAP-2) on 11 S&P Select Sector SPDR ETFs:
- 2016 daily returns (2018-2026), pure stdlib CSV loading
- Compares linear vs poly2 likelihood
- Validates against known sector causal structure:
  Energy→Materials, Energy→Industrials, Financials→Real Estate,
  Technology→Comm Services, Health Care→exogenous
- Measures edge recovery vs sector-economics prior knowledge

Run: PYTHONPATH=src python experiments/sector_dibs.py
"""
from __future__ import annotations

import csv
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aac.bayesian_dag_posterior import GovernedDiBS

SECTORS = ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"]
SECTOR_NAMES = {
    "XLB": "Materials", "XLC": "Comm Services", "XLE": "Energy",
    "XLF": "Financials", "XLI": "Industrials", "XLK": "Technology",
    "XLP": "Consumer Staples", "XLRE": "Real Estate", "XLU": "Utilities",
    "XLV": "Health Care", "XLY": "Consumer Disc",
}
_DATA = os.path.join(os.path.dirname(__file__), "data")

KNOWN_EDGES = frozenset({
    (2, 0),   # XLE→XLB: Energy input costs → Materials
    (2, 4),   # XLE→XLI: Energy → Industrials
    (3, 7),   # XLF→XLRE: Financials → Real Estate (interest rates)
    (5, 1),   # XLK→XLC: Technology → Communication Services
    (4, 9),   # XLI→XLV: Industrial production → Health Care supply chain
    (3, 10),  # XLF→XLY: Financial conditions → Consumer spending
    (8, 3),   # XLU→XLF: Utility bonds/rates → Financials
})


def load_returns() -> list[list[float]]:
    """Load daily returns from CSV. Pure stdlib."""
    path = os.path.join(_DATA, "sp500_sectors.csv")
    with open(path) as f:
        reader = csv.reader(f)
        header = next(reader)
        col_map = {h.strip(): i for i, h in enumerate(header)}
        rows = []
        for row in reader:
            date = row[0].strip()
            vals = []
            for s in SECTORS:
                idx = col_map.get(f"'{s}'", col_map.get(s, -1))
                if idx >= 0:
                    vals.append(float(row[idx]))
            if len(vals) == len(SECTORS):
                rows.append(vals)
    returns = []
    for t in range(1, len(rows)):
        ret_row = []
        for j in range(len(SECTORS)):
            if rows[t-1][j] != 0:
                ret_row.append((rows[t][j] - rows[t-1][j]) / rows[t-1][j])
            else:
                ret_row.append(0.0)
        returns.append(ret_row)
    return returns


def standardize(obs: list[list[float]]) -> list[list[float]]:
    m, n = len(obs), len(obs[0])
    means = [0.0] * n
    for row in obs:
        for j in range(n):
            means[j] += row[j] / m
    stds = [0.0] * n
    for row in obs:
        for j in range(n):
            stds[j] += (row[j] - means[j]) ** 2
    for j in range(n):
        stds[j] = math.sqrt(stds[j] / m) or 1e-9
    return [[(obs[i][j] - means[j]) / stds[j] for j in range(n)] for i in range(m)]


def compute_metrics(predicted, truth):
    tp = len(predicted & truth)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1, tp


def run_sector_dibs(obs, mode, **params):
    di = GovernedDiBS(
        n_nodes=len(SECTORS),
        n_particles=params.get("n_particles", 40),
        lambda_sparse=params.get("lambda_sparse", 1.0),
        sigma_noise=params.get("sigma_noise", 1.0),
        seed=params.get("seed", 42),
        likelihood_mode=mode,
        posterior_temperature=params.get("posterior_temperature", 30.0),
    )
    for _ in range(params.get("n_svgd_steps", 8)):
        di.svgd_step(obs, n_gradient_edges=params.get("n_gradient_edges", 12))
    p, r, f1, tp = compute_metrics(frozenset(di.MAP_dag()), KNOWN_EDGES)
    return {
        "mode": mode,
        "MAP": di.MAP_dag(),
        "precision": p, "recall": r, "f1": f1, "tp": tp,
        "entropy": di.posterior_entropy(),
        "confidence": di.confidence(),
        "verdict": di.route(0.5),
        "n_map_edges": len(di.MAP_dag()),
    }


def main():
    raw = load_returns()
    if not raw:
        print("No return data found. Run data download first.")
        return
    obs = standardize(raw)
    obs = obs[-500:]
    n, m = len(SECTORS), len(obs)
    print(f"S&P 500 Sector Causal Discovery — {n} ETFs, {m} daily returns (last 500, standardized)")
    print(f"Sectors: {[SECTOR_NAMES[s] for s in SECTORS]}")
    print(f"Known edges: {[(SECTORS[a],SECTORS[b]) for a,b in sorted(KNOWN_EDGES)]}")
    print()

    results = {}
    for mode, label, params in [
        ("linear", "Linear SCM", {"n_particles": 40, "n_svgd_steps": 6, "n_gradient_edges": 12, "posterior_temperature": 30.0}),
        ("poly2", "Poly2 (NL)",  {"n_particles": 40, "n_svgd_steps": 6, "n_gradient_edges": 12, "posterior_temperature": 30.0}),
    ]:
        print(f"--- {label} ---")
        r = run_sector_dibs(obs, mode, **params)
        results[mode] = r
        print(f"  P={r['precision']:.3f} R={r['recall']:.3f} F1={r['f1']:.3f} TP={r['tp']}/{len(KNOWN_EDGES)}")
        print(f"  MAP edges={r['n_map_edges']} entropy={r['entropy']:.2f} conf={r['confidence']:.3f}")

        discovered = r['MAP'] & KNOWN_EDGES
        if discovered:
            named = [(SECTORS[a], SECTOR_NAMES[SECTORS[a]], SECTORS[b], SECTOR_NAMES[SECTORS[b]]) for a, b in sorted(discovered)]
            print(f"  Recovered known edges: {named}")
        print()

    lin, poly = results["linear"], results["poly2"]
    print("--- Comparison ---")
    print(f"  Linear:     P={lin['precision']:.3f} R={lin['recall']:.3f} F1={lin['f1']:.3f} TP={lin['tp']}/{len(KNOWN_EDGES)}")
    print(f"  Poly2 (NL): P={poly['precision']:.3f} R={poly['recall']:.3f} F1={poly['f1']:.3f} TP={poly['tp']}/{len(KNOWN_EDGES)}")
    print(f"  Delta F1:   {poly['f1'] - lin['f1']:+.3f}")
    print()
    print("Novel discovered edges (not in prior knowledge):")
    for mode, r in [("linear", lin), ("poly2", poly)]:
        novel = r['MAP'] - KNOWN_EDGES
        if novel:
            named = [(SECTORS[a], SECTORS[b]) for a, b in sorted(novel)]
            print(f"  {mode}: {named}")


if __name__ == "__main__":
    main()
