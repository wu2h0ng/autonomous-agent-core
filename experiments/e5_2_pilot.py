"""5e-2 PILOT (calibration, no freeze): find the ZERO-SHOT arena's n — the sample size where
screening's RANKING of 1,770 pairs collapses (recall@30 of true pairs) while VERIFICATION of a given
30-candidate set stays sound (oracle-set verified AUC). The gap between those two curves is the
knowledge channel's exclusive region (design: 5E-2.DESIGN-NOTE)."""
from __future__ import annotations

import json
import statistics

import experiments.synthetic_scm_highdim as hd
from experiments.cwm_learn_5e import _screen_pairs, _fit_score
from aac.invariant_structure import InvariantStructureFilter

NS = [40, 80, 160, 320]
SEEDS = [300, 301, 302]


def main():
    keep = hd.HD_PARAMS["n_train"]
    out = {"per_n": {}}
    true_pairs = hd.HD_PARAMS["true_pairs"]
    tset = {tuple(p) for p in true_pairs}
    for n in NS:
        hd.HD_PARAMS["n_train"] = n
        rec, ver = [], []
        for s in SEEDS:
            tr = hd.train_envs_hd(s)
            teX, teY = hd.test_env_hd(s)
            scr = _screen_pairs(tr, 30)
            rec.append(len({tuple(p) for p in scr} & tset) / len(tset))
            # verification soundness of a GIVEN candidate set (oracle pairs + decoys to 30) at this n
            import random as _r
            rr = _r.Random(f"5e2|{s}")
            allp = [(i, j) for i in range(60) for j in range(i + 1, 60) if (i, j) not in tset]
            cand = [list(p) for p in true_pairs] + [list(p) for p in rr.sample(allp, 30 - len(true_pairs))]
            ver.append(_fit_score(tr, teX, teY, cand, s))
        out["per_n"][n] = {"screening_recall@30": round(statistics.mean(rec), 3),
                           "given30_verified_auc": round(statistics.mean(ver), 3)}
        print(n, json.dumps(out["per_n"][n]))
    hd.HD_PARAMS["n_train"] = keep
    # zero-shot arena n = largest n where screening recall <= 0.5 while verified auc >= 0.75
    zone = [n for n in NS if out["per_n"][n]["screening_recall@30"] <= 0.5
            and out["per_n"][n]["given30_verified_auc"] >= 0.75]
    out["zero_shot_arena_n_candidates"] = zone
    open("experiments/e5_2_pilot.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "per_n"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
