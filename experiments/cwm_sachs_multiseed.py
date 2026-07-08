"""Multi-seed Sachs benchmark harness for the CWM discovery pipeline.

Deterministically evaluates whether a small intervention budget improves
skeleton recovery over an observational/correlation baseline on the Sachs
protein-signaling dataset. Interventions are simulated offline from a linear
SCM oracle fit to the consensus biology DAG and observational data — no live
environment control or online control-path inference is performed.

Run:
    PYTHONPATH=src python experiments/cwm_sachs_multiseed.py
"""
from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.bayesian_dag_posterior import (
    GovernedDiBS,
    _ols_coefficients,
    _parent_adjacency,
)
from aac.cwm_organ import _cov, _inv, _standardize_cols
from aac.product_engine import ProductDiscoveryEngine

OUT = Path(__file__).parent / "cwm_sachs_multiseed.result.json"

PROTEINS = [
    "Raf", "Mek", "Plcg", "PIP2", "PIP3", "Erk", "Akt", "PKA", "PKC", "P38", "Jnk",
]
GROUND_TRUTH = frozenset({
    (PROTEINS.index("PKC"), PROTEINS.index("Raf")),
    (PROTEINS.index("PKC"), PROTEINS.index("Mek")),
    (PROTEINS.index("PKC"), PROTEINS.index("Jnk")),
    (PROTEINS.index("PKC"), PROTEINS.index("P38")),
    (PROTEINS.index("PKC"), PROTEINS.index("PKA")),
    (PROTEINS.index("PKA"), PROTEINS.index("Raf")),
    (PROTEINS.index("PKA"), PROTEINS.index("Mek")),
    (PROTEINS.index("PKA"), PROTEINS.index("Erk")),
    (PROTEINS.index("PKA"), PROTEINS.index("Akt")),
    (PROTEINS.index("PKA"), PROTEINS.index("Jnk")),
    (PROTEINS.index("PKA"), PROTEINS.index("P38")),
    (PROTEINS.index("Raf"), PROTEINS.index("Mek")),
    (PROTEINS.index("Mek"), PROTEINS.index("Erk")),
    (PROTEINS.index("Erk"), PROTEINS.index("Akt")),
    (PROTEINS.index("Plcg"), PROTEINS.index("PIP2")),
    (PROTEINS.index("Plcg"), PROTEINS.index("PIP3")),
    (PROTEINS.index("PIP3"), PROTEINS.index("PIP2")),
})


def load_sachs_obs(path: str | None = None) -> list[list[float]]:
    """Load Sachs observational data from the default experiments/data location."""
    if path is None:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, "experiments", "data", "sachs_obs.txt")
    with open(path) as f:
        rows = [ln.split() for ln in f.read().splitlines()[1:] if ln.strip()]
    return [[float(v) for v in r] for r in rows]


def _skeleton_metrics(predicted: frozenset, truth: frozenset) -> dict:
    pred_undir = {frozenset(e) for e in predicted}
    true_undir = {frozenset(e) for e in truth}
    tp = len(pred_undir & true_undir)
    precision = tp / len(pred_undir) if pred_undir else 0.0
    recall = tp / len(true_undir) if true_undir else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "n_predicted": len(pred_undir),
        "n_true": len(true_undir),
    }


def _topological_order(edges: frozenset, n: int) -> list[int]:
    indeg = {i: 0 for i in range(n)}
    adj = {i: [] for i in range(n)}
    for u, v in edges:
        adj[u].append(v)
        indeg[v] += 1
    queue = [i for i in range(n) if indeg[i] == 0]
    order = []
    while queue:
        u = queue.pop(0)
        order.append(u)
        for v in adj[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
    for i in range(n):
        if i not in order:
            order.append(i)
    return order


def make_linear_scm_oracle(
    obs: list[list[float]],
    edges: frozenset[tuple[int, int]],
    rng: random.Random,
) -> callable:
    """Fit a linear SCM to obs constrained to `edges` and return a do() simulator."""
    n = len(obs[0])
    col_means = [statistics.mean([obs[t][k] for t in range(len(obs))]) for k in range(n)]
    parents = _parent_adjacency(n, edges)

    coefs: dict[int, list[float]] = {}
    noise_sds: dict[int, float] = {}
    for j in range(n):
        pa = parents[j]
        if pa:
            X = [[obs[t][p] for p in pa] for t in range(len(obs))]
            y = [obs[t][j] for t in range(len(obs))]
            try:
                beta = _ols_coefficients(X, y)
            except (ValueError, ZeroDivisionError):
                beta = []
            coefs[j] = beta
            preds = [sum(beta[i] * X[t][i] for i in range(len(pa))) for t in range(len(y))]
            rss = sum((y[t] - preds[t]) ** 2 for t in range(len(y)))
            noise_sds[j] = math.sqrt(max(rss / max(len(y) - len(pa), 1), 1e-9))
        else:
            coefs[j] = []
            noise_sds[j] = statistics.pstdev([obs[t][j] for t in range(len(obs))]) or 0.3

    topo = _topological_order(edges, n)

    def oracle(do_node: int, do_val: float) -> list[float]:
        row = list(col_means)
        row[do_node] = do_val
        for j in topo:
            if j == do_node:
                continue
            pa = parents[j]
            if not pa:
                row[j] = col_means[j] + rng.gauss(0, noise_sds[j])
            else:
                pred = sum(
                    coefs[j][pi] * (do_val if p == do_node else row[p])
                    for pi, p in enumerate(pa)
                )
                row[j] = pred + rng.gauss(0, noise_sds[j])
        return row

    return oracle


def run_baseline(obs: list[list[float]], seed: int = 42) -> dict:
    """Observational/correlation baseline: GGM skeleton + GovernedDiBS orientation.

    Uses the same particle engine as the causal arm but without interventions,
    so measured advantage comes from the intervention budget rather than a
    different inference method.
    """
    engine = ProductDiscoveryEngine(
        skeleton_tau=0.05,
        n_particles=20,
        use_fast_orient=False,
        likelihood_mode="linear",
        seed=seed,
    )
    result = engine.discover(obs, true_edges_for_eval=GROUND_TRUTH)
    return {
        "f1": round(2 * result.recall * result.precision / max(result.recall + result.precision, 1e-9), 4),
        "recall": round(result.recall, 4),
        "precision": round(result.precision, 4),
        "n_edges": result.n_dag_edges,
    }


def run_cwm_with_interventions(
    obs: list[list[float]],
    seed: int,
    budget: int = 6,
) -> dict:
    """CWM pipeline: GovernedDiBS + small budget of offline simulated interventions."""
    rng = random.Random(seed)
    n = len(obs[0])
    oracle = make_linear_scm_oracle(obs, GROUND_TRUTH, rng)

    # Build GGM skeleton as organ proposal to constrain search.
    std = _standardize_cols(obs)
    prec = _inv(_cov(std))
    skeleton = set()
    for i in range(n):
        for j in range(i + 1, n):
            denom = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
            if abs(prec[i][j]) / denom > 0.05:
                skeleton.add(frozenset({i, j}))
    organ_proposals = {1: set()}
    for undir in skeleton:
        parts = list(undir)
        if len(parts) == 2:
            organ_proposals[1].add((parts[0], parts[1]))
            organ_proposals[1].add((parts[1], parts[0]))

    di = GovernedDiBS(
        n_nodes=n,
        n_particles=20,
        lambda_sparse=0.5,
        sigma_noise=0.3,
        seed=seed,
        likelihood_mode="linear",
        organ_proposals=organ_proposals,
        organ_credits={1: 0.8},
        max_in_degree=4,
    )
    di.posterior_temperature = 2.0

    data = [list(row) for row in obs]
    di.update(data)
    di.resample_and_perturb()

    for _ in range(budget):
        # Build candidate values for each node and use existing BOED/EIG to
        # select the most informative intervention (verify-only simulation).
        candidates = {}
        for k in range(n):
            col = [data[t][k] for t in range(len(data))]
            mu = statistics.mean(col)
            sd = statistics.pstdev(col) or 1.0
            candidates[k] = [round(mu - sd, 2), round(mu, 2), round(mu + sd, 2)]
        do_node, do_val, _ = di.select_intervention(data, candidates, n_mc_samples=3)
        if do_node < 0:
            do_node = rng.randrange(n)
            col = [data[t][do_node] for t in range(len(data))]
            do_val = round(statistics.mean(col), 2)
        outcome = oracle(do_node, do_val)
        data.append(outcome)
        di.update(data)
        di.resample_and_perturb()

    map_dag = di.MAP_dag()
    metrics = _skeleton_metrics(map_dag, GROUND_TRUTH)
    return {
        "f1": metrics["f1"],
        "recall": metrics["recall"],
        "precision": metrics["precision"],
        "n_edges": metrics["n_predicted"],
        "interventions_spent": budget,
    }


def run_seed(obs: list[list[float]], seed: int, budget: int = 6) -> dict:
    """Run baseline and causal pipeline for one seed and return comparison."""
    baseline = run_baseline(obs, seed=seed)
    causal = run_cwm_with_interventions(obs, seed, budget=budget)
    return {
        "seed": seed,
        "baseline": baseline,
        "causal": causal,
        "f1_advantage": round(causal["f1"] - baseline["f1"], 4),
        "recall_advantage": round(causal["recall"] - baseline["recall"], 4),
        "precision_advantage": round(causal["precision"] - baseline["precision"], 4),
    }


def run_multiseed_benchmark(
    obs: list[list[float]] | None = None,
    seeds: list[int] | None = None,
    budget: int = 6,
) -> dict:
    """Run baseline vs causal comparison across seeds and aggregate."""
    if obs is None:
        obs = load_sachs_obs()
    seeds = seeds or [100, 101, 102, 103, 104]
    per_seed = [run_seed(obs, s, budget=budget) for s in seeds]
    advantages = [s["f1_advantage"] for s in per_seed]
    mean_adv = statistics.mean(advantages) if advantages else 0.0
    std_adv = statistics.pstdev(advantages) if len(advantages) > 1 else 0.0
    positive = sum(1 for a in advantages if a > 0.0)
    verdict = (
        "CAUSAL_WINS" if mean_adv > 0.02 and positive >= len(seeds) // 2 + 1
        else "TIE" if abs(mean_adv) <= 0.02
        else "BASELINE_WINS"
    )
    return {
        "seeds": seeds,
        "budget": budget,
        "n_obs": len(obs),
        "n_nodes": len(obs[0]),
        "n_true_edges": len(GROUND_TRUTH),
        "per_seed": per_seed,
        "mean_f1_advantage": round(mean_adv, 4),
        "std_f1_advantage": round(std_adv, 4),
        "positive_seeds": f"{positive}/{len(seeds)}",
        "verdict": verdict,
    }


def main():
    obs = load_sachs_obs()
    print("CWM multi-seed Sachs benchmark — verify-only offline simulation")
    print(f"  n_obs={len(obs)}  n_nodes={len(obs[0])}  true_edges={len(GROUND_TRUTH)}")
    print("  budget=6  seeds=[100..104]  baseline=observational GGM+DiBS orientation\n")

    result = run_multiseed_benchmark(obs=obs, seeds=[100, 101, 102, 103, 104], budget=6)

    print("--- Per-seed F1 advantage ---")
    for r in result["per_seed"]:
        print(
            f"  seed={r['seed']}  "
            f"causal F1={r['causal']['f1']:.3f}  "
            f"baseline F1={r['baseline']['f1']:.3f}  "
            f"Δ={r['f1_advantage']:+.3f}"
        )

    print("\n--- Aggregate ---")
    print(f"  mean F1 advantage: {result['mean_f1_advantage']:+.4f} ± {result['std_f1_advantage']:.4f}")
    print(f"  positive seeds:    {result['positive_seeds']}")
    print(f"  verdict:           {result['verdict']}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nResult written to {OUT.resolve()}")


if __name__ == "__main__":
    main()
