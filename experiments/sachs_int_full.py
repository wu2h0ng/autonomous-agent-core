"""Sachs Interventional Likelihood — 5400 do() rows fed into GovernedDiBS.

Complete causal discovery loop on real biology:
- Skeleton: GGM + auto-tuned tau from observational data
- Orientation: GovernedDiBS with poly2 likelihood on obs+int augmented matrix
- Verification: interventional data enters likelihood naturally —
  different candidate DAGs predict different do() outcomes,
  DiBS posterior scores them → automatic direct/indirect effect decomposition

Compares:
A) Observational only (854 rows) — baseline
B) Observational + interventional (854 + 5400 = 6254 rows) — full pipeline
C) Interventional only (5400 rows) — just do() data

Run: PYTHONPATH=src python experiments/sachs_int_full.py
"""
from __future__ import annotations

import json, os, random, statistics, sys, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.product_engine import ProductDiscoveryEngine
from aac.cwm_organ import LinearGGMOrgan
from aac.bayesian_dag_posterior import GovernedDiBS

OUT = Path(__file__).parent / "sachs_int_full.result.json"
PROTEINS = ["Raf","Mek","Plcg","PIP2","PIP3","Erk","Akt","PKA","PKC","P38","Jnk"]
GROUND_TRUTH = [
    ("PKC","Raf"),("PKC","Mek"),("PKC","Jnk"),("PKC","P38"),("PKC","PKA"),
    ("PKA","Raf"),("PKA","Mek"),("PKA","Erk"),("PKA","Akt"),("PKA","Jnk"),("PKA","P38"),
    ("Raf","Mek"),("Mek","Erk"),("Erk","Akt"),
    ("Plcg","PIP2"),("Plcg","PIP3"),("PIP3","PIP2"),
]


def load_obs():
    p = os.path.join(os.path.dirname(__file__), "data", "sachs_obs.txt")
    with open(p) as f:
        rows = [ln.split() for ln in f.read().splitlines()[1:] if ln.strip()]
    return [[float(v) for v in r] for r in rows]


def load_int():
    p = os.path.join(os.path.dirname(__file__), "data", "sachs_int.txt")
    out = []
    with open(p) as f:
        for ln in f.read().splitlines()[1:]:
            if not ln.strip(): continue
            parts = ln.split()
            out.append([float(v) for v in parts[:11]])
    return out


def evaluate(dag, true_edges):
    mu = {frozenset(e) for e in dag}; tu = {frozenset(e) for e in true_edges}
    recall = len(mu & tu) / max(len(tu), 1)
    precision = len(mu & tu) / max(len(mu), 1)
    corr = sum(1 for u,v in true_edges if (u,v) in dag)
    tot = sum(1 for u,v in true_edges if (u,v) in dag or (v,u) in dag)
    orient = corr / max(tot, 1) if tot > 0 else 0
    return recall, precision, orient


def run_governed_dibs(obs_all, true_edges, n, label):
    t0 = time.time()
    org = LinearGGMOrgan(tau=0.05)
    sk = org.propose_skeleton(obs_all)
    organ_proposals = {1: set()}
    for p in sk:
        for undir in p.edges:
            parts = list(undir)
            if len(parts) == 2:
                organ_proposals[1].add((parts[0], parts[1]))
                organ_proposals[1].add((parts[1], parts[0]))

    di = GovernedDiBS(n_nodes=n, n_particles=30, lambda_sparse=0.5, sigma_noise=0.3, seed=42,
                       likelihood_mode="poly2", organ_proposals=organ_proposals,
                       organ_credits={1: 0.8})
    di.posterior_temperature = 2.0
    di.update(obs_all)
    di.resample_and_perturb()
    di.update(obs_all)
    di.hippocampal_replay(obs_all, replay_rounds=2)

    rec, prec, orient = evaluate(di.MAP_dag(), true_edges)
    ens = di.ensemble_confidence(obs_all, n_ensembles=2)
    return {
        "method": label, "n_obs": len(obs_all),
        "recall": round(rec, 3), "precision": round(prec, 3),
        "orientation": round(orient, 3),
        "confidence": round(ens["confidence"], 3),
        "MEC_confidence": round(di.MEC_confidence(), 3),
        "ESS": round(di.effective_sample_size(), 1),
        "time_s": round(time.time() - t0, 1),
    }


def main():
    obs = load_obs(); int_data = load_int()
    n = len(PROTEINS)
    true_edges = frozenset({(PROTEINS.index(a), PROTEINS.index(b)) for a,b in GROUND_TRUTH})
    print(f"Sachs: n_obs={len(obs)}, n_int={len(int_data)}, |E|={len(true_edges)}")

    results = []

    for label, data in [
        ("A_Fast_obs", obs),
        ("B_Fast_obs+int", obs + int_data),
        ("C_DiBS_obs", obs),
        ("D_DiBS_obs+int", obs + int_data),
    ]:
        if "Fast" in label:
            t0 = time.time()
            engine = ProductDiscoveryEngine(skeleton_tau=0.05, use_fast_orient=True)
            r = engine.discover(data, true_edges)
            rec, prec, orient = r.recall, r.precision, r.orientation_accuracy
            t = r.time_s
            conf = r.confidence
        else:
            res = run_governed_dibs(data, true_edges, n, label)
            rec, prec, orient = res["recall"], res["precision"], res["orientation"]
            t = res["time_s"]; conf = res["confidence"]
        results.append({"method": label, "n_obs": len(data), "recall": round(rec,3),
                         "precision": round(prec,3), "orientation": round(orient,3),
                         "confidence": round(conf,3), "time_s": round(t,1)})
        print(f"  {label:20s}: recall={rec:.3f} prec={prec:.3f} orient={orient:.3f} t={t:.0f}s")


if __name__ == "__main__":
    main()
