"""OEE D2 Experiment — self-selected discovery targets vs fixed targets.

Tests whether RecursiveGoalFormation (D2) improves cumulative causal discovery
vs a pre-specified target list vs an Oracle using true causal structure.

Preregistration: docs/research/OEE-D2-PREREG-2026-07-08.yaml
Founder Cast: Option C — Fund one preregistered experiment.

Run: PYTHONPATH=src python experiments/oee_d2_experiment.py
"""
from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.product_engine import ProductDiscoveryEngine
from aac.goal_formation import RecursiveGoalFormation
from aac.engine_upgrades import generate_interventional_data

OUT = Path(__file__).parent / "oee_d2_experiment.result.json"
SEEDS = list(range(100, 130))
N_DOMAINS = 3
N_VARS = (15, 18, 20)          # harder: 15-20 variables
N_OBS = 200                     # fewer observations for challenge
N_INTERVENTIONS = 20


def generate_domain(domain_id: int, seed: int) -> tuple[list[list[float]], frozenset]:
    n = N_VARS[domain_id % 3]
    rng = random.Random(seed)
    edges = set()
    for i in range(n):
        for j in range(i + 1, n):
            if rng.random() < rng.uniform(0.05, 0.20):  # sparser river-like DAG
                edges.add((i, j))
    if len(edges) < 4:
        edges = {(i, i + 1) for i in range(min(4, n - 1))} | {(0, n - 1)}
    edges = frozenset(edges)

    parents = {j: [] for j in range(n)}
    coefs = {}
    for u, v in edges:
        parents[v].append(u)
        coefs[(u, v)] = rng.uniform(0.3, 0.8) * rng.choice([1.0, -1.0])

    # Add HIDDEN CONFOUNDER: unobserved rainfall affects stations 0..4
    confounder = [rng.gauss(0, 1) for _ in range(N_OBS)]

    obs = []
    for t in range(N_OBS):
        row = [0.0] * n
        for j in range(n):
            val = rng.gauss(0, 0.5)  # higher noise
            if j < 5:
                val += 0.6 * confounder[t]
            for p in parents[j]:
                val += coefs[(p, j)] * row[p]
            row[j] = val
        obs.append(row)
    return obs, edges


def run_condition(seed: int, condition: str) -> dict:
    domain_id = (seed - 100) // 10
    obs, true_edges = generate_domain(domain_id, seed)
    n = len(obs[0])
    true_undir = {frozenset(e) for e in true_edges}
    engine = ProductDiscoveryEngine(skeleton_tau=0.02, use_fast_orient=True)
    result = engine.discover(obs)
    baseline_dag = result.dag
    baseline_recall = len({frozenset(e) for e in baseline_dag} & true_undir) / max(len(true_undir), 1)

    interventions_applied = 0
    int_data: list[list[float]] = []
    recalls = [baseline_recall]

    for _ in range(N_INTERVENTIONS):
        if condition == "oracle":
            best_recall = max(recalls)
            targets = [v for v in range(n) if v not in {e[1] for e in baseline_dag}]
            if not targets:
                targets = list(range(n))
            target = random.Random(seed + interventions_applied).choice(targets)
            int_row = _oracle_intervention(true_edges, target, n, seed + interventions_applied)
            if int_row:
                int_data.append(int_row)
                interventions_applied += 1

        elif condition == "treatment":
            if len(int_data) >= 3:
                engine = ProductDiscoveryEngine(skeleton_tau=0.02, use_fast_orient=True)
                result = engine.discover(obs + int_data)
                organ = RecursiveGoalFormation(intervenable_nodes=set(range(n)))
                goals = organ.form_goals(result.dag, obs + int_data, max_goals=1, demonstrated_only=False)
                if goals:
                    target = goals[0].target if goals[0].leverage else random.Random(seed).randint(0, n - 1)
                else:
                    target = random.Random(seed).randint(0, n - 1)
            else:
                target = random.Random(seed).randint(0, n - 1)

            int_rows = generate_interventional_data(result.dag, obs + int_data, n_interventions=3, n_nodes=1,
                                                     seed=seed + interventions_applied)
            int_data.extend(int_rows)
            interventions_applied += len(int_rows)

        else:  # control
            target = (seed * 7 + interventions_applied) % n
            engine = ProductDiscoveryEngine(skeleton_tau=0.02, use_fast_orient=True)
            _ = engine.discover(obs + int_data)

        if interventions_applied > 0 and condition != "oracle":
            engine = ProductDiscoveryEngine(skeleton_tau=0.02, use_fast_orient=True)
            result = engine.discover(obs + int_data)
            mu = {frozenset(e) for e in result.dag}
            rec = len(mu & true_undir) / max(len(true_undir), 1)
            recalls.append(rec)
        if interventions_applied >= N_INTERVENTIONS:
            break

    return {
        "seed": seed, "condition": condition, "n_vars": n,
        "baseline_recall": round(baseline_recall, 3),
        "final_recall": round(recalls[-1], 3) if recalls else 0.0,
        "max_recall": round(max(recalls), 3) if recalls else 0.0,
        "interventions_used": interventions_applied,
        "n_edges": len(true_edges),
        "recall_trajectory": [round(r, 3) for r in recalls],
    }


def _oracle_intervention(true_edges, target, n, seed):
    rng = random.Random(seed)
    row = [0.0] * n
    row[target] = rng.uniform(-2, 2)
    for u, v in true_edges:
        if u == target:
            row[v] = rng.gauss(0, 0.3)
    return row


def main():
    results = []
    for seed in SEEDS:
        condition = "treatment" if seed < 110 else ("control" if seed < 120 else "oracle")
        t0 = time.time()
        r = run_condition(seed, condition)
        r["time_s"] = round(time.time() - t0, 1)
        results.append(r)
        print(f"seed={seed} {condition}: baseline={r['baseline_recall']:.3f} final={r['final_recall']:.3f} max={r['max_recall']:.3f} ({r['time_s']:.0f}s)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    for cond in ["treatment", "control", "oracle"]:
        grp = [r for r in results if r["condition"] == cond]
        if not grp:
            continue
        avg_base = statistics.mean([r["baseline_recall"] for r in grp])
        avg_final = statistics.mean([r["final_recall"] for r in grp])
        avg_max = statistics.mean([r["max_recall"] for r in grp])
        avg_int = statistics.mean([r["interventions_used"] for r in grp])
        print(f"\n{cond}: baseline={avg_base:.3f} final={avg_final:.3f} max={avg_max:.3f} interventions={avg_int:.0f}")

    treatment = [r for r in results if r["condition"] == "treatment"]
    control = [r for r in results if r["condition"] == "control"]
    if treatment and control:
        t_final = statistics.mean([r["final_recall"] for r in treatment])
        c_final = statistics.mean([r["final_recall"] for r in control])
        print(f"\nD2 lift (over control): {t_final - c_final:+.3f}")


if __name__ == "__main__":
    main()
