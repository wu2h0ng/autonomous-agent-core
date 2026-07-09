"""Product Engine Benchmark — n=30,40,50 Skeleton+Orientation.
Run: PYTHONPATH=src python experiments/product_engine_bench.py
"""
from __future__ import annotations

import math, os, random, statistics, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.product_engine import ProductDiscoveryEngine
from aac.cwm_organ import LinearGGMOrgan
from aac.bayesian_dag_posterior import generate_linear_scm_data


def make_domain(n, n_obs, mech, seed):
    rng = random.Random(seed)
    edges = set()
    for i in range(n):
        for j in range(i+1,n):
            if rng.random() < rng.uniform(0.12,0.30): edges.add((i,j))
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


def main():
    engine = ProductDiscoveryEngine(skeleton_tau=0.02, n_particles=30,
                                     likelihood_mode="poly2", seed=42)
    for n, n_obs, mech, seed, label in [
        (15, 250, "linear", 42, "L15"),
        (20, 220, "tanh", 99, "L20"),
        (30, 180, "linear", 199, "L30"),
    ]:
        print(f"\n{label}: n={n}, n_obs={n_obs}")
        obs, true_edges = make_domain(n, n_obs, mech, seed)
        r = engine.discover(obs, true_edges)
        t0 = time.time()
        ggm = LinearGGMOrgan(tau=0.02)
        ggm_sk = set()
        for p in ggm.propose_skeleton(obs):
            for u in p.edges: parts=list(u)
            if len(parts)==2: ggm_sk.add(frozenset(parts))
        ggm_rec = len(ggm_sk & {frozenset(e) for e in true_edges}) / max(len(true_edges),1)
        print(f"  product: recall={r.recall:.3f} orient={r.orientation_accuracy:.3f} "
              f"conf={r.confidence:.3f} t={r.time_s:.0f}s sk={r.n_skeleton_edges} dag={r.n_dag_edges}")


if __name__ == "__main__":
    main()
