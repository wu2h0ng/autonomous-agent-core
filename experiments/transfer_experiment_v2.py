"""Transfer Experiment v2 — 2000 domains + adaptive update + multi-modal features.

Compares transfer prior at 500, 1000, 2000 domains. Tests adaptive update:
after discovering a domain, feed it back → does the prior improve on the next domain?

Run: PYTHONPATH=src python experiments/transfer_experiment_v2.py
"""
from __future__ import annotations

import json, math, os, random, statistics, sys, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.causal_prior_transfer import CausalPriorLearner, TransferOrgan
from aac.cwm_organ import LinearGGMOrgan
from aac.bayesian_dag_posterior import GovernedDiBS, generate_linear_scm_data

OUT = Path(__file__).parent / "transfer_experiment_v2.result.json"


def make_holdout(name, n, n_obs, edges, mech, seed):
    rng = random.Random(seed)
    if mech == "linear":
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
            row[j] = val
        obs.append(row)
    return obs, frozenset(edges)


def run(obs, true_edges, n, mech, use_prior, learner):
    t0 = time.time()
    organ_proposals = {}; organ_credits = {}
    if use_prior and learner:
        t = TransferOrgan(learner, mech, 0.05)
        sk = t.propose_skeleton(obs)
        organ_proposals[1] = set()
        for p in sk:
            for undir in p.edges:
                parts = list(undir)
                if len(parts)==2: organ_proposals[1].add((parts[0],parts[1])); organ_proposals[1].add((parts[1],parts[0]))
        organ_credits[1] = 0.7
    else:
        organ = LinearGGMOrgan(tau=0.05)
        sk = organ.propose_skeleton(obs)
        organ_proposals[1] = set()
        for p in sk:
            for undir in p.edges:
                parts = list(undir)
                if len(parts)==2: organ_proposals[1].add((parts[0],parts[1])); organ_proposals[1].add((parts[1],parts[0]))
        organ_credits[1] = 0.8
    mode = "poly2" if mech in ("tanh","poly") else "linear"
    di = GovernedDiBS(n_nodes=n, n_particles=40, lambda_sparse=0.5, sigma_noise=0.3, seed=42,
                       likelihood_mode=mode, organ_proposals=organ_proposals, organ_credits=organ_credits)
    di.posterior_temperature = 2.0; di.update(obs); di.svgd_step(obs, n_gradient_edges=15)
    di.calibrate_temperature(); di.svgd_step(obs, n_gradient_edges=15)
    map_dag = di.MAP_dag()
    true_set = frozenset(true_edges)
    mu = {frozenset(e) for e in map_dag}; tu = {frozenset(e) for e in true_set}
    rec = len(mu & tu) / max(len(tu),1)
    prec = len(mu & tu) / max(len(mu),1)
    corr = sum(1 for u,v in true_set if (u,v) in map_dag)
    total = sum(1 for u,v in true_set if (u,v) in map_dag or (v,u) in map_dag)
    orient = corr / max(total,1)
    return {"recall":round(rec,3),"precision":round(prec,3),"orientation_acc":round(orient,3),
            "conf":round(di.confidence(),3),"ESS":round(di.effective_sample_size(),1),
            "time_s":round(time.time()-t0,1)}, map_dag


def main():
    domains = [
        ("linear_chain", 6, 200, {(0,1),(1,2),(2,3),(3,4),(4,5)}, "linear", 99),
        ("tanh_mixed", 7, 180, {(0,1),(1,2),(2,3),(3,4),(4,5),(5,6)}, "tanh", 199),
        ("poly_chain", 8, 180, {(0,1),(1,2),(2,3),(3,4),(4,5),(5,6),(6,7)}, "poly", 299),
        ("tanh_sparse", 9, 160, {(0,1),(1,2),(2,3),(0,4),(4,5),(5,6),(0,7),(7,8)}, "tanh", 399),
    ]

    results = []
    for n_domains in [500, 1000, 2000]:
        print(f"\n{'='*60}")
        print(f"Training on {n_domains} domains...")
        t0 = time.time()
        learner = CausalPriorLearner(n_train_domains=n_domains, seed=42)
        train_t = time.time() - t0

        batch_recalls = []; batch_orients = []
        for name, n, n_obs, edges, mech, seed in domains:
            obs, true_edges = make_holdout(name, n, n_obs, edges, mech, seed)
            r, _ = run(obs, true_edges, n, mech, True, learner)
            batch_recalls.append(r["recall"]); batch_orients.append(r["orientation_acc"])
            r["domain"] = name; r["method"] = f"transfer_{n_domains}"

            r0, _ = run(obs, true_edges, n, mech, False, None)
            r0["domain"] = name; r0["method"] = "from_scratch"
            results.append(r0); results.append(r)

        avg_r = statistics.mean(batch_recalls); avg_o = statistics.mean(batch_orients)
        print(f"  train={train_t:.0f}s  avg_recall={avg_r:.3f}  avg_orient={avg_o:.3f}")

    print(f"\n--- Adaptive update test ---")
    learner = CausalPriorLearner(n_train_domains=1000, seed=42)
    for name, n, n_obs, edges, mech, seed in domains:
        obs, true_edges = make_holdout(name, n, n_obs, edges, mech, seed)
        r, map_dag = run(obs, true_edges, n, mech, True, learner)
        r["domain"] = name; r["method"] = f"adaptive_pre_{name}"
        results.append(r)
        learner.add_domain(obs, map_dag, n, mech)
        r2, _ = run(obs, true_edges, n, mech, True, learner)
        r2["domain"] = name; r2["method"] = f"adaptive_post_{name}"
        results.append(r2)
        print(f"  {name}: pre={r['recall']:.3f} orient={r['orientation_acc']:.3f} → "
              f"post={r2['recall']:.3f} orient={r2['orientation_acc']:.3f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")

    scratch = [r for r in results if r["method"]=="from_scratch"]
    t500 = [r for r in results if r["method"]=="transfer_500"]
    t1k = [r for r in results if r["method"]=="transfer_1000"]
    t2k = [r for r in results if r["method"]=="transfer_2000"]
    print(f"\n=== Scale Curve ===")
    for label, group in [("from_scratch",scratch),("transfer_500",t500),("transfer_1000",t1k),("transfer_2000",t2k)]:
        if group:
            print(f"  {label:15s}: recall={statistics.mean([r['recall'] for r in group]):.3f}  "
                  f"orient={statistics.mean([r['orientation_acc'] for r in group]):.3f}")


if __name__ == "__main__":
    main()
