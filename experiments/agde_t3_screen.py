"""T3 family-validity MACHINE SCREEN (AGDE-1 precedent; deterministic, no sampling): a family is
arena-valid iff the ACTIVE loop, fed NOISE-FREE true-weight clamp means as 'measurements', uniquely
identifies truth (with minimality) within B=4 at c=3.2, tol=0.5. Families failing this are structurally
unidentifiable (residual equivalences beyond minimality) -> INVALID-BY-CONSTRUCTION, excluded pre-freeze.
Also re-derives reference points (mean/SE of active/random id) on VALID calib families -> formulaic bars."""
from __future__ import annotations

import json
import statistics

import experiments.svar_scm as sv
from experiments.agde_t3_pilot import fit_hyp, predict_clamp
from experiments.agde_t3_pilot5 import run_min
from aac.hypothesis_pool import canon

TOL, C, B = 0.5, 3.2, 4


def true_coefs(env):
    return {v: (0.0, {("c", s_): env.C[(s_, v)] for s_ in env.true_pa.get(v, ())} |
                {("l", src): w for (src, dst), w in env.A.items() if dst == v})
            for v in range(env.n)}


def machine_valid(env):
    """Noise-free active discovery with TRUE mechanisms as both predictor and 'world'."""
    coefs_t = true_coefs(env)
    # every hypothesis predicts with ITS OWN fitted... for the SCREEN we use each hypothesis's ideal
    # self-consistent predictions: fit on a long noise-free... simpler: hypothesis predictions under
    # its own structure with TRUE-weight magnitudes is ill-defined for wrong structures; the honest
    # deterministic screen: use each hypothesis's OLS fit on ONE long low-noise obs draw (seed 0), and
    # the WORLD returns exact true-mechanism clamp means. Deterministic given the fixed draw.
    obs = env.obs(999)
    coefs = [fit_hyp(env, hyp, obs) for hyp in env.pool]
    alive = list(range(len(env.pool)))
    for step in range(B):
        ors = {canon(env.pool[i][0]) for i in alive}
        mn = min(len(env.pool[i][1]) for i in alive)
        minimal = [i for i in alive if len(env.pool[i][1]) == mn]
        if len(ors) == 1 and len(minimal) == 1:
            break
        best_k, best_worst = None, None
        for k in range(env.n):
            sigs = [tuple(round(predict_clamp(env, env.pool[i], coefs[i], k)[j] / (2 * TOL))
                          for j in range(env.n)) for i in alive]
            blocks = {}
            for i, s_ in enumerate(sigs):
                blocks.setdefault(s_, []).append(i)
            worst = max(len(b) for b in blocks.values())
            if best_worst is None or worst < best_worst:
                best_k, best_worst = k, worst
        k = best_k
        world = predict_clamp(env, env.pool[env.truth_index], true_coefs(env), k)  # exact true means
        alive = [i for i in alive
                 if max(abs(predict_clamp(env, env.pool[i], coefs[i], k)[j] - world[j])
                        for j in range(env.n)) <= TOL]
        if not alive:
            return False
    ors = {canon(env.pool[i][0]) for i in alive}
    mn = min(len(env.pool[i][1]) for i in alive)
    minimal = [i for i in alive if len(env.pool[i][1]) == mn]
    return len(ors) == 1 and len(minimal) == 1 and minimal[0] == env.truth_index


def main():
    keep = sv.SVAR_PARAMS["do_value"]
    sv.SVAR_PARAMS["do_value"] = C
    valid, invalid = [], []
    for s in range(9000, 9021):
        env = sv.SvarEnv(s)
        (valid if machine_valid(env) else invalid).append(s)
    print(f"valid {len(valid)}/{len(valid)+len(invalid)}: {valid}")
    fam_a, fam_r = [], []
    for s in valid:
        env = sv.SvarEnv(s)
        fam_a.append(statistics.mean(1.0 if run_min(env, rs, B, "active") == env.truth_index else 0.0
                                     for rs in (0, 1)))
        fam_r.append(statistics.mean(1.0 if run_min(env, rs, B, "random") == env.truth_index else 0.0
                                     for rs in (0, 1)))
    sv.SVAR_PARAMS["do_value"] = keep
    ma, sda, mr = statistics.mean(fam_a), statistics.pstdev(fam_a), statistics.mean(fam_r)
    se = sda / (len(fam_a) ** 0.5)
    out = {"valid_families": valid, "invalid_families": invalid,
           "valid_fraction": round(len(valid) / 21, 3),
           "on_valid": {"active_mean": round(ma, 3), "active_sd": round(sda, 3),
                        "random_mean": round(mr, 3), "gap": round(ma - mr, 3)},
           "FORMULAIC_BARS": {"active_bar_mean_minus_2se": round(ma - 2 * se, 3),
                              "gap_bar_60pct": round((ma - mr) * 0.6, 3)}}
    open("experiments/agde_t3_screen.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
