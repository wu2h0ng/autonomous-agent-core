"""CWM-LEARN-5e degradation-regime PILOT (pre-freeze calibration; design §2 regime check).

Question (compute-only, no LLM): at n_raw=60 (1,830 cross2 coordinates vs 400 samples/env), does exhaustive
enumeration + invariance selection DEGRADE relative to the oracle candidate set? The design requires this
regime to be CONFIRMED before the 5e gate freezes (else escalate n_raw to 100 pre-freeze).

Arms (identical verifier = InvariantStructureFilter; pilot seeds 100-102, disjoint from any scored set):
  exhaustive — basis="cross2" on the 60 raw features (1,830 coords)
  oracle     — raw rows pre-expanded with ONLY the 4 true pairs, basis="raw" (64 coords)
Regime CONFIRMED iff median normalized score s_exh = (AUC-0.5)/(AUC_oracle-0.5) <= 0.6 OR found=False in
>= half the pilot seeds. Result feeds the 5e prereg; never re-run post-freeze.
"""
from __future__ import annotations

import json
import statistics
import time

import experiments.synthetic_scm_highdim as hd
from aac.invariant_structure import InvariantStructureFilter, NoInvariantStructure

PILOT_SEEDS = [100, 101, 102]


def main():
    out = {"pilot_seeds": PILOT_SEEDS, "per_seed": []}
    for s in PILOT_SEEDS:
        t0 = time.time()
        tr = hd.train_envs_hd(s)
        teX, teY = hd.test_env_hd(s)

        oracle_f = InvariantStructureFilter(basis="raw")
        tr_o = [(hd.expand_pairs(X, hd.HD_PARAMS["true_pairs"]), Y) for X, Y in tr]
        m_o = oracle_f.fit(tr_o, seed=s)
        auc_o = m_o.score_auc(hd.expand_pairs(teX, hd.HD_PARAMS["true_pairs"]), teY) if m_o.found else 0.5

        exh_f = InvariantStructureFilter(basis="cross2")
        m_e = exh_f.fit(tr, seed=s)
        if m_e.found:
            auc_e = m_e.score_auc(teX, teY)
            n_kept = len(m_e.kept)
        else:
            auc_e, n_kept = 0.5, 0

        s_norm = (auc_e - 0.5) / (auc_o - 0.5) if auc_o > 0.5 else 0.0
        rec = {"seed": s, "oracle_auc": round(auc_o, 4), "exhaustive_auc": round(auc_e, 4),
               "exhaustive_found": m_e.found, "exhaustive_kept_n": n_kept,
               "normalized_score": round(s_norm, 4), "minutes": round((time.time() - t0) / 60, 1)}
        out["per_seed"].append(rec)
        print(json.dumps(rec))

    scores = [r["normalized_score"] for r in out["per_seed"]]
    not_found = sum(1 for r in out["per_seed"] if not r["exhaustive_found"])
    out["median_normalized"] = round(statistics.median(scores), 4)
    out["regime_confirmed"] = bool(out["median_normalized"] <= 0.6 or not_found * 2 >= len(PILOT_SEEDS))
    out["action"] = ("FREEZE 5e at n_raw=60" if out["regime_confirmed"]
                     else "ESCALATE to n_raw=100 pre-freeze (design §2)")
    with open("experiments/cwm_learn_5e_pilot.result.json", "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps({k: v for k, v in out.items() if k != "per_seed"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
