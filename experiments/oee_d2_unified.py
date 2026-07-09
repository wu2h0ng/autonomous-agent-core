"""OEE D2 — Unified Pipeline: CI auto-selection + HSIC + FCI + EIG + LLM.

Runs Sachs + FinCARE through the full UnifiedDiscoveryEngine pipeline.
Compares D2-guided (EIG + GoalFormation) vs random vs oracle interventions.

Run: PYTHONPATH=src python experiments/oee_d2_unified.py
"""
from __future__ import annotations

import json, math, os, random, statistics, sys, time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.unified_engine import UnifiedDiscoveryEngine
from aac.goal_formation import RecursiveGoalFormation
from aac.engine_upgrades import generate_interventional_data

OUT = Path(__file__).parent / "oee_d2_unified.result.json"
SEEDS_PER = 1
N_ROUNDS = 4
ROWS_PER_ROUND = 15
ROWS_PER_ROUND = 4


def generate_targeted_interventions(dag, obs, target_node, n_rows=4, seed=42):
    n = len(obs[0]); n_obs = len(obs)
    if n_obs < 10:
        return []
    rng = random.Random(seed)
    parents = {j: [] for j in range(n)}
    for u, v in dag:
        if v < n:
            parents[v].append(u)
    coefs = {}
    for j in range(n):
        pa = parents[j]
        if pa:
            X = [[obs[t][p] for p in pa] for t in range(n_obs)]
            y = [obs[t][j] for t in range(n_obs)]
            from aac.bayesian_dag_posterior import _ols_coefficients
            try:
                coefs[j] = _ols_coefficients(X, y)
            except (ValueError, ZeroDivisionError):
                coefs[j] = []
        else:
            coefs[j] = []
    indeg = {i: len([u for u, v in dag if v == i and v < n]) for i in range(n)}
    q = [i for i in range(n) if indeg[i] == 0]
    order = []
    while q:
        u = q.pop(0); order.append(u)
        for v in [v for u2, v in dag if u2 == u and v < n]:
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    if len(order) < n:
        order = list(range(n))
    col_k = [obs[t][target_node] for t in range(n_obs)]
    mu = statistics.mean(col_k)
    sd = statistics.pstdev(col_k) or 1.0
    baseline_means = [statistics.mean([obs[t][v] for t in range(n_obs)]) for v in range(n)]
    int_rows = []
    for do_val in [mu - 1.5 * sd, mu, mu + 1.5 * sd]:
        for _ in range(max(1, n_rows // 3)):
            row = [0.0] * n
            for j in order:
                if j == target_node:
                    row[j] = do_val; continue
                pa = parents[j]; coef = coefs.get(j, [])
                if coef and len(coef) == len(pa) and all(p < n for p in pa):
                    row[j] = sum(coef[pi] * row[p] for pi, p in enumerate(pa))
                    row[j] += rng.gauss(0, 0.12 * max(abs(row[j]), 1.0))
                else:
                    row[j] = baseline_means[j] + rng.gauss(0, 0.3 * max(abs(baseline_means[j]), 1.0))
            int_rows.append(row)
    return int_rows


def evaluate(dag, true_edges):
    mu = {frozenset(e) for e in dag}
    tu = {frozenset(e) for e in true_edges}
    rec = len(mu & tu) / max(len(tu), 1)
    prec = len(mu & tu) / max(len(mu), 1)
    return rec, prec


def run_d2(seed, condition, obs, true_edges, n_vars, variable_names=None):
    rng = random.Random(seed)
    engine = UnifiedDiscoveryEngine(
        pipeline_mode="full",
        use_hsic=True, use_fci=True,
        variable_names=variable_names or [],
    )
    try:
        result = engine.discover(obs)
    except Exception:
        return {"seed": seed, "condition": condition, "n_vars": n_vars,
                "baseline_recall": 0.0, "baseline_precision": 0.0,
                "final_recall": 0.0, "final_precision": 0.0,
                "max_recall": 0.0, "n_true_edges": len(true_edges), "n_obs": len(obs),
                "n_int_rows": 0}
    base_rec, base_prec = evaluate(result.dag, true_edges)
    int_data = []
    recalls = [base_rec]
    precs = [base_prec]

    for round_i in range(N_ROUNDS):
        if condition == "oracle":
            ancestors = sorted({e[0] for e in true_edges})
            target = rng.choice(ancestors) if ancestors else rng.randint(0, n_vars - 1)
        elif condition == "treatment":
            target, reason = engine.select_uncertainty_driven_target(obs, int_data)
            if target is None:
                target = rng.randint(0, n_vars - 1)
        else:  # control
            target = rng.randint(0, n_vars - 1)

        # Hard do-interventions: set target value, no downstream propagation
        col_t = [obs[t][target] for t in range(len(obs))]
        mu = statistics.mean(col_t); sd = statistics.pstdev(col_t) or 1.0
        new_rows = []
        do_vals = [mu - 2.5*sd, mu - 1.0*sd, mu, mu + 1.0*sd, mu + 2.5*sd]
        for dv in do_vals:
            for _ in range(ROWS_PER_ROUND // len(do_vals)):
                row = [0.0] * n_vars
                row[target] = dv + rng.gauss(0, 0.05 * sd)
                new_rows.append(row)
        int_data.extend(new_rows)

        try:
            result4 = engine.discover(obs + int_data)
            rec, prec = evaluate(result4.dag, true_edges)
        except Exception:
            rec, prec = (recalls[-1], precs[-1])
        recalls.append(rec)
        precs.append(prec)

    return {
        "seed": seed, "condition": condition, "n_vars": n_vars,
        "baseline_recall": round(base_rec, 3),
        "baseline_precision": round(base_prec, 3),
        "final_recall": round(recalls[-1], 3) if len(recalls) > 1 else round(base_rec, 3),
        "final_precision": round(precs[-1], 3) if len(precs) > 1 else round(base_prec, 3),
        "max_recall": round(max(recalls), 3),
        "n_true_edges": len(true_edges), "n_obs": len(obs),
        "n_int_rows": len(int_data),
    }


def main():
    results = []

    from experiments.sachs_task import load_obs, PROTEINS, GROUND_TRUTH
    sachs_obs = load_obs()
    sachs_edges = frozenset({(PROTEINS.index(a), PROTEINS.index(b)) for a, b in GROUND_TRUTH})
    print(f"Sachs: {len(sachs_obs)} obs, {len(PROTEINS)} vars, {len(sachs_edges)} true edges")
    for i in range(SEEDS_PER):
        for cond in ["treatment", "control", "oracle"]:
            seed_off = {"treatment": 0, "control": 100, "oracle": 200}[cond]
            t0 = time.time()
            r = run_d2(seed_off + i, cond, sachs_obs, sachs_edges, 11, variable_names=PROTEINS)
            r["domain"] = "Sachs"; r["time_s"] = round(time.time() - t0, 1)
            results.append(r)
            print(f"  Sachs/{cond:10s} s{i}: base={r['baseline_recall']:.3f} final={r['final_recall']:.3f} t={r['time_s']:.0f}s")

    from experiments.realworld_bench import generate_fincare_style
    fine_obs, _, fine_edges = generate_fincare_style(seed=99)
    fine_n = len(fine_obs[0])
    print(f"\nFinCARE: {len(fine_obs)} obs, {fine_n} vars, {len(fine_edges)} true edges")
    for i in range(SEEDS_PER):
        for cond in ["treatment", "control", "oracle"]:
            seed_off = {"treatment": 300, "control": 400, "oracle": 500}[cond]
            t0 = time.time()
            r = run_d2(seed_off + i, cond, fine_obs, fine_edges, fine_n)
            r["domain"] = "FinCARE"; r["time_s"] = round(time.time() - t0, 1)
            results.append(r)
            print(f"  FinCARE/{cond:10s} s{i}: base={r['baseline_recall']:.3f} final={r['final_recall']:.3f} t={r['time_s']:.0f}s")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    print("\n=== SUMMARY ===\n")
    for domain in sorted(set(r["domain"] for r in results)):
        for cond in ["treatment", "control", "oracle"]:
            grp = [r for r in results if r["domain"] == domain and r["condition"] == cond]
            if not grp:
                continue
            avg_rec = statistics.mean([r["final_recall"] for r in grp])
            avg_prec = statistics.mean([r["final_precision"] for r in grp])
            avg_max = statistics.mean([r["max_recall"] for r in grp])
            avg_t = statistics.mean([r["time_s"] for r in grp])
            print(f"{domain:10s}/{cond:10s}: rec={avg_rec:.3f} prec={avg_prec:.3f} max_rec={avg_max:.3f} t={avg_t:.0f}s")
        t = [r for r in results if r["domain"] == domain and r["condition"] == "treatment"]
        c = [r for r in results if r["domain"] == domain and r["condition"] == "control"]
        o = [r for r in results if r["domain"] == domain and r["condition"] == "oracle"]
        if t and c:
            tr = statistics.mean([r["final_recall"] for r in t])
            cr = statistics.mean([r["final_recall"] for r in c])
            print(f"  D2 vs control: rec {tr - cr:+.3f}")
        if t and o:
            tr = statistics.mean([r["final_recall"] for r in t])
            orec = statistics.mean([r["final_recall"] for r in o])
            print(f"  D2 vs oracle:  rec {tr - orec:+.3f}")
        print()


if __name__ == "__main__":
    main()
