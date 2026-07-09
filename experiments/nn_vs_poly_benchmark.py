"""NN vs Poly Benchmark — compare MLP-based vs polynomial nonlinear mechanism fitting.

Run: PYTHONPATH=src python experiments/nn_vs_poly_benchmark.py
"""
from __future__ import annotations

import math, os, random, statistics, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.cwm_organ import LinearGGMOrgan, PolynomialOrgan
from aac.nn_cwm_organ import NNMechanismOrgan
from aac.bayesian_dag_posterior import GovernedDiBS


def make_domain(n, n_obs, edges, mech, seed):
    rng = random.Random(seed)
    if mech == "linear":
        from aac.bayesian_dag_posterior import generate_linear_scm_data
        obs, _ = generate_linear_scm_data(n, frozenset(edges), n_obs, 0.3, rng=rng)
        return obs, frozenset(edges)
    parents = {j: [] for j in range(n)}
    coefs = {}
    for u, v in edges: parents[v].append(u); coefs[(u,v)] = rng.uniform(0.4,1.0)*rng.choice([1.0,-1.0])
    obs = []
    for _ in range(n_obs):
        row = [0.0]*n
        for j in range(n):
            val = rng.gauss(0, 0.35)
            for p in parents[j]:
                if mech == "tanh": val += coefs[(p,j)]*math.tanh(row[p]*1.5)
                elif mech == "poly": val += coefs[(p,j)]*(row[p]+0.3*row[p]**2)
                elif mech == "sin": val += coefs[(p,j)]*math.sin(row[p]*1.5)
            row[j] = val
        obs.append(row)
    return obs, frozenset(edges)


def run(obs, true_edges, n, mech, organ_type):
    t0 = time.time()
    if organ_type == "poly":
        org = PolynomialOrgan(max_degree=2, tau=0.05)
    else:
        org = NNMechanismOrgan([8, 4], "tanh", 0.01, 150, 0.05, 0)

    sk = org.propose_skeleton(obs)
    organ_proposals = {1: set()}
    for p in sk:
        for undir in p.edges:
            parts = list(undir)
            if len(parts) == 2:
                organ_proposals[1].add((parts[0], parts[1]))
                organ_proposals[1].add((parts[1], parts[0]))

    di = GovernedDiBS(n_nodes=n, n_particles=40, lambda_sparse=0.5, sigma_noise=0.3, seed=42,
                       likelihood_mode="poly2", organ_proposals=organ_proposals, organ_credits={1:0.8})
    di.posterior_temperature = 2.0; di.update(obs); di.svgd_step(obs, n_gradient_edges=15)
    di.calibrate_temperature(); di.svgd_step(obs, n_gradient_edges=15)

    map_dag = di.MAP_dag()
    true_set = frozenset(true_edges)
    mu = {frozenset(e) for e in map_dag}; tu = {frozenset(e) for e in true_set}
    rec = len(mu & tu) / max(len(tu), 1)
    prec = len(mu & tu) / max(len(mu), 1)
    corr = sum(1 for u, v in true_set if (u, v) in map_dag)
    total = sum(1 for u, v in true_set if (u, v) in map_dag or (v, u) in map_dag)
    orient = corr / max(total, 1)
    return {"recall": round(rec,3), "precision": round(prec,3),
            "orientation_acc": round(orient,3), "time_s": round(time.time()-t0,1)}


def main():
    domains = [
        ("tanh_chain", 6, 200, {(0,1),(1,2),(2,3),(3,4),(4,5)}, "tanh", 42),
        ("sin_chain", 6, 200, {(0,1),(1,2),(2,3),(3,4),(4,5)}, "sin", 99),
        ("poly_mixed", 7, 200, {(0,1),(1,2),(2,3),(3,4),(4,5),(5,6)}, "poly", 199),
    ]
    for name, n, n_obs, edges, mech, seed in domains:
        obs, true_edges = make_domain(n, n_obs, edges, mech, seed)
        print(f"\n{name} ({mech}): n={n}, |E|={len(true_edges)}")
        r_poly = run(obs, true_edges, n, mech, "poly")
        r_nn = run(obs, true_edges, n, mech, "nn")
        print(f"  poly:  recall={r_poly['recall']:.3f} orient={r_poly['orientation_acc']:.3f} t={r_poly['time_s']:.0f}s")
        print(f"  NN:    recall={r_nn['recall']:.3f} orient={r_nn['orientation_acc']:.3f} t={r_nn['time_s']:.0f}s")


if __name__ == "__main__":
    main()
