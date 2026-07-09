"""Sachs GovernedDiBS validation — real protein signaling causal discovery benchmark.

Runs GovernedDiBS (M-GAP-2 Algorithm 1) on the Sachs et al. 2005 dataset:
- 11 protein nodes, 17 consensus ground-truth edges
- 854 observational + 5,400 interventional measurements
- Compares linear vs poly2 (nonlinear) likelihood modes
- Measures edge recovery precision/recall/F1 vs ground truth
- Tests Bayesian safety: confident-wrong = 0 under poly2 mode

Run: PYTHONPATH=src python experiments/sachs_dibs.py
"""
from __future__ import annotations

import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aac.bayesian_dag_posterior import GovernedDiBS, _dag_log_likelihood, _dag_log_likelihood_poly2

PROTEINS = ["Raf", "Mek", "Plcg", "PIP2", "PIP3", "Erk", "Akt", "PKA", "PKC", "P38", "Jnk"]
GROUND_TRUTH = [
    ("PKC", "Raf"), ("PKC", "Mek"), ("PKC", "Jnk"), ("PKC", "P38"), ("PKC", "PKA"),
    ("PKA", "Raf"), ("PKA", "Mek"), ("PKA", "Erk"), ("PKA", "Akt"), ("PKA", "Jnk"), ("PKA", "P38"),
    ("Raf", "Mek"), ("Mek", "Erk"), ("Erk", "Akt"),
    ("Plcg", "PIP2"), ("Plcg", "PIP3"), ("PIP3", "PIP2"),
]
_DATA = os.path.join(os.path.dirname(__file__), "data")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aac.bayesian_dag_posterior import GovernedDiBS, _dag_log_likelihood, _dag_log_likelihood_poly2


def load_obs() -> list[list[float]]:
    with open(os.path.join(_DATA, "sachs_obs.txt")) as f:
        rows = [ln.split() for ln in f.read().splitlines()[1:] if ln.strip()]
    obs = [[float(v) for v in r] for r in rows]
    return obs


def standardize(obs: list[list[float]]) -> list[list[float]]:
    """Z-score standardize each column to zero mean, unit variance."""
    m = len(obs)
    n = len(obs[0])
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


N_NODES = len(PROTEINS)
GROUND_TRUTH_SET = frozenset(
    (PROTEINS.index(a), PROTEINS.index(b)) for a, b in GROUND_TRUTH
)


def compute_metrics(predicted: frozenset, truth: frozenset) -> dict:
    tp = len(predicted & truth)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {"tp": tp, "precision": precision, "recall": recall, "f1": f1}


def run_dibs_pipeline(
    obs: list[list[float]],
    mode: str = "linear",
    n_particles: int = 30,
    lambda_sparse: float = 0.5,
    sigma_noise: float = 0.5,
    n_svgd_steps: int = 6,
    n_gradient_edges: int = 12,
    confidence_threshold: float = 0.8,
    seed: int = 42,
) -> dict:
    """Run GovernedDiBS on Sachs data and return results."""
    rng = random.Random(seed)
    di = GovernedDiBS(
        n_nodes=N_NODES,
        n_particles=n_particles,
        lambda_sparse=lambda_sparse,
        sigma_noise=sigma_noise,
        seed=seed,
        rbf_bandwidth=3.0,
        svgd_step_size=1.0,
        likelihood_mode=mode,
        posterior_temperature=50.0,
    )

    confs = []
    for step in range(n_svgd_steps):
        di.svgd_step(obs, n_gradient_edges=n_gradient_edges)
        confs.append(di.confidence())

    predicted_edges = frozenset(di.MAP_dag())
    metrics = compute_metrics(predicted_edges, GROUND_TRUTH_SET)
    marginals = di.edge_marginals()

    high_conf_edges = frozenset(
        e for e in GROUND_TRUTH_SET
        if marginals.get(e, 0.0) > 0.5
    )
    missing_edges = set(GROUND_TRUTH_SET) - set(predicted_edges)

    confident_wrong = 0
    confidence_threshold_used = confidence_threshold
    verdict = di.route(confidence_threshold_used)
    for e in predicted_edges:
        if e not in GROUND_TRUTH_SET:
            prob = marginals.get(e, 0.0)
            if prob > confidence_threshold_used:
                confident_wrong += 1

    gt_ll = _dag_log_likelihood(GROUND_TRUTH_SET, obs, sigma_noise)
    poly_gt_ll = _dag_log_likelihood_poly2(GROUND_TRUTH_SET, obs, sigma_noise) if mode == "poly2" else 0.0
    map_ll = (
        _dag_log_likelihood_poly2(predicted_edges, obs, sigma_noise)
        if mode == "poly2"
        else _dag_log_likelihood(predicted_edges, obs, sigma_noise)
    )

    return {
        "mode": mode,
        "n_particles": n_particles,
        "n_svgd_steps": n_svgd_steps,
        "seed": seed,
        "MAP_edges": len(predicted_edges),
        "MAP": predicted_edges,
        "precision": metrics["precision"],
        "recall": metrics["recall"],
        "f1": metrics["f1"],
        "tp": metrics["tp"],
        "confidence_trajectory": confs,
        "final_confidence": di.confidence(),
        "verdict": verdict,
        "confident_wrong": confident_wrong,
        "missing_gt_edges": missing_edges,
        "gt_log_likelihood": gt_ll,
        "gt_poly2_log_likelihood": poly_gt_ll,
        "MAP_log_likelihood": map_ll,
        "posterior_entropy": di.posterior_entropy(),
    }


def main():
    obs_raw = load_obs()
    obs = standardize(obs_raw)
    print(f"Sachs GovernedDiBS — {N_NODES} proteins, {len(GROUND_TRUTH_SET)} GT edges, {len(obs)} obs rows (standardized)")
    print(f"Ground truth edges: {sorted(GROUND_TRUTH_SET)}")
    print(f"Protein names: {PROTEINS}\n")

    results = {}

    for mode, label, params in [
        ("linear", "Linear SCM", {"n_particles": 50, "lambda_sparse": 1.0, "sigma_noise": 1.0, "n_svgd_steps": 10, "n_gradient_edges": 15, "confidence_threshold": 0.75}),
        ("poly2", "Poly2 (nonlinear)", {"n_particles": 50, "lambda_sparse": 1.0, "sigma_noise": 1.0, "n_svgd_steps": 10, "n_gradient_edges": 15, "confidence_threshold": 0.75}),
    ]:
        print(f"--- {label} ({mode}) ---")
        r = run_dibs_pipeline(obs, mode=mode, **params)
        results[mode] = r

        print(f"  Precision: {r['precision']:.3f}, Recall: {r['recall']:.3f}, F1: {r['f1']:.3f}, TP: {r['tp']}/{len(GROUND_TRUTH_SET)}")
        print(f"  MAP edges: {r['MAP_edges']}, Final confidence: {r['final_confidence']:.4f}")
        print(f"  Verdict: {r['verdict']}, Confident-wrong: {r['confident_wrong']}")
        print(f"  GT log-likelihood: {r['gt_log_likelihood']:.1f}")
        if mode == "poly2":
            print(f"  GT poly2 log-likelihood: {r['gt_poly2_log_likelihood']:.1f}")
        print(f"  MAP log-likelihood: {r['MAP_log_likelihood']:.1f}")
        print(f"  Posterior entropy: {r['posterior_entropy']:.3f}")
        if r["missing_gt_edges"]:
            missing_names = [(PROTEINS[a], PROTEINS[b]) for a, b in r["missing_gt_edges"]]
            print(f"  Missing GT edges: {missing_names}")
        print()

    print("--- Comparison ---")
    lin = results["linear"]
    poly = results["poly2"]
    print(f"  Linear:      P={lin['precision']:.3f} R={lin['recall']:.3f} F1={lin['f1']:.3f} TP={lin['tp']}/{len(GROUND_TRUTH_SET)}")
    print(f"  Poly2 (NL):  P={poly['precision']:.3f} R={poly['recall']:.3f} F1={poly['f1']:.3f} TP={poly['tp']}/{len(GROUND_TRUTH_SET)}")
    print(f"  Delta F1:    {poly['f1'] - lin['f1']:+.3f}")
    print(f"  Confident-wrong: linear={lin['confident_wrong']} poly2={poly['confident_wrong']}")

    print()
    print("--- Bayesian Safety (M-GAP-2 P1) ---")
    if poly["confident_wrong"] == 0 and poly["final_confidence"] < 0.95:
        print("  PASS: poly2 Bayesian posterior avoids confident-wrong in nonlinear Sachs")
    else:
        print(f"  NOTE: poly2 confident_wrong={poly['confident_wrong']}, final_confidence={poly['final_confidence']:.4f}")

    print()
    print("--- Interpretation ---")
    print("  Protein signaling cascades are inherently nonlinear (sigmoidal kinase activation,")
    print("  feedback loops, cooperative binding). The poly2 likelihood captures pairwise")
    print("  interactions and quadratic effects that the linear model misses. The Bayesian")
    print("  posterior under poly2 should naturally express uncertainty about equivalent")
    print("  nonlinear structures, routing them to UNVERIFIED rather than making overconfident")
    print("  errors (the flexibility curse inversion from M-GAP-2 Theorem 1).")


if __name__ == "__main__":
    main()
