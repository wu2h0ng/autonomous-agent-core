"""10-Domain Interventional Benchmark — obs vs obs+int across domains.

Validates that interventional likelihood improvement is GENERAL, not Sachs-specific.
Each domain: generate obs data + synthetic do() interventions → compare recall/orient.

Run: PYTHONPATH=src python experiments/interv_bench_10domain.py
"""
from __future__ import annotations

import json, math, os, random, statistics, sys, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.product_engine import ProductDiscoveryEngine
from aac.bayesian_dag_posterior import generate_linear_scm_data

OUT = Path(__file__).parent / "interv_bench_10domain.result.json"


def make_domain(n, n_obs, mech, seed):
    rng = random.Random(seed)
    edges = set()
    for i in range(n):
        for j in range(i+1,n):
            if rng.random() < rng.uniform(0.12,0.30): edges.add((i,j))
    if len(edges) < 3: edges = {(i,i+1) for i in range(min(3,n-1))}|{(0,n-1)}
    edges = frozenset(edges); true_set = frozenset(edges)
    if mech == "linear":
        obs, coeffs = generate_linear_scm_data(n, edges, n_obs, 0.3, rng=rng)
        int_rows = _gen_interventions_linear(n, edges, coeffs, rng, n_int=50, n_intervenable=3)
        return obs, int_rows, true_set
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
    int_rows = _gen_interventions_nonlinear(n, parents, coefs, mech, rng, n_int=50, n_intervenable=3)
    return obs, int_rows, true_set


def _gen_interventions_linear(n, edges, coeffs, rng, n_int, n_intervenable):
    intervenable = rng.sample(range(n), min(n_intervenable, n))
    int_rows = []
    for k in intervenable:
        col = [rng.gauss(0,1) for _ in range(50)]
        mu = statistics.mean(col) if col else 0; sd = statistics.pstdev(col) or 1.0
        for v in [mu-sd, mu, mu+sd]:
            for _ in range(n_int // 3):
                row = [0.0]*n
                for j in range(n):
                    val = rng.gauss(0,0.3)
                    for p in [p for p,u in [(p,u) for (p,u) in edges if u==j]]:
                        val += coeffs[(p,j)] * (v if p==k else rng.gauss(0,1))
                    row[j] = val
                row[k] = v
                int_rows.append([float(x) for x in row])
    return int_rows


def _gen_interventions_nonlinear(n, parents, coefs, mech, rng, n_int, n_intervenable):
    intervenable = rng.sample(range(n), min(n_intervenable, n))
    int_rows = []
    for k in intervenable:
        for v in [-1.5, 0.0, 1.5]:
            for _ in range(n_int // 3):
                row = [0.0]*n; row[k] = v
                for j in range(n):
                    if j==k: continue
                    val = rng.gauss(0,0.35)
                    for p in parents[j]:
                        beta = coefs[(p,j)]
                        if mech=="tanh": val+=beta*math.tanh(row[p]*1.5)
                        elif mech=="poly": val+=beta*(row[p]+0.3*row[p]**2)
                    row[j]=val
                int_rows.append(row)
    return int_rows


def evaluate(dag, true_edges):
    mu = {frozenset(e) for e in dag}; tu = {frozenset(e) for e in true_edges}
    rec = len(mu & tu) / max(len(tu), 1)
    prec = len(mu & tu) / max(len(mu), 1)
    corr = sum(1 for u,v in true_edges if (u,v) in dag)
    tot = sum(1 for u,v in true_edges if (u,v) in dag or (v,u) in dag)
    orient = corr / max(tot, 1) if tot>0 else 0
    return rec, prec, orient


def main():
    configs = [
        (8, 250, "linear", 100), (9, 240, "tanh", 200), (10, 230, "poly", 300),
        (8, 250, "linear", 400), (12, 220, "tanh", 500), (14, 200, "poly", 600),
        (13, 200, "linear", 700), (11, 220, "tanh", 800), (10, 210, "linear", 900),
        (9, 200, "poly", 1000),
    ]
    results = []
    for i, (n, n_obs, mech, seed) in enumerate(configs):
        obs, int_rows, true_edges = make_domain(n, n_obs, mech, seed)
        obs_int = obs + int_rows
        engine = ProductDiscoveryEngine(skeleton_tau=0.05, use_fast_orient=True, n_particles=0)
        r_obs = engine.discover(obs, true_edges)
        r_int = engine.discover(obs_int, true_edges)
        rec_o, _, ori_o = evaluate(r_obs.dag, true_edges)
        rec_i, _, ori_i = evaluate(r_int.dag, true_edges)
        results.append({"domain": f"D{i:02d}_{mech}_n{n}", "n": n, "obs_recall": rec_o, "obs_orient": ori_o,
                         "int_recall": rec_i, "int_orient": ori_i})
        print(f"D{i:02d} n={n} {mech}: obs={rec_o:.2f}/{ori_o:.2f}  int={rec_i:.2f}/{ori_i:.2f}")

    obs_r = statistics.mean([r["obs_recall"] for r in results])
    int_r = statistics.mean([r["int_recall"] for r in results])
    obs_o = statistics.mean([r["obs_orient"] for r in results])
    int_o = statistics.mean([r["int_orient"] for r in results])
    print(f"\n10-domain avg: obs={obs_r:.3f}/{obs_o:.3f}  int={int_r:.3f}/{int_o:.3f}")
    print(f"  Δ recall: {int_r-obs_r:+.3f}  Δ orient: {int_o-obs_o:+.3f}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
