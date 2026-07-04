"""T3 reference-point VARIANCE expansion (calibration; de-judgments next session's bar: bar = formula
over measured mean/SD, not a chosen margin). Pilot-v5 config (c=3.2, B=4, tol=0.5, minimality) on 15
additional calib families (9006-9020) + the original 6 -> per-family active/random id, spread stats."""
from __future__ import annotations

import json
import statistics

import experiments.svar_scm as sv
from experiments.agde_t3_pilot5 import run_min

FAMS = list(range(9000, 9021))
RUNS = [0, 1]


def main():
    keep = sv.SVAR_PARAMS["do_value"]
    sv.SVAR_PARAMS["do_value"] = 3.2
    fam_a, fam_r = [], []
    for s in FAMS:
        env = sv.SvarEnv(s)
        a = statistics.mean(1.0 if run_min(env, rs, 4, "active") == env.truth_index else 0.0
                            for rs in RUNS)
        r = statistics.mean(1.0 if run_min(env, rs, 4, "random") == env.truth_index else 0.0
                            for rs in RUNS)
        fam_a.append(a)
        fam_r.append(r)
        print(f"fam {s}: active {a:.2f} random {r:.2f}")
    sv.SVAR_PARAMS["do_value"] = keep
    ma, sda = statistics.mean(fam_a), statistics.pstdev(fam_a)
    mr = statistics.mean(fam_r)
    out = {"config": {"c": 3.2, "B": 4, "tol": 0.5, "minimality": True},
           "families": len(FAMS),
           "active_id_mean": round(ma, 3), "active_id_sd": round(sda, 3),
           "active_mean_minus_2se": round(ma - 2 * sda / (len(FAMS) ** 0.5), 3),
           "random_id_mean": round(mr, 3),
           "gap_mean": round(ma - mr, 3),
           "FORMULAIC_BARS_next_session": {
               "active_bar": round(ma - 2 * sda / (len(FAMS) ** 0.5), 3),
               "gap_bar": round((ma - mr) * 0.6, 3)}}
    open("experiments/agde_t3_variance.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
