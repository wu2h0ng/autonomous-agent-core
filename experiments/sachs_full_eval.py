"""Sachs Full Evaluation — all SOTA optimizations on real biology.

Runs GovernedDiBS with poly2 likelihood, differential intervention curves,
hippocampal replay, MEC confidence, and Bayesian ensemble on the real Sachs
protein signaling dataset (854 observational + 5400 interventional rows).

Baseline: linear GGM recall 0.588@0.625 on Sachs skeleton (established by
sachs_openworld.py). All improvements since: rank probe, NOTEARS, GOLEM
per-node sigma, DCD intervention likelihood, BOED, hippocampal replay, MEC.

Run: PYTHONPATH=src python experiments/sachs_full_eval.py
"""
from __future__ import annotations

import json, math, os, random, statistics, sys, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.cwm_organ import LinearGGMOrgan, PolynomialOrgan
from aac.bayesian_dag_posterior import GovernedDiBS

OUT = Path(__file__).parent / "sachs_full_eval.result.json"

PROTEINS = ["Raf","Mek","Plcg","PIP2","PIP3","Erk","Akt","PKA","PKC","P38","Jnk"]
GROUND_TRUTH = [
    ("PKC","Raf"),("PKC","Mek"),("PKC","Jnk"),("PKC","P38"),("PKC","PKA"),
    ("PKA","Raf"),("PKA","Mek"),("PKA","Erk"),("PKA","Akt"),("PKA","Jnk"),("PKA","P38"),
    ("Raf","Mek"),("Mek","Erk"),("Erk","Akt"),
    ("Plcg","PIP2"),("Plcg","PIP3"),("PIP3","PIP2"),
]


def load_sachs_obs():
    path = Path(__file__).parent / "data" / "sachs_obs.txt"
    with open(path) as f:
        rows = [ln.split() for ln in f.read().splitlines()[1:] if ln.strip()]
    return [[float(v) for v in r] for r in rows]


def main():
    obs = load_sachs_obs()
    n = 11; n_obs = len(obs)
    true_edges = frozenset({(PROTEINS.index(a), PROTEINS.index(b)) for a,b in GROUND_TRUTH})
    true_set = frozenset(true_edges)
    true_undir = {frozenset(e) for e in true_set}
    print(f"Sachs: n={n}, n_obs={n_obs}, |E|={len(true_edges)} (consensus DAG)")

    print("\n--- Linear GGM baseline ---")
    t0 = time.time()
    ggm = LinearGGMOrgan(tau=0.02)
    sk = ggm.propose_skeleton(obs)
    ggm_edges = set()
    for p in sk:
        for undir in p.edges: parts=list(undir)
        if len(parts)==2: ggm_edges.add(frozenset(parts))
    ggm_recall = len(ggm_edges & true_undir) / max(len(true_undir), 1)
    ggm_precision = len(ggm_edges & true_undir) / max(len(ggm_edges), 1)
    ggm_t = time.time() - t0
    print(f"  recall={ggm_recall:.3f}  precision={ggm_precision:.3f}  n_edges={len(ggm_edges)}  t={ggm_t:.1f}s")

    organ_proposals = {1: set()}
    for undir in ggm_edges:
        parts = list(undir)
        if len(parts)==2:
            organ_proposals[1].add((parts[0],parts[1])); organ_proposals[1].add((parts[1],parts[0]))

    print("\n--- GovernedDiBS + poly2 + differential curve + hippocampal replay ---")
    t0 = time.time()
    di = GovernedDiBS(n_nodes=n, n_particles=30, lambda_sparse=0.5, sigma_noise=0.3, seed=42,
                       likelihood_mode="poly2", organ_proposals=organ_proposals, organ_credits={1:0.8})
    di.posterior_temperature = 2.0
    print("  update+svgd...", flush=True)
    di.update(obs); di.svgd_step(obs, n_gradient_edges=15)

    print("  diff curve...", flush=True)
    curve = {k:[] for k in range(n)}
    for k in range(n):
        col = [obs[t][k] for t in range(len(obs))]
        mu = statistics.mean(col); sd = statistics.pstdev(col) or 1.0
        for a in [-1.0, -0.5, 0.0, 0.5, 1.0]: curve[k].append((round(mu+a*sd,1),mu))
    di.update_with_intervention_curve(obs, curve)
    di.calibrate_temperature()

    print("  svgd rounds...", flush=True)
    for _ in range(2): di.svgd_step(obs, n_gradient_edges=15); di.calibrate_temperature()
    print("  hippocampal replay...", flush=True)
    di.hippocampal_replay(obs, replay_rounds=2)

    map_dag = di.MAP_dag()
    map_undir = {frozenset(e) for e in map_dag}
    dibs_recall = len(map_undir & true_undir) / max(len(true_undir), 1)
    dibs_precision = len(map_undir & true_undir) / max(len(map_undir), 1)

    corr = sum(1 for u,v in true_set if (u,v) in map_dag)
    total = sum(1 for u,v in true_set if (u,v) in map_dag or (v,u) in map_dag)
    orient = corr / max(total, 1)

    ens = di.ensemble_confidence(obs, n_ensembles=2)
    mec_conf = di.MEC_confidence()

    def auc(marg):
        labs, scs = [], []
        for i in range(n):
            for j in range(n):
                if i==j: continue
                scs.append(max(marg.get((i,j),0), marg.get((j,i),0)))
                labs.append(1 if (i,j) in true_set or (j,i) in true_set else 0)
        if not labs or sum(labs) in (0,len(labs)): return 0.5
        paired = sorted(zip(scs,labs), reverse=True, key=lambda x:x[0])
        n_pos = sum(labs); ranks = [i+1 for i,(_,l) in enumerate(paired) if l==1]
        return (sum(ranks)-n_pos*(n_pos+1)/2)/(n_pos*(len(labs)-n_pos))

    dibs_t = time.time() - t0

    result = {
        "dataset": "Sachs", "n_nodes": n, "n_obs": n_obs, "n_true_edges": len(true_edges),
        "GGM_recall": round(ggm_recall,3), "GGM_precision": round(ggm_precision,3),
        "DiBS_recall": round(dibs_recall,3), "DiBS_precision": round(dibs_precision,3),
        "DiBS_orientation_acc": round(orient,3),
        "DiBS_confidence": round(ens["confidence"],3),
        "DiBS_MEC_confidence": round(mec_conf,3),
        "DiBS_ESS": round(di.effective_sample_size(),1),
        "DiBS_n_MECs": len(di.MEC_clusters()),
        "DiBS_AUC": round(auc(ens["marginals"]),3),
        "DiBS_time_s": round(dibs_t,1),
        "DiBS_MAP_n_edges": len(map_dag),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"  recall={dibs_recall:.3f} (GGM={ggm_recall:.3f}, Δ={dibs_recall-ggm_recall:+.3f})")
    print(f"  precision={dibs_precision:.3f}  orient_acc={orient:.3f}")
    print(f"  conf={ens['confidence']:.3f}  MEC_conf={mec_conf:.3f}  ESS={di.effective_sample_size():.0f}  AUC={auc(ens['marginals']):.3f}")
    print(f"  MAP_edges={len(map_dag)}  MECs={len(di.MEC_clusters())}  t={dibs_t:.1f}s")
    print(f"\nResult → {OUT.resolve()}")


if __name__ == "__main__":
    main()
