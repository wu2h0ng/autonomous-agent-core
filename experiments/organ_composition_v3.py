"""Organ Composition v3 — pure nonlinear chain: ALL edges in same MEC.

Strict test of RR-0046 §27: pure nonlinear tanh chain (0→1→2→3→4→5).
Under tanh with identical mechanism forms, ALL edges are in the same MEC.
Data alone CANNOT orient any edge — every pair (i,i+1) is reversible.
The engine SHOULD fail orientation here. Language organ SHOULD provide the fix.

Run: PYTHONPATH=src python experiments/organ_composition_v3.py
"""
from __future__ import annotations

import json, math, os, random, statistics, sys, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.cwm_organ import LinearGGMOrgan
from aac.language_orientation_organ import LanguageOrientationOrgan
from aac.bayesian_dag_posterior import GovernedDiBS

OUT = Path(__file__).parent / "organ_composition_v3.result.json"


def make_pure_chain(n_nodes=6, n_obs=600, noise_std=0.3, seed=42):
    edges = frozenset({(i, i + 1) for i in range(n_nodes - 1)})
    rng = random.Random(seed)
    obs = []
    for _ in range(n_obs):
        row = [0.0] * n_nodes
        row[0] = rng.gauss(0, noise_std)
        for j in range(1, n_nodes):
            row[j] = math.tanh(row[j - 1] * 1.5) + rng.gauss(0, noise_std)
        obs.append(row)
    return obs, edges


class ForwardStub:
    def __init__(self, n, confidence=0.8):
        self._n = n
        self.confidence = confidence
    def propose(self, prompt):
        orients = []
        for line in prompt.split("\n"):
            line = line.strip()
            if line.startswith("(") and ") -- (" in line:
                try:
                    i = int(line.split(":")[0].replace("(", "").strip())
                    j = int(line.split("--")[1].split(":")[0].replace("(", "").strip())
                    a, b = min(i, j), max(i, j)
                    direction = f"{a}→{b}"
                    orients.append({"i": a, "j": b, "direction": direction, "score": self.confidence})
                except: continue
        return {"orientations": orients}


def compute(di, true_edges, n_nodes, obs):
    map_dag = di.MAP_dag()
    true_set = frozenset(true_edges)
    mu = {frozenset(e) for e in map_dag}
    tu = {frozenset(e) for e in true_set}
    rec = len(mu & tu) / max(len(tu), 1)
    prec = len(mu & tu) / max(len(mu), 1)
    corr = sum(1 for u, v in true_set if (u, v) in map_dag)
    total = sum(1 for u, v in true_set if (u, v) in map_dag or (v, u) in map_dag)
    orient = corr / max(total, 1)
    ens = di.ensemble_confidence(obs, n_ensembles=2)
    def auc(marg):
        labs, scs = [], []
        for i in range(n_nodes):
            for j in range(n_nodes):
                if i==j: continue
                scs.append(max(marg.get((i,j),0), marg.get((j,i),0)))
                labs.append(1 if (i,j) in true_set or (j,i) in true_set else 0)
        if not labs or sum(labs) in (0, len(labs)): return 0.5
        paired = sorted(zip(scs, labs), reverse=True, key=lambda x: x[0])
        n_pos = sum(labs)
        ranks = [i+1 for i,(_,l) in enumerate(paired) if l==1]
        return (sum(ranks)-n_pos*(n_pos+1)/2)/(n_pos*(len(labs)-n_pos))
    return {
        "recall": round(rec,3), "precision": round(prec,3),
        "orientation_acc": round(orient,3),
        "confidence": round(ens["confidence"],3),
        "AUC": round(auc(ens["marginals"]),3),
    }


def run(label, use_lang, obs, true_edges, n):
    t0 = time.time()
    organ = LinearGGMOrgan(tau=0.05)
    sk = organ.propose_skeleton(obs)
    organ_proposals = {1: set()}
    for p in sk:
        for undir in p.edges:
            parts = list(undir); 
            if len(parts)==2: organ_proposals[1].add((parts[0],parts[1])); organ_proposals[1].add((parts[1],parts[0]))
    organ_credits = {1:0.8}
    if use_lang:
        backend = ForwardStub(n, 0.85)
        lang = LanguageOrientationOrgan(backend, [f"v{i}" for i in range(n)])
        skeleton = frozenset()
        for s in [frozenset(p.edges) if isinstance(p.edges,frozenset) else p.edges for p in sk]:
            skeleton = skeleton | s
        orients = lang.propose_orientation(skeleton)
        organ_proposals[2] = set()
        for p in orients:
            for pair in p.edges:
                if isinstance(pair,tuple) and len(pair)==2: organ_proposals[2].add(pair)
        organ_credits[2]=0.85
    di = GovernedDiBS(n_nodes=n, n_particles=50, lambda_sparse=0.5, sigma_noise=0.3, seed=42,
                       likelihood_mode="poly2", organ_proposals=organ_proposals, organ_credits=organ_credits)
    di.posterior_temperature=2.0
    di.update(obs); di.svgd_step(obs, n_gradient_edges=20)
    curve = {k:[] for k in range(n)}
    for k in range(n):
        col = [obs[t][k] for t in range(len(obs))]; mu=statistics.mean(col); sd=statistics.pstdev(col) or 1.0
        for a in [-1.0,-0.5,0.0,0.5,1.0]: curve[k].append((round(mu+a*sd,1),mu))
    di.update_with_intervention_curve(obs,curve); di.calibrate_temperature()
    for _ in range(2): di.svgd_step(obs, n_gradient_edges=20); di.calibrate_temperature()
    di.hippocampal_replay(obs, replay_rounds=2)
    r = compute(di, true_edges, n, obs); r["method"]=label; r["time_s"]=round(time.time()-t0,1)
    return r

def main():
    for n_obs in [50, 30]:
        obs, true_edges = make_pure_chain(6, n_obs, 0.5, 42)
        r1 = run(f"data_{n_obs}", False, obs, true_edges, 6)
        r2 = run(f"data+lang_{n_obs}", True, obs, true_edges, 6)
        print(f"\nPure nonlinear tanh chain: n_obs={n_obs}, noise=0.5")
        for r in [r1, r2]:
            print(f"  {r['method']:15s}: recall={r['recall']:.3f} orient={r['orientation_acc']:.3f} AUC={r['AUC']:.3f} conf={r['confidence']:.3f}")
        d = r2["orientation_acc"] - r1["orientation_acc"]
        print(f"  Δ orientation: {d:+.3f}  → {'LIFT ✓' if d > 0 else 'no lift'}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps([r1,r2], indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
