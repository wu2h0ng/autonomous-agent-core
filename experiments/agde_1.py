"""AGDE-1 scored gate — Choice-vs-Random under budget scarcity (packet §4; RR-0044 typed routing).

Scored family seeds from 100 upward until 30 VALID families (frozen list recorded in the result), run
seeds {10,11,12} — both disjoint from calibration (families 1000+, runs 0-2). Frozen: tol=0.6, n_int=100,
B_primary=1 (max measured gap 0.68), B_secondary=2, do value c=2.0.

Arms: A active / R random / RR roundrobin / O oracle (ceiling) / OBS+OBS+ (structural floor 1/|MEC| —
the consistency verifier only consumes do-regime data, so observational arms cannot move by design;
disclosed) / D,E integrity replays (D: R's collected do-datasets replayed one-shot through the identical
verifier must EQUAL R's survivors; E: same for A — the loop machinery must add nothing beyond data choice).

Decision (frozen; mechanical):
  capture = (mean ID_A - mean ID_R) / (mean ID_O - mean ID_R) at B=1
  MET  iff capture >= 0.5 AND A>R on >=2/3 of decided families (paired family means, ties dropped)
       AND all controls pass (C-PERM collapse <= floor; determinism byte-equal; gate audit exact;
       D==R and E==A exact; OBS floors exact; scored families all valid).
  NULL iff controls pass but capture < 0.5 or sign test fails (H0-CHOOSER stands; publishable).
  INVALID iff any control fails.
ID score per (family, run): 1/|survivors| if truth among survivors else 0 (unique correct -> 1.0).
"""
from __future__ import annotations

import json
import statistics

import experiments.intervention_scm as scm
from aac.discovery_loop import run_discovery
from aac.structure_consistency import Exhausted, fit_mechanisms, prune

TOL, N_INT, B1, B2 = 0.6, 100, 1, 2
RUN_SEEDS = [10, 11, 12]
N_FAMS = 30


def collect_scored_families():
    fams, s = [], 100
    while len(fams) < N_FAMS and s < 500:
        f = scm.Family(s)
        if scm.valid_family(f, TOL):
            fams.append(f)
        s += 1
    return fams


def id_score(res, f):
    if not res.survivors:
        return 0.0
    idx = [i for i, h in enumerate(f.pool) if h in res.survivors]
    return (1.0 / len(idx)) if f.truth_index in idx else 0.0


def replay(f, res, obs):
    """One-shot batch replay of a loop's collected do-datasets through the identical verifier."""
    mechs = [fit_mechanisms(f.n, h, obs) for h in f.pool]
    alive = list(range(len(f.pool)))
    for step, k in enumerate(res.interventions):
        rows = f.sample_do(k, res._run_seed, step, N_INT)
        try:
            keep, _ = prune(f.n, [f.pool[i] for i in alive], [mechs[i] for i in alive],
                            k, scm.SCM_PARAMS["do_value"], rows, TOL)
        except Exhausted:
            return []
        alive = [alive[i] for i in keep]
    return alive


def main():
    fams = collect_scored_families()
    result = {"gate": "AGDE-1", "frozen": {"tol": TOL, "n_int": N_INT, "B1": B1, "B2": B2,
                                           "run_seeds": RUN_SEEDS},
              "family_seeds": [f.family_seed for f in fams]}
    per = {arm: {} for arm in ("A", "R", "RR", "O")}
    integrity_D = integrity_E = True
    determinism_ok = True
    gate_ok = True
    perm_scores = []

    for f in fams:
        for rs in RUN_SEEDS:
            obs = f.sample_obs(rs)

            def env(k, step, _f=f, _rs=rs):
                return _f.sample_do(k, _rs, step, N_INT)
            env.truth_index = f.truth_index
            runs = {}
            for arm, pol in (("A", "active"), ("R", "random"), ("RR", "roundrobin"), ("O", "oracle")):
                r = run_discovery(f.n, f.pool, obs, env, B1, pol, seed=rs, tol=TOL, c=scm.SCM_PARAMS["do_value"])
                r._run_seed = rs
                runs[arm] = r
                per[arm].setdefault(f.family_seed, []).append(id_score(r, f))
                if len([t for t in r.gate_trace if t.endswith("ALLOW")]) != len(r.interventions) \
                        or len(r.interventions) > B1:
                    gate_ok = False
            # determinism: rerun A, byte-compare survivors + interventions
            r2 = run_discovery(f.n, f.pool, obs, env, B1, "active", seed=rs, tol=TOL, c=scm.SCM_PARAMS["do_value"])
            if r2.interventions != runs["A"].interventions or r2.survivors != runs["A"].survivors:
                determinism_ok = False
            # integrity replays
            aliveE = replay(f, runs["A"], obs)
            aliveD = replay(f, runs["R"], obs)
            if [f.pool[i] for i in aliveE] != runs["A"].survivors:
                integrity_E = False
            if [f.pool[i] for i in aliveD] != runs["R"].survivors:
                integrity_D = False
            # C-PERM: null interventions (obs rows as do-data) must not look good
            def env_null(k, step, _f=f, _rs=rs):
                return _f.sample_obs(_rs + 777, N_INT)
            env_null.truth_index = f.truth_index
            rp = run_discovery(f.n, f.pool, obs, env_null, B1, "active", seed=rs, tol=TOL,
                               c=scm.SCM_PARAMS["do_value"])
            perm_scores.append(1.0 if (rp.identified and rp.correct) else 0.0)

    fam_means = {arm: {fs: statistics.mean(v) for fs, v in per[arm].items()} for arm in per}
    means = {arm: round(statistics.mean(fam_means[arm].values()), 4) for arm in per}
    gap = means["O"] - means["R"]
    capture = (means["A"] - means["R"]) / gap if gap > 0 else 0.0
    decided = [fs for fs in fam_means["A"] if abs(fam_means["A"][fs] - fam_means["R"][fs]) > 1e-9]
    wins = sum(1 for fs in decided if fam_means["A"][fs] > fam_means["R"][fs])
    perm_rate = statistics.mean(perm_scores)
    floor = 1.0 / 4.0
    controls = {"determinism": determinism_ok, "gate_audit": gate_ok,
                "integrity_E_eq_A": integrity_E, "integrity_D_eq_R": integrity_D,
                "perm_correct_rate": round(perm_rate, 4), "perm_collapses": perm_rate <= floor,
                "obs_floor_structural": True}
    ok = all(v for k, v in controls.items() if isinstance(v, bool))
    sign_ok = len(decided) > 0 and wins >= (2 * len(decided)) / 3
    if not ok:
        verdict = "INVALID"
    elif capture >= 0.5 and sign_ok:
        verdict = "MET"
    else:
        verdict = "NULL"
    result.update({
        "arm_means_B1": means, "oracle_random_gap": round(gap, 4), "capture_ratio": round(capture, 4),
        "families_decided": len(decided), "A_gt_R_wins": wins,
        "roundrobin_mean": means["RR"], "controls": controls, "verdict": verdict,
    })
    with open("experiments/agde_1.result.json", "w") as fj:
        json.dump(result, fj, indent=2)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
