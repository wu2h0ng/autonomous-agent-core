"""Tau Tuning — find optimal skeleton precision for product engine.
Run: PYTHONPATH=src python experiments/tau_tune.py
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
        ("n15_linear", 15, 250, "linear", 42),
        ("n20_tanh", 20, 220, "tanh", 99),
        ("n30_linear", 30, 180, "linear", 199),
    ]
    for tau in [0.02, 0.03, 0.04, 0.05, 0.06, 0.08]:
        recalls, orients, times, sk_sizes = [], [], [], []
        for label, n, n_obs, mech, seed in configs:
            obs, true_edges = make_domain(n, n_obs, mech, seed)
            engine = ProductDiscoveryEngine(skeleton_tau=tau, n_particles=30, seed=42)
            r = engine.discover(obs, true_edges)
            recalls.append(r.recall); orients.append(r.orientation_accuracy)
            times.append(r.time_s); sk_sizes.append(r.n_skeleton_edges)
        avg_r = sum(recalls)/len(recalls); avg_o = sum(orients)/len(orients)
        avg_t = sum(times)/len(times); avg_sk = sum(sk_sizes)/len(sk_sizes)
        print(f"tau={tau:.2f}: recall={avg_r:.3f} orient={avg_o:.3f} sk_edges={avg_sk:.0f} t={avg_t:.0f}s")


if __name__ == "__main__":
    main()
