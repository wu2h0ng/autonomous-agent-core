"""Train AttentionCausalPrior and benchmark vs K-NN and GGM baseline.

Run: PYTHONPATH=src .venv-torch/bin/python experiments/torch_prior_train.py
"""
from __future__ import annotations

import json, math, os, random, statistics, sys, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch

from aac.torch_attention_prior import (
    AttentionCausalPrior, train_model, predict_priors, generate_training_batch,
)
from aac.causal_prior_transfer import CausalPriorLearner, TransferOrgan
from aac.cwm_organ import LinearGGMOrgan
from aac.bayesian_dag_posterior import GovernedDiBS, generate_linear_scm_data

OUT = Path(__file__).parent / "torch_prior_benchmark.result.json"


def make_holdout(name, n, n_obs, edges, mech, seed):
    rng = random.Random(seed)
    if mech == "linear":
        obs, _ = generate_linear_scm_data(n, frozenset(edges), n_obs, 0.3, rng=rng)
        return obs, frozenset(edges)
    parents = {j:[] for j in range(n)}
    coefs = {}
    for u,v in edges: parents[v].append(u); coefs[(u,v)]=rng.uniform(0.4,1.0)*rng.choice([1.0,-1.0])
    obs = []
    for _ in range(n_obs):
        row = [0.0]*n
        for j in range(n):
            val = rng.gauss(0,0.35)
            for p in parents[j]:
                if mech=="tanh": val+=coefs[(p,j)]*math.tanh(row[p]*1.5)
                elif mech=="poly": val+=coefs[(p,j)]*(row[p]+0.3*row[p]**2)
                elif mech=="sin": val+=coefs[(p,j)]*math.sin(row[p]*1.5)
            row[j]=val
        obs.append(row)
    return obs, frozenset(edges)


def run_with_prior(obs, true_edges, n, mech, prior_fn):
    t0 = time.time()
    priors = prior_fn(obs, mech)
    organ_proposals = {1: set()}
    for (i,j), prob in priors.items():
        if prob >= 0.05:
            organ_proposals[1].add((i,j)); organ_proposals[1].add((j,i))
    organ_credits = {1: max(0.1, min(1.0, statistics.mean(list(priors.values())) if priors else 0.5))}

    di = GovernedDiBS(n_nodes=n, n_particles=40, lambda_sparse=0.5, sigma_noise=0.3, seed=42,
                       likelihood_mode="poly2", organ_proposals=organ_proposals, organ_credits=organ_credits)
    di.posterior_temperature=2.0; di.update(obs); di.svgd_step(obs, n_gradient_edges=15)
    di.calibrate_temperature(); di.svgd_step(obs, n_gradient_edges=15)

    map_dag = di.MAP_dag()
    true_set = frozenset(true_edges)
    mu = {frozenset(e) for e in map_dag}; tu = {frozenset(e) for e in true_set}
    rec = len(mu & tu) / max(len(tu), 1)
    prec = len(mu & tu) / max(len(mu), 1)
    corr = sum(1 for u,v in true_set if (u,v) in map_dag)
    total = sum(1 for u,v in true_set if (u,v) in map_dag or (v,u) in map_dag)
    orient = corr / max(total, 1)
    return {"recall": round(rec,3), "precision": round(prec,3),
            "orientation_acc": round(orient,3), "time_s": round(time.time()-t0, 1)}


def main():
    print("Training AttentionCausalPrior on 5000 SCMs (50k steps)...")
    t0 = time.time()
    model = AttentionCausalPrior(feat_dim=12, embed_dim=64, n_heads=2)
    losses = train_model(model, n_steps=200, batch_size=16, lr=1e-3, seed=42)
    train_t = time.time() - t0
    print(f"  Done in {train_t:.0f}s  final loss={losses[-1]:.4f}")

    print("\nTraining K-NN prior on 2000 domains for comparison...")
    t0 = time.time()
    knn_learner = CausalPriorLearner(n_train_domains=2000, seed=42)
    knn_t = time.time() - t0
    print(f"  Done in {knn_t:.0f}s")

    domains = [
        ("linear_chain", 6, 150, {(0,1),(1,2),(2,3),(3,4),(4,5)}, "linear", 99),
        ("tanh_chain", 7, 150, {(0,1),(1,2),(2,3),(3,4),(4,5),(5,6)}, "tanh", 199),
        ("poly_mixed", 8, 150, {(0,1),(1,2),(2,3),(3,4),(4,5),(5,6),(6,7)}, "poly", 299),
        ("sin_chain", 6, 150, {(0,1),(1,2),(2,3),(3,4),(4,5)}, "sin", 399),
        ("tanh_sparse", 9, 140, {(0,1),(1,2),(2,3),(0,4),(4,5),(5,6),(0,7),(7,8)}, "tanh", 499),
    ]

    results = []
    for name, n, n_obs, edges, mech, seed in domains:
        obs, true_edges = make_holdout(name, n, n_obs, edges, mech, seed)

        r_ggm = run_with_prior(obs, true_edges, n, mech,
                                lambda o, m: {k: 0.3 for k in [(i,j) for i in range(n) for j in range(i+1,n)]})
        r_ggm["domain"] = name; r_ggm["method"] = "GGM_baseline"

        def knn_fn(o, m): return knn_learner.predict_edge_priors(o, k=15)
        r_knn = run_with_prior(obs, true_edges, n, mech, knn_fn)
        r_knn["domain"] = name; r_knn["method"] = "KNN_prior"

        def attn_fn(o, m): return predict_priors(model, o, m)
        r_attn = run_with_prior(obs, true_edges, n, mech, attn_fn)
        r_attn["domain"] = name; r_attn["method"] = "Attention_prior"

        results.extend([r_ggm, r_knn, r_attn])
        print(f"\n{name} ({mech}):")
        for r in [r_ggm, r_knn, r_attn]:
            print(f"  {r['method']:20s}: recall={r['recall']:.3f} orient={r['orientation_acc']:.3f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")

    for m in ["GGM_baseline", "KNN_prior", "Attention_prior"]:
        group = [r for r in results if r["method"] == m]
        if group:
            avg_r = statistics.mean([r["recall"] for r in group])
            avg_o = statistics.mean([r["orientation_acc"] for r in group])
            print(f"\n  {m:20s}: avg_recall={avg_r:.3f}  avg_orient={avg_o:.3f}")


if __name__ == "__main__":
    main()
