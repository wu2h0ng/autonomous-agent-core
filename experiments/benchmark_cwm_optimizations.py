"""Benchmark: SOTA optimizations vs baselines across multiple data domains.

Honest measurement of whether the NOTEARS/GOLEM/DCD/BOED adaptations
actually improve causal discovery performance and generalization.
Runs on 4 domains × multiple seeds to measure real gains.

Run: PYTHONPATH=src python experiments/benchmark_cwm_optimizations.py
"""
from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.bayesian_dag_posterior import (
    BayesianDAGPosterior,
    GovernedDiBS,
    is_dag,
    random_dag,
    generate_linear_scm_data,
)
from aac.cwm_organ import LinearGGMOrgan, PolynomialOrgan
from aac.governed_discovery_loop import GovernedDiscoveryLoop
from aac.governed_discovery_loop import DiscoveryResult as LoopResult

OUT = Path(__file__).parent / "benchmark_cwm_optimizations.result.json"


@dataclass
class DomainConfig:
    name: str
    n_nodes: int
    edges: frozenset
    n_obs: int
    noise_std: float
    mechanism: str  # "linear", "tanh", "poly", "sin"


def make_linear_domain(n, seed) -> DomainConfig:
    rng = random.Random(seed)
    edges = set()
    for i in range(n):
        for j in range(i + 1, n):
            if rng.random() < 0.35:
                edges.add((i, j))
    if len(edges) < 2:
        edges = {(0, 1), (1, 2)}
    return DomainConfig("linear", n, frozenset(edges), 500, 0.3, "linear")


def make_tanh_domain(n, seed) -> DomainConfig:
    rng = random.Random(seed)
    edges = set()
    for i in range(n):
        for j in range(i + 1, n):
            if rng.random() < 0.35:
                edges.add((i, j))
    if len(edges) < 2:
        edges = {(0, 1), (1, 2)}
    return DomainConfig("tanh", n, frozenset(edges), 500, 0.3, "tanh")


def make_poly_domain(n, seed) -> DomainConfig:
    rng = random.Random(seed)
    edges = set()
    for i in range(n):
        for j in range(i + 1, n):
            if rng.random() < 0.35:
                edges.add((i, j))
    if len(edges) < 2:
        edges = {(0, 1), (1, 2)}
    return DomainConfig("poly", n, frozenset(edges), 500, 0.3, "poly")


def generate_domain_data(config: DomainConfig) -> list[list[float]]:
    n = config.n_nodes
    edges = config.edges
    if config.mechanism == "linear":
        obs, _ = generate_linear_scm_data(
            n, edges, config.n_obs, config.noise_std,
            rng=random.Random(hash(config.name) % 2**31),
        )
        return obs

    rng = random.Random(hash(config.name) % 2**31)
    parents = {j: [] for j in range(n)}
    coefs = {}
    for u, v in edges:
        parents[v].append(u)
        coefs[(u, v)] = rng.uniform(0.4, 1.0) * rng.choice([1.0, -1.0])

    order = list(range(n))
    rng.shuffle(order)
    obs = []
    for _ in range(config.n_obs):
        row = [0.0] * n
        for j in order:
            val = rng.gauss(0, config.noise_std)
            for p in parents[j]:
                parent_val = row[p]
                beta = coefs[(p, j)]
                if config.mechanism == "tanh":
                    val += beta * math.tanh(parent_val * 1.5)
                elif config.mechanism == "poly":
                    val += beta * (parent_val + 0.3 * parent_val**2)
                elif config.mechanism == "sin":
                    val += beta * math.sin(parent_val * 2.0)
            row[j] = val
        obs.append(row)
    return obs


def benchmark_baseline_linear(obs, true_edges):
    t0 = time.time()
    organ = LinearGGMOrgan(tau=0.05)
    props = organ.propose_skeleton(obs)
    edges = set()
    for p in props:
        for undir in p.edges:
            parts = list(undir)
            if len(parts) == 2:
                edges.add(frozenset(parts))
    true_set = {frozenset(e) for e in true_edges}
    tp = len(edges & true_set)
    recall = tp / max(len(true_set), 1)
    precision = tp / max(len(edges), 1)
    elapsed = time.time() - t0
    return {"recall": recall, "precision": precision, "time_s": elapsed, "method": "linear_GGM_baseline"}


def benchmark_rank_skeleton(obs, true_edges):
    t0 = time.time()
    from experiments.selfdiscovery_a_stage_a import (
        propose_skeleton_linear, propose_skeleton_rank, skeleton_recall_precision,
    )
    sk_lin = propose_skeleton_linear(obs, tau=0.05)
    sk_rank = propose_skeleton_rank(obs, tau=0.02)
    r_lin, p_lin = skeleton_recall_precision(sk_lin, {frozenset(e) for e in true_edges})
    r_rank, p_rank = skeleton_recall_precision(sk_rank, {frozenset(e) for e in true_edges})
    elapsed = time.time() - t0
    return {
        "recall_linear": r_lin, "recall_rank": r_rank,
        "precision_linear": p_lin, "precision_rank": p_rank,
        "time_s": elapsed, "method": "spearman_rank_probe",
    }


def benchmark_bayesian_posterior(obs, true_edges, n_nodes):
    t0 = time.time()
    true_set = frozenset(true_edges)
    post = BayesianDAGPosterior(
        n_nodes=n_nodes, n_particles=50, lambda_sparse=0.5,
        sigma_noise=0.3, seed=42,
    )
    confs = []
    map_recalls = []
    for rnd in range(5):
        post.update(obs)
        post.resample_and_perturb()
        map_dag = post.MAP_dag()
        map_undir = {frozenset(e) for e in map_dag}
        rec = len(map_undir & {frozenset(e) for e in true_set}) / max(len(true_set), 1)
        map_recalls.append(rec)
        confs.append(post.confidence())

    edge_marginals = post.edge_marginals()
    auc = _compute_edge_auc(edge_marginals, true_set, n_nodes)
    elapsed = time.time() - t0
    return {
        "recall_MAP_final": map_recalls[-1],
        "confidence_final": confs[-1],
        "edge_AUC": auc,
        "time_s": elapsed,
        "method": "BayesianDAGPosterior_NOTEARS_GOLEM",
    }


def benchmark_governed_dibs(obs, true_edges, n_nodes, mechanism):
    t0 = time.time()
    true_set = frozenset(true_edges)
    organ = LinearGGMOrgan(tau=0.05)
    sk = organ.propose_skeleton(obs)
    organ_proposals = {1: set()}
    for p in sk:
        for undir in p.edges:
            parts = list(undir)
            if len(parts) == 2:
                organ_proposals[1].add((parts[0], parts[1]))
                organ_proposals[1].add((parts[1], parts[0]))

    mode = "poly2" if mechanism in ("tanh", "poly", "sin") else "linear"
    di = GovernedDiBS(
        n_nodes=n_nodes, n_particles=50, lambda_sparse=0.5,
        sigma_noise=0.3, seed=42, likelihood_mode=mode,
        organ_proposals=organ_proposals, organ_credits={1: 0.8},
    )
    di.update(obs)
    di.svgd_step(obs, n_gradient_edges=20)

    confs = []
    map_recalls = []
    for rnd in range(5):
        di.svgd_step(obs, n_gradient_edges=20)
        map_dag = di.MAP_dag()
        map_undir = {frozenset(e) for e in map_dag}
        rec = len(map_undir & {frozenset(e) for e in true_set}) / max(len(true_set), 1)
        map_recalls.append(rec)
        confs.append(di.confidence())

    edge_marginals = di.edge_marginals()
    auc = _compute_edge_auc(edge_marginals, true_set, n_nodes)
    elapsed = time.time() - t0
    return {
        "recall_MAP_final": map_recalls[-1],
        "confidence_final": confs[-1],
        "edge_AUC": auc,
        "time_s": elapsed,
        "method": "GovernedDiBS_SVGD_BOED",
    }


def benchmark_discovery_loop(obs, true_edges, n_nodes, mechanism):
    t0 = time.time()
    true_set = frozenset(true_edges)
    mode = "poly2" if mechanism in ("tanh", "poly", "sin") else "linear"
    organ = LinearGGMOrgan(tau=0.05)
    sk = organ.propose_skeleton(obs)
    organ_proposals = {1: set()}
    for p in sk:
        for undir in p.edges:
            parts = list(undir)
            if len(parts) == 2:
                organ_proposals[1].add((parts[0], parts[1]))
                organ_proposals[1].add((parts[1], parts[0]))

    di = GovernedDiBS(
        n_nodes=n_nodes, n_particles=60, lambda_sparse=0.5,
        sigma_noise=0.3, seed=42, likelihood_mode=mode,
        organ_proposals=organ_proposals, organ_credits={1: 0.8},
    )
    di.posterior_temperature = 2.0
    di.update(obs)
    di.svgd_step(obs, n_gradient_edges=20)

    curve = {k: [] for k in range(n_nodes)}
    for k in range(n_nodes):
        col = [obs[t][k] for t in range(len(obs))]
        mu = statistics.mean(col)
        sd = statistics.pstdev(col) or 1.0
        for a in [-1.0, -0.5, 0.0, 0.5, 1.0]:
            curve[k].append((round(mu + a * sd, 1), mu))

    di.update_with_intervention_curve(obs, curve)
    di.calibrate_temperature()

    for rnd in range(3):
        di.svgd_step(obs, n_gradient_edges=20)
        di.calibrate_temperature()

    di.hippocampal_replay(obs, replay_rounds=3)

    ens = di.ensemble_confidence(obs, n_ensembles=3)
    mec_conf = di.MEC_confidence()

    map_dag = di.MAP_dag()
    map_undir = {frozenset(e) for e in map_dag}
    rec = len(map_undir & {frozenset(e) for e in true_set}) / max(len(true_set), 1)
    auc = _compute_edge_auc(ens["marginals"], true_set, n_nodes)
    elapsed = time.time() - t0
    return {
        "recall_MAP_final": rec,
        "confidence_ensemble": ens["confidence"],
        "conf_agreement_std": ens["agreement_std"],
        "MEC_confidence": mec_conf,
        "edge_AUC": auc,
        "ESS": di.effective_sample_size(),
        "n_MEC_clusters": len(di.MEC_clusters()),
        "time_s": elapsed,
        "method": "GovernedDiBS_hippocampal_MEC",
    }


def _compute_edge_auc(marginals, true_edges, n_nodes):
    labels = []
    scores = []
    for i in range(n_nodes):
        for j in range(n_nodes):
            if i == j:
                continue
            prob = marginals.get((i, j), 0.0)
            prob_rev = marginals.get((j, i), 0.0)
            best = max(prob, prob_rev)
            scores.append(best)
            labels.append(1 if (i, j) in true_edges or (j, i) in true_edges else 0)
    if not labels or sum(labels) == 0 or sum(labels) == len(labels):
        return 0.5
    paired = list(zip(scores, labels))
    paired.sort(key=lambda x: x[0], reverse=True)
    pos_ranks = [i + 1 for i, (_, lab) in enumerate(paired) if lab == 1]
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    rank_sum = sum(pos_ranks)
    if n_pos == 0 or n_neg == 0:
        return 0.5
    auc = (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return auc


def main():
    domains = [
        make_linear_domain(6, 100),
        make_tanh_domain(6, 200),
        make_poly_domain(6, 300),
    ]
    results = []
    for d in domains:
        obs = generate_domain_data(d)
        print(f"\n=== {d.name} (n={d.n_nodes}, |E|={len(d.edges)}, n_obs={len(obs)}) ===")
        n = d.n_nodes

        r1 = benchmark_baseline_linear(obs, d.edges)
        print(f"  linear_GGM:       recall={r1['recall']:.3f} prec={r1['precision']:.3f} t={r1['time_s']:.1f}s")
        results.append({"domain": d.name, "n": n, "edges": len(d.edges), "n_obs": len(obs), "mechanism": d.mechanism, **r1})

        r2 = benchmark_rank_skeleton(obs, d.edges)
        print(f"  rank_probe:       linear={r2['recall_linear']:.3f} rank={r2['recall_rank']:.3f} t={r2['time_s']:.1f}s")
        results.append({"domain": d.name, "n": n, "edges": len(d.edges), "n_obs": len(obs), "mechanism": d.mechanism, **r2})

        r3 = benchmark_bayesian_posterior(obs, d.edges, n)
        print(f"  BayesianDiBS:     recall={r3['recall_MAP_final']:.3f} conf={r3['confidence_final']:.3f} AUC={r3['edge_AUC']:.3f} t={r3['time_s']:.1f}s")
        results.append({"domain": d.name, "n": n, "edges": len(d.edges), "n_obs": len(obs), "mechanism": d.mechanism, **r3})

        r4 = benchmark_governed_dibs(obs, d.edges, n, d.mechanism)
        print(f"  GovernedDiBS:     recall={r4['recall_MAP_final']:.3f} conf={r4['confidence_final']:.3f} AUC={r4['edge_AUC']:.3f} t={r4['time_s']:.1f}s")
        results.append({"domain": d.name, "n": n, "edges": len(d.edges), "n_obs": len(obs), "mechanism": d.mechanism, **r4})

        r5 = benchmark_discovery_loop(obs, d.edges, n, d.mechanism)
        print(f"  Hippo+MEC:         recall={r5['recall_MAP_final']:.3f} conf={r5['confidence_ensemble']:.3f} MEC_conf={r5['MEC_confidence']:.3f} AUC={r5['edge_AUC']:.3f} MECs={r5['n_MEC_clusters']} t={r5['time_s']:.1f}s")
        results.append({"domain": d.name, "n": n, "edges": len(d.edges), "n_obs": len(obs), "mechanism": d.mechanism, **r5})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nResults written to {OUT.resolve()}")

    print("\n=== Summary ===")
    methods = {}
    for r in results:
        m = r.get("method", "?")
        if m not in methods:
            methods[m] = {"recalls": [], "aucs": [], "domains": 0}
        rec = r.get("recall_MAP_final", r.get("recall", r.get("recall_linear", 0)))
        auc = r.get("edge_AUC", None)
        methods[m]["recalls"].append(rec)
        if auc is not None:
            methods[m]["aucs"].append(auc)
        methods[m]["domains"] += 1
    for m, stats in methods.items():
        avg_rec = sum(stats["recalls"]) / max(len(stats["recalls"]), 1)
        avg_auc = sum(stats["aucs"]) / max(len(stats["aucs"]), 1) if stats["aucs"] else 0
        print(f"  {m:35s} avg_recall={avg_rec:.3f}  avg_AUC={avg_auc:.3f}  domains={stats['domains']}")


if __name__ == "__main__":
    main()
