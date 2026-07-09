"""AGDE-T3 PILOT v5 — causal-minimality collapse (frozen classical principle, mechanical):
nesting lives ONLY in lag-subsets (orientations share the skeleton, never nested). At loop end, the
survivor set is collapsed: identified iff survivors share ONE orientation AND the minimal lag-subset
among them is unique; the identified structure = (that orientation, minimal lagset). Correct iff it
equals truth exactly (minimality makes the superset-equivalence ill-posedness disappear BY CONVENTION,
the standard Spirtes/Pearl assumption). Measures id/gap at c in {2.0, 3.2}, budgets {4, 5}."""
from __future__ import annotations

import json
import random
import statistics
from typing import Iterable

import experiments.svar_scm as sv
from experiments.agde_t3_pilot import fit_hyp, predict_clamp
from aac.hypothesis_pool import canon

TOL = 0.5
FAMS = list(range(9000, 9006))
RUNS = [0, 1]
NOT_AUTHORIZED = (
    "freeze_verdict",
    "r_final",
    "route_promotion",
    "autonomy_claim",
    "product_claim",
    "C6_C7_change",
)


def signatures(env, hyps, coefs_list, k):
    return [tuple(round(predict_clamp(env, hyp, coefs, k)[j] / (2 * TOL)) for j in range(env.n))
            for hyp, coefs in zip(hyps, coefs_list)]


def collapse_minimal_survivor(pool, alive):
    """Return the unique causal-minimal survivor, or None if ambiguity remains."""
    survivors = list(alive)
    if not survivors:
        return None
    ors = {canon(pool[i][0]) for i in survivors}
    if len(ors) != 1:
        return None
    min_size = min(len(pool[i][1]) for i in survivors)
    minimal = [i for i in survivors if len(pool[i][1]) == min_size]
    return minimal[0] if len(minimal) == 1 else None


def run_min(env, rs, budget, policy):
    obs = env.obs(rs)
    coefs = [fit_hyp(env, hyp, obs) for hyp in env.pool]
    alive = list(range(len(env.pool)))
    rng = random.Random(f"T3v5|{env.seed}|{rs}|{policy}")
    for step in range(budget):
        # minimality-aware early stop: unique orientation + unique minimal lagset.
        if collapse_minimal_survivor(env.pool, alive) is not None:
            break
        if policy == "active":
            best_k, best_worst = None, None
            for k in range(env.n):
                sigs = signatures(env, [env.pool[i] for i in alive], [coefs[i] for i in alive], k)
                blocks = {}
                for i, s_ in enumerate(sigs):
                    blocks.setdefault(s_, []).append(i)
                worst = max(len(b) for b in blocks.values())
                if best_worst is None or worst < best_worst:
                    best_k, best_worst = k, worst
            k = best_k
        else:
            k = rng.randrange(env.n)
        measured = env.do_window(k, rs, step)
        keep = [i for i in alive
                if max(abs(predict_clamp(env, env.pool[i], coefs[i], k)[j] - measured[j])
                       for j in range(env.n)) <= TOL]
        if not keep:
            return None
        alive = keep
    return collapse_minimal_survivor(env.pool, alive)


def run_pilot(
    *,
    families: Iterable[int] = FAMS,
    runs: Iterable[int] = RUNS,
    c_values: Iterable[float] = (2.0, 3.2),
    budgets: Iterable[int] = (4, 5),
):
    family_list = list(families)
    run_list = list(runs)
    out = {
        "schema_version": "agde_t3_pilot5_v1",
        "evidence_level": "calibration_pilot_not_freeze",
        "claim_scope": "apparatus_calibration_only",
        "tol": TOL,
        "families": family_list,
        "runs": run_list,
        "not_authorized": list(NOT_AUTHORIZED),
        "configs": {},
    }
    keep_c = sv.SVAR_PARAMS["do_value"]
    try:
        for c in c_values:
            sv.SVAR_PARAMS["do_value"] = c
            for B in budgets:
                a_id, r_id = [], []
                for s in family_list:
                    env = sv.SvarEnv(s)
                    for rs in run_list:
                        ia = run_min(env, rs, B, "active")
                        a_id.append(1.0 if ia == env.truth_index else 0.0)
                        ir = run_min(env, rs, B, "random")
                        r_id.append(1.0 if ir == env.truth_index else 0.0)
                key = f"c{c}_B{B}"
                out["configs"][key] = {
                    "active_id": round(statistics.mean(a_id), 3),
                    "random_id": round(statistics.mean(r_id), 3),
                    "gap": round(statistics.mean(a_id) - statistics.mean(r_id), 3),
                }
    finally:
        sv.SVAR_PARAMS["do_value"] = keep_c
    return out


def main():
    out = run_pilot()
    for key, cfg in out["configs"].items():
        print(key, json.dumps(cfg))
    open("experiments/agde_t3_pilot5.result.json", "w").write(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
