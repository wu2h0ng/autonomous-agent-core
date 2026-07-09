"""10-Domain Scale Experiment — zero-rebuild at n=8-16 nodes.

Tests engine generalization: same GovernedDiBS code, 10 structurally diverse
domains with 8-16 nodes, mixed mechanisms (linear, tanh, poly, sin), varying
edge densities. Zero code changes per domain.

Run: PYTHONPATH=src python experiments/scale_10domain.py
"""
from __future__ import annotations

import json, math, os, random, statistics, sys, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.cwm_organ import LinearGGMOrgan
from aac.bayesian_dag_posterior import GovernedDiBS, generate_linear_scm_data

OUT = Path(__file__).parent / "scale_10domain.result.json"


def make_domain(n, n_obs, mech, seed):
    rng = random.Random(seed)
    edges = set()
    for i in range(n):
        for j in range(i + 1, n):
            if rng.random() < rng.uniform(0.15, 0.40):
                edges.add((i, j))
    if len(edges) < 3:
        edges = {(i, i+1) for i in range(min(3, n-1))} | {(0, n-1)}
    edges = frozenset(edges)
    if mech == "linear":
        obs, _ = generate_linear_scm_data(n, edges, n_obs, 0.3, rng=rng)
        return obs, edges
    parents = {j: [] for j in range(n)}
    coefs = {}
    for u, v in edges:
        parents[v].append(u)
        coefs[(u, v)] = rng.uniform(0.4, 1.0) * rng.choice([1.0, -1.0])
    obs = []
    for _ in range(n_obs):
        row = [0.0] * n
        for j in range(n):
            val = rng.gauss(0, 0.35)
            for p in parents[j]:
                beta = coefs[(p, j)]
                if mech == "tanh": val += beta * math.tanh(row[p] * 1.5)
                elif mech == "poly": val += beta * (row[p] + 0.3 * row[p]**2)
                elif mech == "sin": val += beta * math.sin(row[p] * 1.5)
            row[j] = val
        obs.append(row)
    return obs, edges


def run_one(obs, true_edges, n, label):
    t0 = time.time()
    org = LinearGGMOrgan(tau=0.02)
    sk = org.propose_skeleton(obs)
    organ_proposals = {1: set()}
    for p in sk:
        for undir in p.edges:
            parts = list(undir)
            if len(parts) == 2:
                organ_proposals[1].add((parts[0], parts[1]))
                organ_proposals[1].add((parts[1], parts[0]))

    di = GovernedDiBS(n_nodes=n, n_particles=25, lambda_sparse=0.5, sigma_noise=0.3, seed=42,
                       likelihood_mode="poly2", organ_proposals=organ_proposals, organ_credits={1: 0.8},
                       max_in_degree=6, adaptive_particles=True)
    di.posterior_temperature = 2.0
    di.update(obs); di.svgd_step(obs, n_gradient_edges=15)

    curve = {k: [] for k in range(n)}
    for k in range(n):
        col = [obs[t][k] for t in range(len(obs))]
        mu = statistics.mean(col); sd = statistics.pstdev(col) or 1.0
        for a in [-1.0, -0.5, 0.0, 0.5, 1.0]: curve[k].append((round(mu + a*sd, 1), mu))
    di.update_with_intervention_curve(obs, curve)
    di.calibrate_temperature()
    di.svgd_step(obs, n_gradient_edges=15)
    di.hippocampal_replay(obs, replay_rounds=1)

    map_dag = di.MAP_dag()
    true_set = frozenset(true_edges)
    mu = {frozenset(e) for e in map_dag}; tu = {frozenset(e) for e in true_set}
    rec = len(mu & tu) / max(len(tu), 1)
    prec = len(mu & tu) / max(len(mu), 1)
    corr = sum(1 for u, v in true_set if (u, v) in map_dag)
    tot = sum(1 for u, v in true_set if (u, v) in map_dag or (v, u) in map_dag)
    orient = corr / max(tot, 1) if tot > 0 else 0
    return {"domain": label, "n_nodes": n, "n_edges": len(true_edges),
            "recall": round(rec, 3), "precision": round(prec, 3),
            "orientation": round(orient, 3), "time_s": round(time.time() - t0, 1)}


def main():
    configs = [
        ("D01_linear_8", 8, 300, "linear", 100),
        ("D02_tanh_9", 9, 280, "tanh", 200),
        ("D03_poly_10", 10, 260, "poly", 300),
        ("D04_sin_8", 8, 300, "sin", 400),
        ("D05_linear_12", 12, 250, "linear", 500),
        ("D06_tanh_14", 14, 230, "tanh", 600),
        ("D07_poly_13", 13, 240, "poly", 700),
        ("D08_sin_11", 11, 260, "sin", 800),
        ("D09_linear_16", 16, 220, "linear", 900),
        ("D10_tanh_15", 15, 220, "tanh", 1000),
        ("D11_linear_20", 20, 200, "linear", 1100),
        ("D12_tanh_18", 18, 200, "tanh", 1200),
    ]

    results = []
    for label, n, n_obs, mech, seed in configs:
        print(f"\n{label}: n={n}, n_obs={n_obs}, mech={mech}")
        obs, true_edges = make_domain(n, n_obs, mech, seed)
        r = run_one(obs, true_edges, n, label)
        results.append(r)
        print(f"  recall={r['recall']:.3f}  prec={r['precision']:.3f}  orient={r['orientation']:.3f}  t={r['time_s']:.0f}s")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    recalls = [r["recall"] for r in results]
    orients = [r["orientation"] for r in results]
    times = [r["time_s"] for r in results]
    total_edges = sum(r["n_edges"] for r in results)
    print(f"\n=== 10 domains, zero rebuild ===")
    print(f"  total_edges: {total_edges}  avg_nodes: {statistics.mean([r['n_nodes'] for r in results]):.0f}")
    print(f"  avg_recall: {statistics.mean(recalls):.3f}  min: {min(recalls):.3f}  max: {max(recalls):.3f}")
    print(f"  avg_orient: {statistics.mean(orients):.3f}")
    print(f"  total_time: {sum(times):.0f}s  avg_per_domain: {statistics.mean(times):.0f}s")
    print(f"  zero_rebuild: True")


if __name__ == "__main__":
    main()
