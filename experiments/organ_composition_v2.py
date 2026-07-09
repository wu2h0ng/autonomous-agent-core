"""Organ Composition Experiment v2 — nonlinear collider where data can't orient.

Tests the RR-0046 §27 thesis on a strict test case: a nonlinear tanh domain
with collider structures (A→C←B). Under tanh saturation, multiple DAG directions
produce equivalent predictions — data alone cannot orient all edges.

The language organ (stub) provides prior knowledge of edge directions from variable
semantics. If composition (data+language) achieves higher orientation accuracy than
data alone, the composition thesis is confirmed on the current engine.

Domain: 6 nodes, nonlinear tanh, mixed chain+collider structure.
Edges: 0→1→2←3, plus 2→4→5  (chain)  →  total 5 edges
V-structure at node 2: edges 1→2 and 3→2 (0 and 1 are independent given 2)

Run: PYTHONPATH=src python experiments/organ_composition_v2.py
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

from aac.cwm_organ import LinearGGMOrgan, PolynomialOrgan
from aac.language_orientation_organ import LanguageOrientationOrgan
from aac.prior_organ_llm import DeterministicStubBackend
from aac.bayesian_dag_posterior import GovernedDiBS

OUT = Path(__file__).parent / "organ_composition_v2.result.json"


def make_collider_domain(seed: int = 42, n_obs: int = 800, noise_std: float = 0.3):
    """Nonlinear tanh domain with collider + chain edges.

    Structure: 0→1, 1→2, 3→2, 2→4, 4→5 (5 edges, 6 nodes)
    Nodes 1 and 3 both affect node 2 (collider at 2).
    Under tanh saturation, data alone cannot distinguish 1→2 vs 2→1
    when both produce saturated outputs at node 2.
    """
    n_nodes = 6
    edges = frozenset({(0, 1), (1, 2), (3, 2), (2, 4), (4, 5)})
    rng = random.Random(seed)
    parents = {0: [], 1: [0], 2: [1, 3], 3: [], 4: [2], 5: [4]}
    coefs = {}
    for u, v in edges:
        coefs[(u, v)] = rng.uniform(0.6, 1.2) * rng.choice([1.0, -1.0])

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


class DirectionStubBackend:
    """Stub LLM that knows the exact edge directions for the collider domain.

    Simulates an LLM with domain expertise: for each undirected edge,
    it proposes the correct causal direction with configurable confidence.
    This is the RR-0046 §27 setup — the language organ contributes knowledge
    that data alone cannot discover (orientation under saturation).
    """

    def __init__(self, true_edges: frozenset, confidence: float = 0.8):
        self._true = true_edges
        self.confidence = confidence

    def propose(self, prompt: str):
        orientations = []
        for line in prompt.split("\n"):
            line = line.strip()
            if line.startswith("(") and ") -- (" in line:
                try:
                    i = int(line.split(":")[0].replace("(", "").strip())
                    parts_second = line.split("--")[1].split(":")[0].replace("(", "").strip()
                    j = int(parts_second)
                    for u, v in self._true:
                        if (u == i and v == j):
                            direction = f"{i}→{j}"
                            break
                        elif (u == j and v == i):
                            direction = f"{j}→{i}"
                            break
                    else:
                        continue
                    orientations.append({
                        "i": min(i, j), "j": max(i, j),
                        "direction": direction, "score": self.confidence,
                    })
                except (ValueError, IndexError):
                    continue
        return {"orientations": orientations}


def compute_metrics(di: GovernedDiBS, true_edges: frozenset, n_nodes: int, obs) -> dict:
    map_dag = di.MAP_dag()
    true_set = frozenset(true_edges)
    map_undir = {frozenset(e) for e in map_dag}
    true_undir = {frozenset(e) for e in true_set}

    sk_recall = len(map_undir & true_undir) / max(len(true_undir), 1)
    sk_precision = len(map_undir & true_undir) / max(len(map_undir), 1)

    oriented_correct = 0
    oriented_total = 0
    for u, v in true_set:
        if (u, v) in map_dag:
            oriented_correct += 1
        if (u, v) in map_dag or (v, u) in map_dag:
            oriented_total += 1
    orient_acc = oriented_correct / max(oriented_total, 1)

    def compute_auc(marginals, true_set_local, n):
        labels = []; scores = []
        for i in range(n):
            for j in range(n):
                if i == j: continue
                prob = marginals.get((i, j), 0.0)
                prob_rev = marginals.get((j, i), 0.0)
                scores.append(max(prob, prob_rev))
                labels.append(1 if (i, j) in true_set_local or (j, i) in true_set_local else 0)
        if not labels or sum(labels) == 0 or sum(labels) == len(labels): return 0.5
        paired = list(zip(scores, labels))
        paired.sort(key=lambda x: x[0], reverse=True)
        p_sum = sum(labels)
        n_neg = len(labels) - p_sum
        pos_ranks = [i+1 for i, (_, l) in enumerate(paired) if l == 1]
        return (sum(pos_ranks) - p_sum*(p_sum+1)/2) / (p_sum * n_neg)

    ens = di.ensemble_confidence(obs, n_ensembles=2)
    return {
        "skeleton_recall": round(sk_recall, 3),
        "skeleton_precision": round(sk_precision, 3),
        "orientation_accuracy": round(orient_acc, 3),
        "confidence": round(ens["confidence"], 3),
        "MEC_confidence": round(di.MEC_confidence(), 3),
        "edge_AUC": round(compute_auc(ens["marginals"], true_set, n_nodes), 3),
        "n_MECs": len(di.MEC_clusters()),
        "ESS": round(di.effective_sample_size(), 1),
    }


def run(use_language: bool, obs, true_edges, n_nodes) -> dict:
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
        backend = DirectionStubBackend(true_edges, confidence=0.85)
        lang = LanguageOrientationOrgan(backend, [f"v{i}" for i in range(n_nodes)])
        skeleton = frozenset()
        for s in [frozenset(p.edges) if isinstance(p.edges, frozenset) else p.edges for p in sk]:
            skeleton = skeleton | s
        orients = lang.propose_orientation(skeleton)
        organ_proposals[2] = set()
        for p in orients:
            for pair in p.edges:
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
        mu = statistics.mean(col); sd = statistics.pstdev(col) or 1.0
        for a in [-1.0, -0.5, 0.0, 0.5, 1.0]:
            curve[k].append((round(mu + a*sd, 1), mu))
    di.update_with_intervention_curve(obs, curve)
    di.calibrate_temperature()
    for _ in range(2):
        di.svgd_step(obs, n_gradient_edges=20)
        di.calibrate_temperature()
    di.hippocampal_replay(obs, replay_rounds=2)

    result = compute_metrics(di, true_edges, n_nodes, obs)
    result["use_language"] = use_language
    result["time_s"] = round(time.time() - t0, 1)
    return result


def main():
    obs, true_edges = make_collider_domain(seed=42, n_obs=800)
    n = 6
    print(f"Nonlinear tanh collider: n={n}, |E|={len(true_edges)}")
    print(f"Edges: {sorted(true_edges)}")

    r_no = run(use_language=False, obs=obs, true_edges=true_edges, n_nodes=n)
    print(f"\n--- Data only ---")
    print(json.dumps(r_no, indent=2))

    r_yes = run(use_language=True, obs=obs, true_edges=true_edges, n_nodes=n)
    print(f"\n--- Data + Language ---")
    print(json.dumps(r_yes, indent=2))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps([r_no, r_yes], indent=2), encoding="utf-8")

    print(f"\n--- Lift ---")
    d_recall = r_yes["skeleton_recall"] - r_no["skeleton_recall"]
    d_orient = r_yes["orientation_accuracy"] - r_no["orientation_accuracy"]
    d_auc = r_yes["edge_AUC"] - r_no["edge_AUC"]
    print(f"  Δ skeleton_recall:       {d_recall:+.3f}")
    print(f"  Δ orientation_accuracy:  {d_orient:+.3f}")
    print(f"  Δ edge_AUC:              {d_auc:+.3f}")


if __name__ == "__main__":
    main()
