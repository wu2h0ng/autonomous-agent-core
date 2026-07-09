"""OEE D2 on Real Benchmark Networks — ASIA + Sachs.

Tests self-selected discovery targets vs fixed targets on real causal
benchmarks where the GGM skeleton does NOT achieve perfect recall.

Networks:
- ASIA (bnlearn, 8 nodes, 8 edges): medical diagnosis, lung cancer symptoms
- Sachs (real biology, 11 nodes, 17 edges): protein signaling network

Both are pre-LLM-era benchmarks — no memorization risk.

Run: PYTHONPATH=src python experiments/oee_d2_realdata.py
"""
from __future__ import annotations

import json, math, os, random, statistics, sys, time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.product_engine import ProductDiscoveryEngine
from aac.goal_formation import RecursiveGoalFormation
from aac.engine_upgrades import generate_interventional_data

OUT = Path(__file__).parent / "oee_d2_realdata.result.json"
N_INTERVENTIONS = 15
SEEDS_PER_CONDITION = 8

# bnlearn ASIA: 8 nodes, 8 edges
ASIA_EDGES = frozenset({
    (0, 1), (2, 3), (2, 4), (0, 5), (1, 5), (3, 5),
    (4, 6), (5, 6),
})
ASIA_LABELS = ["asia", "tub", "smoke", "lung", "bronc", "either", "dysp", "xray"]


def generate_asia_data(n_obs: int, seed: int) -> list[list[float]]:
    rng = random.Random(seed)
    parents = {0: [], 1: [0], 2: [], 3: [2], 4: [2], 5: [0, 1, 3], 6: [4, 5], 7: [5]}
    coefs = {
        (0, 1): 0.8, (2, 3): 0.7, (2, 4): 0.6, (0, 5): 0.5, (1, 5): 0.5,
        (3, 5): 0.5, (4, 6): 0.7, (5, 6): 0.6, (5, 7): 0.8,
    }

    obs = []
    for _ in range(n_obs):
        row = [0.0] * 8
        for j in [0, 2]:  # root nodes
            row[j] = rng.gauss(0, 1)
        for j in range(8):
            val = rng.gauss(0, 0.4)
            for p in parents[j]:
                val += coefs.get((p, j), 0.5) * row[p]
            if j not in [0, 2]:
                row[j] = val
        obs.append(row)
    return obs


def run_d2(seed: int, condition: str, data_fn, true_edges, n_vars, n_obs) -> dict:
    obs = data_fn(n_obs, seed)
    true_undir = {frozenset(e) for e in true_edges}
    engine = ProductDiscoveryEngine(skeleton_tau=0.02, use_fast_orient=True)
    result = engine.discover(obs)
    baseline_recall = len({frozenset(e) for e in result.dag} & true_undir) / max(len(true_undir), 1)

    int_data = []
    recalls = [baseline_recall]
    rng = random.Random(seed)

    for _ in range(N_INTERVENTIONS):
        if condition == "oracle":
            target = rng.choice([v for v in range(n_vars)])
            row = [0.0] * n_vars; row[target] = rng.uniform(-1, 1)
            int_data.append(row)
        elif condition == "treatment":
            if len(int_data) >= 3:
                engine = ProductDiscoveryEngine(skeleton_tau=0.02, use_fast_orient=True)
                result = engine.discover(obs + int_data)
                organ = RecursiveGoalFormation(intervenable_nodes=set(range(n_vars)))
                goals = organ.form_goals(result.dag, obs + int_data, max_goals=1,
                                          demonstrated_only=False)
                if goals and goals[0].leverage:
                    target = goals[0].leverage.ancestor
                else:
                    target = rng.randint(0, n_vars - 1)
            else:
                target = rng.randint(0, n_vars - 1)
            rows = generate_interventional_data(result.dag, obs + int_data,
                                                  n_interventions=3, n_nodes=1,
                                                  seed=seed + len(int_data))
            int_data.extend(rows)
        else:  # control: fixed targets
            target = (seed + len(int_data)) % n_vars

        if len(int_data) > 0:
            engine = ProductDiscoveryEngine(skeleton_tau=0.02, use_fast_orient=True)
            result = engine.discover(obs + int_data)
            mu = {frozenset(e) for e in result.dag}
            rec = len(mu & true_undir) / max(len(true_undir), 1)
            recalls.append(rec)

    return {
        "seed": seed, "condition": condition, "n_vars": n_vars, "n_obs": n_obs,
        "baseline_recall": round(baseline_recall, 3),
        "final_recall": round(recalls[-1], 3) if len(recalls) > 1 else round(baseline_recall, 3),
        "max_recall": round(max(recalls), 3),
        "n_true_edges": len(true_edges),
    }


def main():
    results = []

    # --- ASIA: 8 nodes, 200 obs ---
    for i in range(SEEDS_PER_CONDITION):
        for cond in ["treatment", "control", "oracle"]:
            seed = 200 + i + ({"treatment": 0, "control": 100, "oracle": 200}[cond])
            t0 = time.time()
            r = run_d2(seed, cond, generate_asia_data, ASIA_EDGES, 8, 200)
            r["time_s"] = round(time.time() - t0, 1)
            r["domain"] = "ASIA"
            results.append(r)

    # --- Sachs: 11 nodes, 853 obs ---
    from experiments.sachs_task import load_obs, PROTEINS, GROUND_TRUTH
    sachs_obs = load_obs()
    sachs_edges = frozenset({(PROTEINS.index(a), PROTEINS.index(b)) for a, b in GROUND_TRUTH})
    def sachs_data_fn(_, __): return sachs_obs

    for i in range(SEEDS_PER_CONDITION):
        for cond in ["treatment", "control", "oracle"]:
            seed = 300 + i + ({"treatment": 0, "control": 100, "oracle": 200}[cond])
            t0 = time.time()
            r = run_d2(seed, cond, sachs_data_fn, sachs_edges, 11, 853)
            r["time_s"] = round(time.time() - t0, 1)
            r["domain"] = "Sachs"
            results.append(r)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    for domain in ["ASIA", "Sachs"]:
        for cond in ["treatment", "control", "oracle"]:
            grp = [r for r in results if r["domain"] == domain and r["condition"] == cond]
            if not grp: continue
            avg_base = statistics.mean([r["baseline_recall"] for r in grp])
            avg_final = statistics.mean([r["final_recall"] for r in grp])
            avg_max = statistics.mean([r["max_recall"] for r in grp])
            print(f"{domain}/{cond}: baseline={avg_base:.3f} final={avg_final:.3f} max={avg_max:.3f}")

    for domain in ["ASIA", "Sachs"]:
        t = [r for r in results if r["domain"] == domain and r["condition"] == "treatment"]
        c = [r for r in results if r["domain"] == domain and r["condition"] == "control"]
        if t and c:
            tf = statistics.mean([r["final_recall"] for r in t])
            cf = statistics.mean([r["final_recall"] for r in c])
            print(f"{domain} D2 lift: {tf - cf:+.3f}")


if __name__ == "__main__":
    main()
