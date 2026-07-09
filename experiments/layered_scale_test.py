"""Layered Discovery Scale Test — n=30, n=40, n=50.
Run: PYTHONPATH=src python experiments/layered_scale_test.py
"""
from __future__ import annotations

import math, os, random, statistics, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.layered_discovery import layered_discover
from aac.cwm_organ import LinearGGMOrgan
from aac.bayesian_dag_posterior import GovernedDiBS, generate_linear_scm_data


def make_domain(n, n_obs, mech, seed):
    rng = random.Random(seed)
    edges = set()
    for i in range(n):
        for j in range(i+1, n):
            if rng.random() < rng.uniform(0.12, 0.30): edges.add((i,j))
    if len(edges) < 3: edges = {(i,i+1) for i in range(min(3,n-1))}|{(0,n-1)}
    edges = frozenset(edges)
    if mech == "linear":
        obs, _ = generate_linear_scm_data(n, edges, n_obs, 0.3, rng=rng); return obs, edges
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
            row[j]=val
        obs.append(row)
    return obs, edges


def evaluate(dag, true_edges):
    mu = {frozenset(e) for e in dag}; tu = {frozenset(e) for e in true_edges}
    rec = len(mu & tu) / max(len(tu), 1)
    prec = len(mu & tu) / max(len(mu), 1)
    corr = sum(1 for u,v in true_edges if (u,v) in dag)
    tot = sum(1 for u,v in true_edges if (u,v) in dag or (v,u) in dag)
    orient = corr / max(tot, 1) if tot>0 else 0
    return rec, prec, orient


def main():
    for n, n_obs, mech, seed, label in [
        (30, 180, "linear", 42, "L30_linear"),
        (40, 150, "tanh", 99, "L40_tanh"),
        (50, 120, "linear", 199, "L50_linear"),
    ]:
        print(f"\n{label}: n={n}, n_obs={n_obs}, mech={mech}")
        obs, true_edges = make_domain(n, n_obs, mech, seed)
        n_e = len(true_edges)
        print(f"  true_edges={n_e}")

        t0 = time.time()
        result = layered_discover(obs, max_cluster_size=12, tau=0.02,
                                   sigma_noise=0.3, lambda_sparse=0.5, seed=42,
                                   likelihood_mode="poly2")
        rec, prec, orient = evaluate(result["edges"], true_edges)
        print(f"  layered: recall={rec:.3f} prec={prec:.3f} orient={orient:.3f} "
              f"clusters={result['n_clusters']} t={time.time()-t0:.0f}s")

        t0 = time.time()
        org = LinearGGMOrgan(tau=0.02)
        sk = org.propose_skeleton(obs)
        ggm_edges = set()
        for p in sk:
            for undir in p.edges:
                parts = list(undir)
                if len(parts)==2: ggm_edges.add(frozenset(parts))
        ggm_rec = len(ggm_edges & {frozenset(e) for e in true_edges}) / max(len(true_edges),1)
        print(f"  GGM:    recall={ggm_rec:.3f}  t={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
