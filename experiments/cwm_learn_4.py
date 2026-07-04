"""CWM-LEARN-4 scored gate — cross-domain transfer of a LEARNED invariant representation (RR-0039 gate 4).

Question: does a SELF-LEARNED representation (stdlib V-REx MLP) trained on ONE environment family transfer to
a COMPLETELY ISOLATED novel family better than baselines — specifically, does it isolate the invariant
interaction (slots 0,1) and generalise to NOVEL-A, whose nuisance is INDEPENDENT of y (non-exploitable), so
that only a true invariant representation can transfer?

Arms on NOVEL-A (held-out family; primary), seeds 0..9:
  vrex     — LEARNED invariant representation (V-REx MLP)         [the thesis arm]
  erm      — capacity-matched ERM MLP (same arch, no invariance)  [capacity baseline: expected chance]
  supplied — LEARN-3 supplied degree-2 basis + invariance select  [POSITIVE control: transfer IS possible]
  oracle   — MLP on causal slots 0,1 only                          [POSITIVE control: signal IS present]
  pooled   — pooled statistical logistic on raw features           [statistical baseline]

Decision (measured-ceiling-relative; author recommends, founder casts). DELTA=0.05, sign test 8/10.
  POSITIVE CONTROLS (transfer achievable): oracle >= 0.85 AND supplied >= 0.70. If they FAIL -> the task is
    impossible / organ-capacity, a different meaning -> ORGAN-CAPACITY-NULL / INVALID.
  MET iff (positives hold) AND vrex >= 0.65 AND (vrex-erm)>=DELTA AND (vrex-pooled)>=DELTA AND
    vrex >= supplied-0.10 (the learned arm approaches the achievable transfer ceiling) AND 8/10 sign test.
  NULL iff positives hold but the learned arm does NOT clear the MET bar (expected: vrex ~ erm ~ pooled ~
    chance, far below supplied/oracle). An INFORMATIVE null: transfer is achievable (supplied/oracle) but our
    LEARNED representation does not achieve it -> learning the invariant representation from scratch fails
    cross-family in this stdlib regime; the structure still has to be supplied (LEARN-3).
  INVALID iff permute does not collapse OR positives fail in a way that makes the null uninformative.

Frozen honest prediction: NULL (spike evidence: learned arms collapse to chance on non-exploitable novel
nuisance; oracle 0.99). Run AFTER prereg freeze; digests rechecked. Never tuned to pass.
"""
from __future__ import annotations

import json
import statistics

import experiments.synthetic_scm_transfer as scm
from aac.interaction_cwm import InteractionCWM
from aac.learned_cwm import LearnedCWM
from aac.transfer_cwm import mlp_transfer_auc

SEEDS = list(range(10))
DELTA = 0.05
LAM = 1e4   # V-REx penalty (frozen)


def _m(xs):
    return statistics.mean(xs)


def main():
    ic = InteractionCWM()
    lin = LearnedCWM()
    vrex, erm, supplied, oracle, pooled, perm = [], [], [], [], [], []
    vB, eB, sB = [], [], []
    for s in SEEDS:
        tr = scm.train_family(s)
        aX, aY = scm.novelA_env(s)
        bX, bY = scm.novelB_env(s)
        vrex.append(mlp_transfer_auc(tr, aX, aY, lam=LAM, seed=s))
        erm.append(mlp_transfer_auc(tr, aX, aY, lam=0.0, seed=s))
        perm.append(mlp_transfer_auc(tr, aX, aY, lam=LAM, seed=s, permute=True))
        supplied.append(ic.invariant_interaction_auc(tr, aX, aY, seed=s, mode="inv_interaction"))
        tr_oracle = [(scm.interaction_only(X), Y) for X, Y in tr]
        oracle.append(mlp_transfer_auc(tr_oracle, scm.interaction_only(aX), aY, lam=0.0, seed=s))
        pooled.append(lin.invariant_predict_auc(tr, aX, aY, seed=s, mode="pooled"))
        # NOVEL-B secondary
        vB.append(mlp_transfer_auc(tr, bX, bY, lam=LAM, seed=s))
        eB.append(mlp_transfer_auc(tr, bX, bY, lam=0.0, seed=s))
        sB.append(ic.invariant_interaction_auc(tr, bX, bY, seed=s, mode="inv_interaction"))

    positives_hold = _m(oracle) >= 0.85 and _m(supplied) >= 0.70
    permute_ok = abs(_m(perm) - 0.5) < 0.08
    d_erm = _m(vrex) - _m(erm)
    d_pooled = _m(vrex) - _m(pooled)
    wins_erm = sum(1 for a, b in zip(vrex, erm) if a > b)
    met = (positives_hold and _m(vrex) >= 0.65 and d_erm >= DELTA and d_pooled >= DELTA
           and _m(vrex) >= _m(supplied) - 0.10 and wins_erm >= 8)

    if not permute_ok:
        verdict = "INVALID"
    elif not positives_hold:
        verdict = "INVALID(TRANSFER-NOT-ACHIEVABLE)"   # positive controls failed -> null uninformative
    elif met:
        verdict = "MET"
    else:
        verdict = "NULL"

    result = {
        "gate": "CWM-LEARN-4", "task": "cross-family transfer of a LEARNED invariant representation",
        "seeds": SEEDS, "delta": DELTA, "vrex_lambda": LAM,
        "novelA_means": {
            "vrex_LEARNED_ours": round(_m(vrex), 4), "erm_capacity_matched": round(_m(erm), 4),
            "supplied_basis_LEARN3_positive": round(_m(supplied), 4),
            "oracle_causal_only_positive": round(_m(oracle), 4), "pooled_statistical": round(_m(pooled), 4),
        },
        "novelB_means": {"vrex": round(_m(vB), 4), "erm": round(_m(eB), 4), "supplied_basis": round(_m(sB), 4)},
        "vrex_minus_erm": round(d_erm, 4), "sign_test_vrex_gt_erm": f"{wins_erm}/10",
        "vrex_minus_pooled": round(d_pooled, 4),
        "vrex_vs_supplied_gap": round(_m(vrex) - _m(supplied), 4),
        "per_seed_vrex": [round(x, 4) for x in vrex],
        "per_seed_supplied": [round(x, 4) for x in supplied],
        "controls": {
            "positive_oracle_ge_0.85": _m(oracle) >= 0.85,
            "positive_supplied_ge_0.70": _m(supplied) >= 0.70,
            "positives_hold": positives_hold,
            "permute_collapses": permute_ok, "permute_mean": round(_m(perm), 4),
        },
        "verdict": verdict,
    }
    out = "experiments/cwm_learn_4.result.json"
    with open(out, "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
