"""CWM-LEARN-3 independent adversarial verification (post-scored, on FRESH seeds 200-219 held out of both
calibration [50-79] and the scored window [0-9]). Probes whether a MET is a real invariance-in-representation
win rather than an artifact of an under-powered baseline or a lucky mag_floor:

  V1 FAIR-BASELINE STRESS: give the capacity-matched pooled baseline STRONGER l2 (better regularisation) and
     more epochs. If a better-regularised SAME-phi pooled model closes Δ_B, the 'not capacity' claim weakens.
  V2 MAG_FLOOR ROBUSTNESS: re-run our arm at mag_floor in {0.10, 0.20, 0.25}. If the win only exists at the
     frozen 0.15, it is fragile / floor-shopped.
  V3 FRESH-SEED REPLICATION: Δ_A and Δ_B on unseen seeds 200-219 (neither calibration nor scored).
  V4 ATTRIBUTION on fresh seeds: interaction coord load-bearing; retained spurious not load-bearing.

Reports raw numbers; does NOT cast a verdict (author != adjudicator). Uses the frozen generator + mechanism.
"""
from __future__ import annotations

import json
import statistics

import experiments.synthetic_scm_interaction as scm
from aac.interaction_cwm import InteractionCWM, product_index
from aac.learned_cwm import LearnedCWM

FRESH = list(range(200, 220))


def _m(xs):
    return statistics.mean(xs)


def main():
    n_raw = scm.N_FEATURES
    xor_k = product_index(n_raw, *scm.INTERACTION_PAIR)
    spur_coords = {product_index(n_raw, i, j) for i in scm.SPURIOUS_IDX for j in range(n_raw) if j != i}

    base = InteractionCWM()
    # V1: stronger-regularised / longer-trained capacity-matched pooled baselines (same phi)
    strong = [InteractionCWM(l2=1e-2, epochs=300), InteractionCWM(l2=5e-2, epochs=300),
              InteractionCWM(l2=1e-1, epochs=400)]

    inv, cap, linv = [], [], []
    cap_strong = {i: [] for i in range(len(strong))}
    xor_collapse, spur_help = [], []
    lin = LearnedCWM()
    for s in FRESH:
        tr = scm.train_envs_l3(s)
        rows, labels = scm.test_env_l3(s)
        full, kept = base.invariant_interaction_auc(tr, rows, labels, seed=s, mode="inv_interaction", return_kept=True)
        inv.append(full)
        cap.append(base.invariant_interaction_auc(tr, rows, labels, seed=s, mode="cap_pooled"))
        linv.append(lin.invariant_predict_auc(tr, rows, labels, seed=s, mode="invariant"))
        for i, m in enumerate(strong):
            cap_strong[i].append(m.invariant_interaction_auc(tr, rows, labels, seed=s, mode="cap_pooled"))
        if xor_k in kept:
            xor_collapse.append(full - base.invariant_interaction_auc(tr, rows, labels, seed=s, drop_coords=(xor_k,)))
        rs = tuple(k for k in kept if k in spur_coords)
        if rs:
            spur_help.append(base.invariant_interaction_auc(tr, rows, labels, seed=s, drop_coords=rs) - full)

    # V2: mag_floor robustness
    floor_res = {}
    for mf in (0.10, 0.20, 0.25):
        m = InteractionCWM()
        m.mag_floor = mf
        vals = []
        for s in FRESH:
            tr = scm.train_envs_l3(s)
            rows, labels = scm.test_env_l3(s)
            vals.append(m.invariant_interaction_auc(tr, rows, labels, seed=s, mode="inv_interaction"))
        floor_res[f"mag_floor_{mf}"] = {"inv_mean": round(_m(vals), 4),
                                        "delta_B_vs_frozen_cap": round(_m(vals) - _m(cap), 4)}

    res = {
        "fresh_seeds": FRESH,
        "V3_fresh_replication": {
            "inv_interaction_mean": round(_m(inv), 4),
            "cap_pooled_mean": round(_m(cap), 4),
            "linear_invariance_mean": round(_m(linv), 4),
            "delta_A_vs_linear_invariance": round(_m(inv) - _m(linv), 4),
            "delta_B_vs_cap_pooled": round(_m(inv) - _m(cap), 4),
        },
        "V1_fair_baseline_stress": {
            f"cap_l2={m.l2}_ep={m.epochs}": {"mean": round(_m(cap_strong[i]), 4),
                                             "delta_B_ours_minus_this": round(_m(inv) - _m(cap_strong[i]), 4)}
            for i, m in enumerate(strong)
        },
        "V2_mag_floor_robustness": floor_res,
        "V4_attribution": {
            "xor_collapse_mean": round(_m(xor_collapse), 4) if xor_collapse else None,
            "spurious_help_max": round(max(spur_help), 4) if spur_help else 0.0,
        },
    }
    out = "experiments/cwm_learn_3_verify.result.json"
    with open(out, "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res, indent=2))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
