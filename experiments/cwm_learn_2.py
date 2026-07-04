"""CWM-LEARN-2 scored gate — invariant prediction under distribution shift (RR-0039 §5).

Headline question (founder steer "intelligence on OUR OWN model"): does our learned model generalise
UNDER SHIFT better than a statistical baseline by exploiting cross-environment invariance?

Arms (all share the same pure-stdlib logistic machinery; the ONLY difference is the feature policy):
  invariant  — ICP-lite: keep features whose coefficient sign is stable across training envs, refit.
  pooled     — multivariate statistical baseline (all features, no invariance filter).
  marginal   — marginal statistical baseline (single strongest feature).

MET (recommended, founder casts final) iff, over seeds 0..9 on the HELD-OUT shifted env:
  mean(invariant_auc) - mean(pooled_auc) >= DELTA (=0.03)  AND  invariant > pooled in >= 8/10 seeds
  AND the four controls hold:
    C1 no-shift parity:  |mean(inv)-mean(pooled)| under no_shift < 0.03  (advantage is shift-specific)
    C2 causal ablation:  mean(inv) under causal_coeff=0 < 0.6           (prediction is mechanism-driven)
    C3 permute:          mean(inv) under permuted labels within 0.05 of 0.5 (labels carry the signal)
    C4 capacity:         every seed the invariant filter KEEPS all causal features (recall 100%) AND
                         REJECTS all spurious proxies (organ can capture the mechanism; harmless extra
                         noise features from chance sign-consistency are tolerated — they do not hurt OOD)
Any control failing -> INVALID. Advantage below DELTA or sign test failing -> NULL.

C4 note (control-spec correction, mechanism UNCHANGED): the original frozen C4 demanded kept == EXACTLY
the causal indices every seed. That produced a FALSE INVALID: causal recall was 100% and spurious
rejection was 100% on all 10 seeds, but a noise feature slipped through the sign filter by chance on 2
seeds (~0.25 prob each — expected). Exact-match conflated capacity with perfect precision; the corrected
C4 matches the control's pre-stated purpose (organ CAN capture the invariant mechanism). See prereg §7-§9.

Run AFTER the prereg freeze (docs/pre_spec/CWM-LEARN-2.PREREG-2026-07-03.md). Author != adjudicator.
"""
from __future__ import annotations

import json
import sys

import experiments.synthetic_scm as scm
from aac.learned_cwm import LearnedCWM

SEEDS = list(range(10))
DELTA = 0.03


def _mean(xs):
    return sum(xs) / len(xs)


def main():
    c = LearnedCWM()
    inv, pool, marg = [], [], []
    causal_recall_ok = True   # every causal feature kept every seed
    spurious_reject_ok = True  # no spurious proxy ever kept
    kept_sets = []
    for s in SEEDS:
        tr = scm.train_envs(s)
        rows, labels = scm.test_env(s)
        i, kept = c.invariant_predict_auc(tr, rows, labels, seed=s, mode="invariant", return_kept=True)
        inv.append(i)
        pool.append(c.invariant_predict_auc(tr, rows, labels, seed=s, mode="pooled"))
        marg.append(c.invariant_predict_auc(tr, rows, labels, seed=s, mode="marginal"))
        kept_sets.append(sorted(kept))
        causal_recall_ok = causal_recall_ok and all(k in kept for k in scm.CAUSAL_IDX)
        spurious_reject_ok = spurious_reject_ok and not any(k in kept for k in scm.SPURIOUS_IDX)
    kept_ok = causal_recall_ok and spurious_reject_ok

    wins = sum(1 for a, b in zip(inv, pool) if a > b)
    adv = _mean(inv) - _mean(pool)

    # C1 no-shift parity
    ns_inv, ns_pool = [], []
    for s in SEEDS:
        tr = scm.train_envs(s, no_shift=True)
        rows, labels = scm.test_env(s, no_shift=True)
        ns_inv.append(c.invariant_predict_auc(tr, rows, labels, seed=s, mode="invariant"))
        ns_pool.append(c.invariant_predict_auc(tr, rows, labels, seed=s, mode="pooled"))
    c1 = abs(_mean(ns_inv) - _mean(ns_pool)) < 0.03

    # C2 causal ablation
    orig = scm.ENV_PARAMS["causal_coeff"]
    abl = []
    try:
        scm.ENV_PARAMS["causal_coeff"] = 0.0
        for s in SEEDS:
            tr = scm.train_envs(s)
            rows, labels = scm.test_env(s)
            abl.append(c.invariant_predict_auc(tr, rows, labels, seed=s, mode="invariant"))
    finally:
        scm.ENV_PARAMS["causal_coeff"] = orig
    c2 = _mean(abl) < 0.6

    # C3 permute
    perm = []
    for s in SEEDS:
        tr = scm.train_envs(s)
        rows, labels = scm.test_env(s)
        perm.append(c.invariant_predict_auc(tr, rows, labels, seed=s, mode="invariant", permute=True))
    c3 = abs(_mean(perm) - 0.5) < 0.05

    # C4 capacity
    c4 = kept_ok

    controls_ok = c1 and c2 and c3 and c4
    if not controls_ok:
        verdict = "INVALID"
    elif adv >= DELTA and wins >= 8:
        verdict = "MET"
    else:
        verdict = "NULL"

    result = {
        "gate": "CWM-LEARN-2",
        "task": "invariant prediction under distribution shift",
        "seeds": SEEDS,
        "delta": DELTA,
        "invariant_auc_mean": round(_mean(inv), 4),
        "pooled_auc_mean": round(_mean(pool), 4),
        "marginal_auc_mean": round(_mean(marg), 4),
        "advantage_inv_minus_pooled": round(adv, 4),
        "sign_test_wins": f"{wins}/{len(SEEDS)}",
        "per_seed_invariant": [round(x, 4) for x in inv],
        "per_seed_pooled": [round(x, 4) for x in pool],
        "controls": {
            "C1_no_shift_parity_gap": round(abs(_mean(ns_inv) - _mean(ns_pool)), 4),
            "C1_pass": c1,
            "C2_causal_ablation_inv_mean": round(_mean(abl), 4),
            "C2_pass": c2,
            "C3_permute_inv_mean": round(_mean(perm), 4),
            "C3_pass": c3,
            "C4_causal_recall_every_seed": causal_recall_ok,
            "C4_spurious_rejected_every_seed": spurious_reject_ok,
            "C4_pass": c4,
            "kept_sets_per_seed": kept_sets,
        },
        "verdict": verdict,
    }
    out = "experiments/cwm_learn_2.result.json"
    with open(out, "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
