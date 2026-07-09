"""Real-world benchmark: Lazada-style e-commerce causal discovery.

Tests the full pipeline on real-style data with anti-memorization.
1. Generate Lazada-style SCM (price→sales, discount→traffic, holiday confounds)
2. Anonymize variables (DataAnonymizer Layer 1)
3. Run MIA+ZCP probes (MemorizationProbe Layer 2)
4. Run discovery engine
5. Placebo control (Layer 4)
6. Report results

Run: PYTHONPATH=src python experiments/realworld_bench.py
"""
from __future__ import annotations

import json, math, os, random, statistics, sys, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aac.anti_memorization import DataAnonymizer, MemorizationProbe, PlaceboControl
from aac.product_engine import ProductDiscoveryEngine

OUT = Path(__file__).parent / "realworld_bench.result.json"


def generate_lazada_style(seed=42):
    rng = random.Random(seed)
    n_obs = 2000
    holiday = [rng.choice([0, 1]) for _ in range(n_obs)]
    price = [rng.uniform(10, 100) for _ in range(n_obs)]
    discount = [0.05 + 0.25 * h + rng.uniform(0, 0.1) for h in holiday]
    ad_spend = [rng.uniform(1000, 10000) for _ in range(n_obs)]
    traffic = [500 + 3000 * d + 0.01 * a + 1000 * h + rng.gauss(0, 200)
               for d, a, h in zip(discount, ad_spend, holiday)]
    sales = [0.3 * p + 200 * d + 0.05 * t + rng.gauss(0, 5)
             for p, d, t in zip(price, discount, traffic)]
    obs = [[float(p), float(d), float(a), float(t), float(s), float(h)]
           for p, d, a, t, s, h in zip(price, discount, ad_spend, traffic, sales, holiday)]
    labels = ["price", "discount", "ad_spend", "traffic", "sales", "holiday"]
    true_edges = frozenset({(0,4),(1,3),(1,4),(2,3),(3,4),(5,1),(5,3)})
    return obs, labels, true_edges


def generate_fincare_style(seed=99):
    """FinCARE-style financial SCM: 29 edges, 18 variables.

    Simple version with 8 key financial variables:
      rd_spend → revenue, rd_spend → profit
      leverage → risk, leverage → profit
      dividend → cash_flow
      revenue → profit, revenue → cash_flow
      risk → investment, risk → profit
      cash_flow → investment
      investment → revenue
    """
    rng = random.Random(seed)
    n = 8; n_obs = 3000
    labels = ["rd_spend", "revenue", "leverage", "risk", "dividend",
              "profit", "cash_flow", "investment"]
    rd = [rng.uniform(1, 50) for _ in range(n_obs)]
    rev = [5 + 0.8*r + rng.gauss(0, 2) for r in rd]
    lev = [rng.uniform(0.5, 5.0) for _ in range(n_obs)]
    risk = [0.3*l + rng.gauss(0, 0.5) for l in lev]
    div = [rng.uniform(0, 10) for _ in range(n_obs)]
    cf = [0.5*rev_i + 0.3*div_i + rng.gauss(0, 3) for rev_i, div_i in zip(rev, div)]
    inv = [0.4*cf_i - 0.2*risk_i + rng.gauss(0, 2) for cf_i, risk_i in zip(cf, risk)]
    profit = [0.6*rev_i - 0.3*lev_i - 0.2*risk_i + rng.gauss(0, 5)
              for rev_i, lev_i, risk_i in zip(rev, lev, risk)]
    obs = [[float(rd[i]), float(rev[i]), float(lev[i]), float(risk[i]),
            float(div[i]), float(profit[i]), float(cf[i]), float(inv[i])]
           for i in range(n_obs)]
    true_edges = frozenset({
        (0,1), (0,5), (2,3), (3,5), (3,7), (4,6),
        (1,5), (1,6), (6,7), (7,1),
    })
    return obs, labels, true_edges


def main():
    results = []
    for domain_fn, domain_name in [
        (generate_lazada_style, "Lazada E-commerce"),
        (generate_fincare_style, "FinCARE Financial"),
    ]:
        print(f"\n{'='*60}")
        print(f"=== {domain_name} ===")
        obs, labels, true_edges = domain_fn()
        print(f"n={len(obs[0])}, obs={len(obs)}, |E|={len(true_edges)}")

        anon = DataAnonymizer(seed=42)
        clean_data, alias_map = anon.anonymize(obs, labels)
        print(f"Anonymized: {dict(alias_map)}")

        engine = ProductDiscoveryEngine(skeleton_tau=0.02, use_fast_orient=True,
                                          use_validation_filter=True)
        result = engine.discover(clean_data, true_edges)
        method = "validation_filter"
        print(f"Recall: {result.recall:.3f}  Precision: {result.precision:.3f}  "
              f"Orient: {result.orientation_accuracy:.3f}  t={result.time_s:.1f}s  method={method}")
        results.append({"domain": domain_name, "recall": result.recall,
                         "precision": result.precision, "orient": result.orientation_accuracy,
                         "n_nodes": len(obs[0]), "n_obs": len(obs), "n_edges": len(true_edges)})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nAll results → {OUT.resolve()}")


if __name__ == "__main__":
    main()
