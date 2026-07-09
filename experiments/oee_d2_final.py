"""OEE D2 Final — real domains with mechanism-aware intervention generation.

Key difference from v2: interventions use generate_interventional_data which fits
OLS mechanisms from the discovered DAG and propagates intervention effects through
descendants. D2-guided (RecursiveGoalFormation) vs random vs oracle ancestor.

Run: PYTHONPATH=src python experiments/oee_d2_final.py
"""
from __future__ import annotations

import json, math, os, random, statistics, sys, time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.product_engine import ProductDiscoveryEngine
from aac.goal_formation import RecursiveGoalFormation
from aac.engine_upgrades import generate_interventional_data

OUT = Path(__file__).parent / "oee_d2_final.result.json"
SEEDS_PER = 6
N_ROUNDS = 10         # intervention rounds
ROWS_PER_ROUND = 4    # interventional rows per round


def generate_targeted_interventions(
    dag: frozenset,
    obs: list[list[float]],
    target_node: int,
    n_rows: int = 4,
    seed: int = 42,
) -> list[list[float]]:
    """Generate intervention rows targeting a specific node using fitted mechanisms."""
    n = len(obs[0])
    n_obs = len(obs)
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

    topo = list(range(n))
    indeg = {i: len([u for u, v in dag if v == i and v < n]) for i in range(n)}
    q = [i for i in range(n) if indeg[i] == 0]
    order = []
    while q:
        u = q.pop(0)
        order.append(u)
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
    do_values = [mu - 1.5 * sd, mu, mu + 1.5 * sd]
    for do_val in do_values:
        for _ in range(max(1, n_rows // 3)):
            row = [0.0] * n
            for j in order:
                if j == target_node:
                    row[j] = do_val
                    continue
                pa = parents[j]
                coef = coefs.get(j, [])
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


def run_d2(seed, condition, obs, true_edges, n_vars):
    rng = random.Random(seed)
    engine = ProductDiscoveryEngine(skeleton_tau=0.02, use_fast_orient=True)
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
            target = rng.randint(0, n_vars - 1)
            if len(int_data) >= ROWS_PER_ROUND:
                try:
                    engine2 = ProductDiscoveryEngine(skeleton_tau=0.02, use_fast_orient=True)
                    result2 = engine2.discover(obs + int_data)
                    organ = RecursiveGoalFormation(intervenable_nodes=set(range(n_vars)))
                    goals = organ.form_goals(result2.dag, obs + int_data, max_goals=1,
                                              demonstrated_only=False)
                    if goals and goals[0].leverage:
                        target = goals[0].leverage.ancestor
                except Exception:
                    pass
        else:  # control
            target = rng.randint(0, n_vars - 1)

        # Generate mechanism-aware intervention rows for the selected target
        try:
            engine3 = ProductDiscoveryEngine(skeleton_tau=0.02, use_fast_orient=True)
            result3 = engine3.discover(obs + int_data)
            new_rows = generate_targeted_interventions(
                result3.dag, obs + int_data, target,
                n_rows=ROWS_PER_ROUND, seed=seed + int(round_i * 10000 + len(int_data)),
            )
        except Exception:
            new_rows = []
            for _ in range(ROWS_PER_ROUND):
                row = [0.0] * n_vars
                row[target] = rng.uniform(-2, 2)
                new_rows.append(row)

        if new_rows:
            int_data.extend(new_rows)

            engine4 = ProductDiscoveryEngine(skeleton_tau=0.02, use_fast_orient=True)
            try:
                result4 = engine4.discover(obs + int_data)
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
        "n_true_edges": len(true_edges),
        "n_obs": len(obs),
        "n_int_rows": len(int_data),
    }


def generate_bnlearn_data(n_nodes, edges, n_obs, seed):
    rng = random.Random(seed)
    parents = {j: [] for j in range(n_nodes)}
    coefs = {}
    for u, v in edges:
        parents[v].append(u)
        coefs[(u, v)] = rng.uniform(0.4, 1.0) * rng.choice([1.0, -1.0])
    obs = []
    for _ in range(n_obs):
        row = [0.0] * n_nodes
        for j in range(n_nodes):
            val = rng.gauss(0, 0.4)
            if not parents[j]:
                val = rng.gauss(0, 1.5)
            for p in parents[j]:
                val += coefs[(p, j)] * row[p]
            row[j] = val
        obs.append(row)
    return obs


def main():
    results = []

    # Sachs — real protein-signaling data
    from experiments.sachs_task import load_obs, PROTEINS, GROUND_TRUTH
    sachs_obs = load_obs()
    sachs_edges = frozenset({(PROTEINS.index(a), PROTEINS.index(b)) for a, b in GROUND_TRUTH})
    print(f"Sachs: {len(sachs_obs)} obs, {len(PROTEINS)} vars, {len(sachs_edges)} true edges")
    for i in range(SEEDS_PER):
        for cond in ["treatment", "control", "oracle"]:
            seed_off = {"treatment": 3000, "control": 4000, "oracle": 5000}[cond]
            t0 = time.time()
            r = run_d2(seed_off + i, cond, sachs_obs, sachs_edges, 11)
            r["domain"] = "Sachs"
            r["time_s"] = round(time.time() - t0, 1)
            results.append(r)
            print(f"  Sachs/{cond} seed={i}: base={r['baseline_recall']:.3f} final={r['final_recall']:.3f}")

    # FinCARE — financial causal data
    from experiments.realworld_bench import generate_fincare_style
    fine_obs, _, fine_edges = generate_fincare_style(seed=99)
    print(f"\nFinCARE: {len(fine_obs)} obs, {len(fine_obs[0])} vars, {len(fine_edges)} true edges")
    for i in range(SEEDS_PER):
        for cond in ["treatment", "control", "oracle"]:
            seed_off = {"treatment": 6000, "control": 7000, "oracle": 8000}[cond]
            t0 = time.time()
            r = run_d2(seed_off + i, cond, fine_obs, fine_edges, len(fine_obs[0]))
            r["domain"] = "FinCARE"
            r["time_s"] = round(time.time() - t0, 1)
            results.append(r)
            print(f"  FinCARE/{cond} seed={i}: base={r['baseline_recall']:.3f} final={r['final_recall']:.3f}")

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
            print(f"{domain:10s}/{cond:10s}: rec={avg_rec:.3f} prec={avg_prec:.3f} max_rec={avg_max:.3f}")
        t = [r for r in results if r["domain"] == domain and r["condition"] == "treatment"]
        c = [r for r in results if r["domain"] == domain and r["condition"] == "control"]
        o = [r for r in results if r["domain"] == domain and r["condition"] == "oracle"]
        if t and c:
            tr = statistics.mean([r["final_recall"] for r in t])
            cr = statistics.mean([r["final_recall"] for r in c])
            tp = statistics.mean([r["final_precision"] for r in t])
            cp = statistics.mean([r["final_precision"] for r in c])
            print(f"  D2 vs control:   rec {tr - cr:+.3f}  prec {tp - cp:+.3f}")
        if t and o:
            tr = statistics.mean([r["final_recall"] for r in t])
            ore = statistics.mean([r["final_recall"] for r in o])
            tp = statistics.mean([r["final_precision"] for r in t])
            op = statistics.mean([r["final_precision"] for r in o])
            print(f"  D2 vs oracle:    rec {tr - ore:+.3f}  prec {tp - op:+.3f}")
        print()


if __name__ == "__main__":
    main()
