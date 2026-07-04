"""CWM-LEARN-5b — few interventional anchors (RR-0041; the founder's highest-value route: "数量级提升,
性价比极高"; A/B-test analog, and the deepest product synergy — the OS's governed action->outcome loop IS an
interventional-anchor source).

Question: how few do(Xs)-randomized anchor samples (added as ONE extra training environment to the LEARN-4
setup) lift the learned representation's cross-family transfer, and does the invariance penalty still matter
once anchors exist? NOT verified-failed repetition: N=0 (the failed configuration) is cited from LEARN-4.

Design: train = LEARN-4's 3 strong-linear envs + anchor_env(N); anchors enter as a 4th environment (equal
per-env gradient weight — an implicit, frozen upweighting, symmetric across arms). N in {16, 64, 256} vs
3x400 observational samples. Arms: vrex (lam=1e4) and erm (lam=0). PRIMARY test = NOVEL-B (tanh mechanism,
never trained on, never intervened on -> strictly family-isolated; LEARN-4 refs: vrex 0.473 / erm 0.675 /
supplied 0.893). SECONDARY = NOVEL-A (its independence property is partially what anchors teach; reported
with that caveat). 10 seeds.

Frozen verdict bands:
  ANCHORS-WORK      iff best (arm,N) NOVEL-B mean >= 0.80 (near the supplied ceiling 0.893)
  ANCHORS-PARTIAL   iff best NOVEL-B mean in [0.60, 0.80)
  ANCHORS-FLAT      iff best NOVEL-B mean < 0.60
  PENALTY-SUPERFLUOUS reported iff |vrex - erm| < 0.03 at the best N (anchors replace the penalty — itself a
  finding). Run AFTER prereg freeze; never tuned to pass.
"""
from __future__ import annotations

import json
import statistics

import experiments.synthetic_scm_transfer as base
import experiments.synthetic_scm_transfer_ext as ext
from aac.transfer_cwm import TransferMLP, _auc

SEEDS = list(range(10))
NS = [16, 64, 256]
L4 = {"vrex_N0_novelB": 0.4731, "erm_N0_novelB": 0.6745, "supplied_novelB": 0.8934}


def _m(xs):
    return statistics.mean(xs)


def main():
    res = {f"{arm}_N{n}": {"B": [], "A": []} for arm in ("vrex", "erm") for n in NS}
    for s in SEEDS:
        tr3 = base.train_family(s)
        bX, bY = base.novelB_env(s)
        aX, aY = base.novelA_env(s)
        for n in NS:
            anch = ext.anchor_env(s, n)
            envs = tr3 + [anch]
            for arm, lam in (("vrex", 1e4), ("erm", 0.0)):
                m = TransferMLP(5, lam=lam, epochs=250, seed=s).fit(envs)
                res[f"{arm}_N{n}"]["B"].append(_auc([m.prob(x) for x in bX], bY))
                res[f"{arm}_N{n}"]["A"].append(_auc([m.prob(x) for x in aX], aY))

    curveB = {k: round(_m(v["B"]), 4) for k, v in res.items()}
    curveA = {k: round(_m(v["A"]), 4) for k, v in res.items()}
    best_key = max(curveB, key=curveB.get)
    best = curveB[best_key]
    best_n = int(best_key.split("_N")[1])
    gap_at_best = abs(curveB[f"vrex_N{best_n}"] - curveB[f"erm_N{best_n}"])

    if best >= 0.80:
        verdict = "ANCHORS-WORK"
    elif best >= 0.60:
        verdict = "ANCHORS-PARTIAL"
    else:
        verdict = "ANCHORS-FLAT"

    result = {
        "experiment": "CWM-LEARN-5b", "route": "few interventional anchors (A/B analog)",
        "seeds": SEEDS, "anchor_counts": NS, "learn4_N0_anchors_cited": L4,
        "novelB_curve_primary": curveB, "novelA_curve_secondary": curveA,
        "per_seed_novelB": {k: [round(x, 4) for x in v["B"]] for k, v in res.items()},
        "best": {"key": best_key, "novelB_mean": best},
        "vrex_vs_erm_gap_at_best_N": round(gap_at_best, 4),
        "penalty_superfluous": bool(gap_at_best < 0.03),
        "verdict": verdict,
    }
    with open("experiments/cwm_learn_5b.result.json", "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
