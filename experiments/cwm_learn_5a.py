"""CWM-LEARN-5a — multi-environment augmentation + curriculum for the learned representation (RR-0041).

Founder-opened enhancement route (2026-07-04): more/more-diverse environments + easy->hard staged training
are the known levers for IRM/V-REx stability. This is an ENGINEERING-ITERATION experiment (quantitative
placement on OUR stack), not a novelty gate: the calibrated expectation is "clear improvement over LEARN-4's
chance-level 0.495, below the oracle/supplied ceiling (~0.88)". NOT a repetition of verified-failed work:
the failed configuration (3 extreme envs, direct full-strength V-REx) is cited from LEARN-4, not re-run.

Arms (10 seeds, NOVEL-A primary / NOVEL-C strict-isolation secondary; LEARN-4 anchors cited for reference):
  direct8     — V-REx lam=1e4 on all 8 diverse envs at once, 300 epochs   (diversity effect alone)
  curriculum8 — stage 1: 3 weak envs, lam=0, 150 ep (interaction is the dominant signal -> learn it first);
                stage 2: warm-start, all 8 envs, lam=1e4, 150 ep          (curriculum effect on top)
  erm8        — lam=0, all 8 envs, 300 epochs                              (does diversity alone fix ERM?)
Historical anchors (LEARN-4, same test envs/seeds): vrex3 0.495 / erm3 0.623 / supplied 0.894 / oracle 0.881.

Frozen verdict bands (measured-ceiling-relative, no naked absolutes):
  IMPROVED  iff best-arm NOVEL-A mean >= 0.65 AND >= LEARN-4 vrex3 + 0.10
  FLAT      iff best-arm NOVEL-A mean <  LEARN-4 vrex3 + 0.05
  DEGRADED  iff best-arm NOVEL-A mean <  LEARN-4 vrex3 - 0.05
  (between IMPROVED and FLAT bands -> MARGINAL). Curriculum-specific claim only if curriculum8 > direct8
  by >= 0.05 with >= 8/10 sign test. Run AFTER prereg freeze; never tuned to pass.
"""
from __future__ import annotations

import json
import statistics

import experiments.synthetic_scm_transfer as base
import experiments.synthetic_scm_transfer_ext as ext
from aac.transfer_cwm import TransferMLP, _auc

SEEDS = list(range(10))
L4 = {"vrex3_novelA": 0.4947, "erm3_novelA": 0.6229, "supplied_novelA": 0.8939, "oracle_novelA": 0.8813}


def _m(xs):
    return statistics.mean(xs)


def _fit_direct(envs, lam, epochs, seed):
    m = TransferMLP(5, lam=lam, epochs=epochs, seed=seed)
    return m.fit(envs)


def _fit_curriculum(fam, seed):
    c = ext.EXT_PARAMS["curriculum"]
    m = TransferMLP(5, lam=c["stage1_lam"], epochs=c["stage1_epochs"], seed=seed)
    m.fit(fam["weak"])                       # stage 1: weak shift, no penalty — learn the interaction
    m.lam, m.epochs = c["stage2_lam"], c["stage2_epochs"]
    m.fit(fam["weak"] + fam["strong_plus"])  # stage 2: warm start, all 8 envs, full penalty
    return m


def main():
    arms = {"direct8": [], "curriculum8": [], "erm8": []}
    armsC = {"direct8": [], "curriculum8": [], "erm8": []}
    for s in SEEDS:
        fam = ext.train_family_8(s)
        all8 = fam["weak"] + fam["strong_plus"]
        aX, aY = base.novelA_env(s)
        cX, cY = ext.novelC_env(s)
        models = {
            "direct8": _fit_direct(all8, ext.EXT_PARAMS["direct_lam"], ext.EXT_PARAMS["direct_epochs"], s),
            "curriculum8": _fit_curriculum(fam, s),
            "erm8": _fit_direct(all8, 0.0, ext.EXT_PARAMS["direct_epochs"], s),
        }
        for k, m in models.items():
            arms[k].append(_auc([m.prob(x) for x in aX], aY))
            armsC[k].append(_auc([m.prob(x) for x in cX], cY))

    means = {k: round(_m(v), 4) for k, v in arms.items()}
    best_arm = max(means, key=means.get)
    best = means[best_arm]
    curr_vs_direct = _m(arms["curriculum8"]) - _m(arms["direct8"])
    curr_wins = sum(1 for a, b in zip(arms["curriculum8"], arms["direct8"]) if a > b)

    if best >= 0.65 and best >= L4["vrex3_novelA"] + 0.10:
        verdict = "IMPROVED"
    elif best < L4["vrex3_novelA"] - 0.05:
        verdict = "DEGRADED"
    elif best < L4["vrex3_novelA"] + 0.05:
        verdict = "FLAT"
    else:
        verdict = "MARGINAL"

    result = {
        "experiment": "CWM-LEARN-5a", "route": "multi-env augmentation + curriculum",
        "seeds": SEEDS, "learn4_anchors": L4,
        "novelA_means": means, "novelC_means": {k: round(_m(v), 4) for k, v in armsC.items()},
        "per_seed_novelA": {k: [round(x, 4) for x in v] for k, v in arms.items()},
        "best_arm": best_arm,
        "curriculum_minus_direct": round(curr_vs_direct, 4),
        "curriculum_sign_test": f"{curr_wins}/10",
        "curriculum_claim": bool(curr_vs_direct >= 0.05 and curr_wins >= 8),
        "verdict": verdict,
    }
    with open("experiments/cwm_learn_5a.result.json", "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
