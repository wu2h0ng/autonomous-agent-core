"""Fast vs DiBS Orientation Benchmark.
Run: PYTHONPATH=src python experiments/fast_orient_bench.py
"""
from __future__ import annotations

import math, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.product_engine import ProductDiscoveryEngine
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
    configs = [
        ("n15_lin", 15, 250, "linear", 42),
        ("n20_tanh", 20, 220, "tanh", 99),
        ("n30_lin", 30, 180, "linear", 199),
    ]
    for mode, n_p in [(False, 30), (True, 0), (False, 100)]:
        label = f"DiBS_P={n_p}" if not mode else "Fast O(|E|)"
        recalls, orients, times = [], [], []
        for name, n, n_obs, mech, seed in configs:
            obs, true_edges = make_domain(n, n_obs, mech, seed)
            engine = ProductDiscoveryEngine(skeleton_tau=0.05, n_particles=n_p if n_p > 0 else 30,
                                             use_fast_orient=mode, seed=42)
            r = engine.discover(obs, true_edges)
            recalls.append(r.recall); orients.append(r.orientation_accuracy); times.append(r.time_s)
        print(f"{label:15s}: recall={sum(recalls)/len(recalls):.3f} orient={sum(orients)/len(orients):.3f} t={sum(times)/len(times):.0f}s")


if __name__ == "__main__":
    main()
