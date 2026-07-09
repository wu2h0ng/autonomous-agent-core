"""Cross-Domain Transfer Experiment — pre-trained causal prior vs from-scratch.

Tests whether pre-training on 500 synthetic SCM domains produces a prior that
improves causal discovery on NEW (held-out) domains.

Setup:
1. Train CausalPriorLearner on 500 synthetic SCMs (varying n, density, mechanism)
2. Generate 3 NEW hold-out domains (not seen during training)
3. Compare: GovernedDiBS with TransferOrgan prior vs without
4. Measure: recall, precision, orientation accuracy, convergence speed

Run: PYTHONPATH=src python experiments/transfer_experiment.py
"""
from __future__ import annotations

import json, math, os, random, statistics, sys, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.causal_prior_transfer import CausalPriorLearner, TransferOrgan
from aac.cwm_organ import LinearGGMOrgan, PolynomialOrgan
from aac.bayesian_dag_posterior import GovernedDiBS, generate_linear_scm_data

OUT = Path(__file__).parent / "transfer_experiment.result.json"


def make_holdout_domain(name, n_nodes, n_obs, edges, mechanism, seed):
    rng = random.Random(seed)
    if mechanism == "linear":
        obs, _ = generate_linear_scm_data(n_nodes, frozenset(edges), n_obs, 0.3, rng=rng)
        return obs, frozenset(edges)
    parents = {j: [] for j in range(n_nodes)}
    coefs = {}
    for u, v in edges:
        parents[v].append(u)
        coefs[(u, v)] = rng.uniform(0.4, 1.0) * rng.choice([1.0, -1.0])
    obs = []
    for _ in range(n_obs):
        row = [0.0] * n_nodes
        for j in range(n_nodes):
            val = rng.gauss(0, 0.3)
            for p in parents[j]:
                if mechanism == "tanh":
                    val += coefs[(p, j)] * math.tanh(row[p] * 1.5)
                elif mechanism == "poly":
                    val += coefs[(p, j)] * (row[p] + 0.3 * row[p]**2)
            row[j] = val
        obs.append(row)
    return obs, frozenset(edges)


def run_on_domain(obs, true_edges, n_nodes, mechanism, use_prior, learner):
    t0 = time.time()
    organ_proposals = {}
    organ_credits = {}

    if use_prior and learner is not None:
        transfer = TransferOrgan(learner, min_prob=0.05)
        sk_prior = transfer.propose_skeleton(obs)
        organ_proposals[1] = set()
        for p in sk_prior:
            for undir in p.edges:
                parts = list(undir)
                if len(parts) == 2:
                    organ_proposals[1].add((parts[0], parts[1]))
                    organ_proposals[1].add((parts[1], parts[0]))
        organ_credits[1] = 0.7
    else:
        organ = LinearGGMOrgan(tau=0.05)
        sk = organ.propose_skeleton(obs)
        organ_proposals[1] = set()
        for p in sk:
            for undir in p.edges:
                parts = list(undir)
                if len(parts) == 2:
                    organ_proposals[1].add((parts[0], parts[1]))
                    organ_proposals[1].add((parts[1], parts[0]))
        organ_credits[1] = 0.8

    mode = "poly2" if mechanism in ("tanh", "poly") else "linear"
    di = GovernedDiBS(
        n_nodes=n_nodes, n_particles=40, lambda_sparse=0.5,
        sigma_noise=0.3, seed=42, likelihood_mode=mode,
        organ_proposals=organ_proposals, organ_credits=organ_credits,
    )
    di.posterior_temperature = 2.0
    di.update(obs)
    di.svgd_step(obs, n_gradient_edges=15)
    di.calibrate_temperature()
    di.svgd_step(obs, n_gradient_edges=15)

    map_dag = di.MAP_dag()
    true_set = frozenset(true_edges)
    map_undir = {frozenset(e) for e in map_dag}
    true_undir = {frozenset(e) for e in true_set}
    recall = len(map_undir & true_undir) / max(len(true_undir), 1)
    precision = len(map_undir & true_undir) / max(len(map_undir), 1)

    corr = sum(1 for u, v in true_set if (u, v) in map_dag)
    total = sum(1 for u, v in true_set if (u, v) in map_dag or (v, u) in map_dag)
    orient = corr / max(total, 1)

    return {
        "recall": round(recall, 3),
        "precision": round(precision, 3),
        "orientation_acc": round(orient, 3),
        "conf": round(di.confidence(), 3),
        "ESS": round(di.effective_sample_size(), 1),
        "time_s": round(time.time() - t0, 1),
    }


def main():
    print("Training CausalPriorLearner on 500 synthetic SCMs...")
    t0 = time.time()
    learner = CausalPriorLearner(n_train_domains=500, seed=42)
    print(f"  Done in {time.time()-t0:.0f}s")

    domains = [
        ("linear_chain", 6, 200, {(0,1),(1,2),(2,3),(3,4),(4,5)}, "linear", 99),
        ("tanh_mixed", 7, 200, {(0,1),(1,2),(2,3),(3,4),(4,5),(5,6)}, "tanh", 199),
        ("poly_chain", 8, 200, {(0,1),(1,2),(2,3),(3,4),(4,5),(5,6),(6,7)}, "poly", 299),
    ]

    results = []
    for name, n, n_obs, edges, mech, seed in domains:
        obs, true_edges = make_holdout_domain(name, n, n_obs, edges, mech, seed)
        r_no = run_on_domain(obs, true_edges, n, mech, False, None)
        r_no["domain"] = name; r_no["method"] = "from_scratch"
        r_yes = run_on_domain(obs, true_edges, n, mech, True, learner)
        r_yes["domain"] = name; r_yes["method"] = "transfer_prior"
        results.extend([r_no, r_yes])
        print(f"\n{name}: from_scratch={r_no['recall']:.3f} transfer={r_yes['recall']:.3f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")

    from_scratch = [r for r in results if r["method"] == "from_scratch"]
    transfer = [r for r in results if r["method"] == "transfer_prior"]
    avg_recall_no = statistics.mean([r["recall"] for r in from_scratch])
    avg_recall_yes = statistics.mean([r["recall"] for r in transfer])
    avg_orient_no = statistics.mean([r["orientation_acc"] for r in from_scratch])
    avg_orient_yes = statistics.mean([r["orientation_acc"] for r in transfer])
    print(f"\n=== Summary ===")
    print(f"  from_scratch:  avg_recall={avg_recall_no:.3f}  avg_orient={avg_orient_no:.3f}")
    print(f"  transfer:      avg_recall={avg_recall_yes:.3f}  avg_orient={avg_orient_yes:.3f}")
    print(f"  Δ recall: {avg_recall_yes - avg_recall_no:+.3f}")


if __name__ == "__main__":
    main()
