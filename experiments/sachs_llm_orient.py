"""Sachs LLM Organ Experiment — real Kimi API for protein causal orientation.

Tests RR-0046 §27 composition thesis with REAL LLM on Sachs biology data.
Uses Kimi API to propose causal directions for protein edges, then
compares against consensus ground truth.

Run: PYTHONPATH=src python experiments/sachs_llm_orient.py
"""
from __future__ import annotations

import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.language_orientation_organ import LanguageOrientationOrgan
from aac.llm_organ import LLMAPIBackend
from aac.product_engine import ProductDiscoveryEngine
from aac.cwm_organ import LinearGGMOrgan
from aac.bayesian_dag_posterior import GovernedDiBS

API_KEY = "KIMI_API_KEY_PLACEHOLDER"
API_URL = "https://api.kimi.com/coding/v1/chat/completions"
PROTEINS = ["Raf","Mek","Plcg","PIP2","PIP3","Erk","Akt","PKA","PKC","P38","Jnk"]
GROUND_TRUTH = [
    ("PKC","Raf"),("PKC","Mek"),("PKC","Jnk"),("PKC","P38"),("PKC","PKA"),
    ("PKA","Raf"),("PKA","Mek"),("PKA","Erk"),("PKA","Akt"),("PKA","Jnk"),("PKA","P38"),
    ("Raf","Mek"),("Mek","Erk"),("Erk","Akt"),
    ("Plcg","PIP2"),("Plcg","PIP3"),("PIP3","PIP2"),
]


def load_sachs_obs():
    path = os.path.join(os.path.dirname(__file__), "data", "sachs_obs.txt")
    with open(path) as f:
        rows = [ln.split() for ln in f.read().splitlines()[1:] if ln.strip()]
    return [[float(v) for v in r] for r in rows]


def main():
    obs = load_sachs_obs()
    n = len(PROTEINS)
    true_edges = frozenset({(PROTEINS.index(a), PROTEINS.index(b)) for a, b in GROUND_TRUTH})
    print(f"Sachs: n={n}, |E|={len(true_edges)}")
    print(f"Proteins: {PROTEINS}")

    engine = ProductDiscoveryEngine(skeleton_tau=0.05, use_fast_orient=False, n_particles=30)
    result = engine.discover(obs, true_edges)
    sk = result.skeleton

    print(f"\nGGM skeleton: {len(sk)} undirected edges")
    print(f"  recall: {result.recall:.3f}  orient: {result.orientation_accuracy:.3f}")

    print(f"\nQuerying real LLM (Kimi) for causal directions on Sachs edges...")
    backend = LLMAPIBackend(api_url=API_URL, api_key=API_KEY,
                             model="kimi-k2.6", temperature=None)
    organ = LanguageOrientationOrgan(backend, PROTEINS)
    proposals = organ.propose_orientation(sk)

    llm_correct = 0; llm_total = 0
    for prop in proposals:
        for pair in prop.edges:
            if isinstance(pair, tuple) and len(pair) == 2:
                u, v = pair
                if (u, v) in true_edges:
                    llm_correct += 1; llm_total += 1
                elif (v, u) in true_edges:
                    llm_total += 1
    llm_orient = llm_correct / max(llm_total, 1)
    print(f"  LLM orientation: {llm_correct}/{llm_total} = {llm_orient:.3f}")

    organ_proposals = {1: set()}
    for undir in sk:
        parts = list(undir)
        if len(parts)==2:
            organ_proposals[1].add((parts[0], parts[1]))
            organ_proposals[1].add((parts[1], parts[0]))
    organ_proposals[2] = set()
    for prop in proposals:
        for pair in prop.edges:
            if isinstance(pair, tuple) and len(pair) == 2:
                organ_proposals[2].add(pair)

    di = GovernedDiBS(n_nodes=n, n_particles=30, lambda_sparse=0.5, sigma_noise=0.3, seed=42,
                       likelihood_mode="poly2", organ_proposals=organ_proposals,
                       organ_credits={1: 0.8, 2: 0.85})
    di.posterior_temperature = 2.0; di.update(obs)
    di.resample_and_perturb(); di.update(obs)
    di.hippocampal_replay(obs, replay_rounds=1)
    map_dag = di.MAP_dag()
    mu = {frozenset(e) for e in map_dag}; tu = {frozenset(e) for e in true_edges}
    comp_recall = len(mu & tu) / max(len(tu), 1)
    corr = sum(1 for u, v in true_edges if (u, v) in map_dag)
    tot = sum(1 for u, v in true_edges if (u, v) in map_dag or (v, u) in map_dag)
    comp_orient = corr / max(tot, 1) if tot > 0 else 0
    print(f"\nComposition (GGM + LLM): recall={comp_recall:.3f} orient={comp_orient:.3f}")
    print(f"  LLM lift: orient={llm_orient:.3f} vs GGM={result.orientation_accuracy:.3f}")


if __name__ == "__main__":
    main()
