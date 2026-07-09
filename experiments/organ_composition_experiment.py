"""Organ Composition Experiment — RR-0046 §27: language orientation on nonlinear domain.

Runs GovernedDiscoveryLoop with BOTH data skeleton organs (LinearGGM + Polynomial)
AND a language orientation organ (ChainStubBackend). Tests whether composition
achieves what neither can alone on the nonlinear tanh chain domain.

The RR-0046 §27 result: data skeleton recall=1.0 but orientation=0/6,
language organ orientation=6/6, COMPOSITION recovers full directed structure.
This experiment replicates that pattern with the current engine.

Run: PYTHONPATH=src python experiments/organ_composition_experiment.py
"""
from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.cwm_organ import LinearGGMOrgan, PolynomialOrgan, StructureProposal
from aac.language_orientation_organ import LanguageOrientationOrgan, ChainStubBackend
from aac.bayesian_dag_posterior import GovernedDiBS, generate_linear_scm_data

OUT = Path(__file__).parent / "organ_composition_experiment.result.json"


def generate_tanh_chain_data(
    n_nodes: int, n_obs: int, noise_std: float = 0.3, seed: int = 42,
) -> tuple[list[list[float]], frozenset]:
    """Generate a nonlinear tanh chain: 0→1→2→...→(n-1)."""
    edges = frozenset({(i, i + 1) for i in range(n_nodes - 1)})
    rng = random.Random(seed)
    parents = {j: [j - 1] for j in range(1, n_nodes)}
    parents[0] = []
    coefs = {(i, i + 1): rng.uniform(0.4, 1.0) * rng.choice([1.0, -1.0]) for i in range(n_nodes - 1)}
    obs = []
    for _ in range(n_obs):
        row = [0.0] * n_nodes
        for j in range(n_nodes):
            val = rng.gauss(0, noise_std)
            for p in parents[j]:
                val += coefs[(p, j)] * math.tanh(row[p] * 1.5)
            row[j] = val
        obs.append(row)
    return obs, edges


def run_organ_composition(
    obs: list[list[float]],
    true_edges: frozenset,
    n_nodes: int,
    use_language: bool = False,
) -> dict:
    t0 = time.time()

    organ = LinearGGMOrgan(tau=0.05)
    sk = organ.propose_skeleton(obs)
    organ_proposals = {1: set()}
    for p in sk:
        for undir in p.edges:
            parts = list(undir)
            if len(parts) == 2:
                organ_proposals[1].add((parts[0], parts[1]))
                organ_proposals[1].add((parts[1], parts[0]))
    organ_credits = {1: 0.8}

    if use_language:
        backend = ChainStubBackend(confidence=0.85)
        labels = [f"node_{i}" for i in range(n_nodes)]
        lang_organ = LanguageOrientationOrgan(backend, labels)
        sk_undirected = {frozenset(p.edges) if isinstance(p.edges, frozenset) else p.edges for p in sk}
        skeleton = frozenset()
        for s in sk_undirected:
            skeleton = skeleton | s
        orientation_props = lang_organ.propose_orientation(skeleton)
        organ_proposals[2] = set()
        for prop in orientation_props:
            for pair in prop.edges:
                if isinstance(pair, tuple) and len(pair) == 2:
                    organ_proposals[2].add(pair)
        organ_credits[2] = 0.85

    di = GovernedDiBS(
        n_nodes=n_nodes, n_particles=50, lambda_sparse=0.5,
        sigma_noise=0.3, seed=42, likelihood_mode="poly2",
        organ_proposals=organ_proposals, organ_credits=organ_credits,
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

    for _ in range(2):
        di.svgd_step(obs, n_gradient_edges=20)
        di.calibrate_temperature()
    di.hippocampal_replay(obs, replay_rounds=2)

    map_dag = di.MAP_dag()
    true_set = frozenset(true_edges)
    map_undir = {frozenset(e) for e in map_dag}
    true_undir = {frozenset(e) for e in true_set}

    recall = len(map_undir & true_undir) / max(len(true_undir), 1)
    precision = len(map_undir & true_undir) / max(len(map_undir), 1)

    oriented_correct = 0
    oriented_total = 0
    for u, v in true_set:
        if (u, v) in map_dag:
            oriented_correct += 1
        elif (v, u) in map_dag:
            pass
        if (u, v) in map_dag or (v, u) in map_dag:
            oriented_total += 1
    orientation_accuracy = oriented_correct / max(oriented_total, 1)

    ens = di.ensemble_confidence(obs, n_ensembles=2)
    mec_conf = di.MEC_confidence()

    def compute_auc(marginals, true_edges_set, n):
        labels = []
        scores = []
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                prob = marginals.get((i, j), 0.0)
                prob_rev = marginals.get((j, i), 0.0)
                scores.append(max(prob, prob_rev))
                labels.append(1 if (i, j) in true_edges_set or (j, i) in true_edges_set else 0)
        if not labels or sum(labels) == 0 or sum(labels) == len(labels):
            return 0.5
        paired = list(zip(scores, labels))
        paired.sort(key=lambda x: x[0], reverse=True)
        pos_ranks = [i + 1 for i, (_, lab) in enumerate(paired) if lab == 1]
        n_pos = sum(labels)
        n_neg = len(labels) - n_pos
        if n_pos == 0 or n_neg == 0:
            return 0.5
        return (sum(pos_ranks) - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)

    auc = compute_auc(ens["marginals"], true_set, n_nodes)
    els = time.time() - t0

    return {
        "use_language_organ": use_language,
        "MAP_skeleton_recall": round(recall, 3),
        "MAP_skeleton_precision": round(precision, 3),
        "MAP_orientation_accuracy": round(orientation_accuracy, 3),
        "n_organs": len(organ_proposals),
        "ensemble_confidence": round(ens["confidence"], 3),
        "MEC_confidence": round(mec_conf, 3),
        "ESS": round(di.effective_sample_size(), 1),
        "edge_AUC": round(auc, 3),
        "time_s": round(els, 1),
    }


def main():
    n_nodes = 8
    obs, true_edges = generate_tanh_chain_data(n_nodes, 600, noise_std=0.3, seed=42)
    print(f"Nonlinear tanh chain: n={n_nodes}, |E|={len(true_edges)}, n_obs={len(obs)}")

    print("\n--- Data only (no language organ) ---")
    r_no_lang = run_organ_composition(obs, true_edges, n_nodes, use_language=False)
    print(json.dumps(r_no_lang, indent=2))

    print("\n--- Composition: data + language orientation organ ---")
    r_with_lang = run_organ_composition(obs, true_edges, n_nodes, use_language=True)
    print(json.dumps(r_with_lang, indent=2))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps([r_no_lang, r_with_lang], indent=2, sort_keys=True), encoding="utf-8")

    print(f"\n--- Summary ---")
    d_recall = r_with_lang["MAP_skeleton_recall"] - r_no_lang["MAP_skeleton_recall"]
    d_orient = r_with_lang["MAP_orientation_accuracy"] - r_no_lang["MAP_orientation_accuracy"]
    print(f"  Skeleton recall Δ: {d_recall:+.3f}")
    print(f"  Orientation accuracy Δ: {d_orient:+.3f}")
    print(f"  Composition lift: skeleton={d_recall >= 0}, orientation={d_orient >= 0}")


if __name__ == "__main__":
    main()
