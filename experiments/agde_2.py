"""AGDE-2 scored gate — full-identification at the information-feasible budget (fresh families/seeds).

AGDE-1 NULLed as frozen (capture 0.4895 < 0.50 vs a TRUTH-INFORMED oracle at B=1). Diagnosis + RR-0044
ledger: at B=1 no truth-blind policy can exceed expected ID 3/4 (one do() makes <=3 blocks of a 4-MEC;
measured blind ceiling exactly 0.750), so gate-1's referee was structurally unreachable; and B=2 supplies
exactly the log2(4)=2 bits full identification needs. AGDE-2 asks the WELL-POSED question with a
LEDGER-DERIVED a-priori bar on FRESH families (seeds 200+, runs 20-22 — never touched by gate 1 or
calibration): at the information-feasible budget, does the blind min-max chooser close the WHOLE gap?

Frozen decision (mechanical): PRIMARY at B=2: MET iff mean ID_A >= 0.90 absolute AND capture vs
truth-informed oracle >= 0.90 AND A>R on >=2/3 decided families AND controls (determinism, gate audit,
E==A/D==R replays, perm collapse). SECONDARY at B=1 (report): capture vs BLIND ceiling (a-priori 0.75
per bit count). This is a NEW claim, not a re-cut: gate-1's claim failed and stays failed."""
from __future__ import annotations

import json
import statistics

import experiments.intervention_scm as scm
from aac.discovery_loop import run_discovery
from experiments.agde_1 import id_score, replay, TOL, N_INT

RUN_SEEDS = [20, 21, 22]
N_FAMS = 30
B = 2


def fams_fresh():
    out, s = [], 200
    while len(out) < N_FAMS and s < 700:
        f = scm.Family(s)
        if scm.valid_family(f, TOL):
            out.append(f)
        s += 1
    return out


def main():
    fams = fams_fresh()
    per = {a: {} for a in ("A", "R", "O")}
    det = gate = intE = intD = True
    perm = []
    b1_blind = []
    for f in fams:
        for rs in RUN_SEEDS:
            obs = f.sample_obs(rs)

            def env(k, step, _f=f, _rs=rs):
                return _f.sample_do(k, _rs, step, N_INT)
            env.truth_index = f.truth_index
            runs = {}
            for arm, pol in (("A", "active"), ("R", "random"), ("O", "oracle")):
                r = run_discovery(f.n, f.pool, obs, env, B, pol, seed=rs, tol=TOL, c=scm.SCM_PARAMS["do_value"])
                r._run_seed = rs
                runs[arm] = r
                per[arm].setdefault(f.family_seed, []).append(id_score(r, f))
                if len([t for t in r.gate_trace if t.endswith("ALLOW")]) != len(r.interventions) \
                        or len(r.interventions) > B:
                    gate = False
            r2 = run_discovery(f.n, f.pool, obs, env, B, "active", seed=rs, tol=TOL, c=scm.SCM_PARAMS["do_value"])
            if r2.interventions != runs["A"].interventions or r2.survivors != runs["A"].survivors:
                det = False
            if [f.pool[i] for i in replay(f, runs["A"], obs)] != runs["A"].survivors:
                intE = False
            if [f.pool[i] for i in replay(f, runs["R"], obs)] != runs["R"].survivors:
                intD = False

            def env_null(k, step, _f=f, _rs=rs):
                return _f.sample_obs(_rs + 777, N_INT)
            env_null.truth_index = f.truth_index
            rp = run_discovery(f.n, f.pool, obs, env_null, B, "active", seed=rs, tol=TOL,
                               c=scm.SCM_PARAMS["do_value"])
            perm.append(1.0 if (rp.identified and rp.correct) else 0.0)
            # secondary: B=1 active vs a-priori blind ceiling 0.75
            r1 = run_discovery(f.n, f.pool, obs, env, 1, "active", seed=rs, tol=TOL, c=scm.SCM_PARAMS["do_value"])
            b1_blind.append(id_score(r1, f))

    fm = {a: {fs: statistics.mean(v) for fs, v in per[a].items()} for a in per}
    means = {a: round(statistics.mean(fm[a].values()), 4) for a in per}
    gap = means["O"] - means["R"]
    capture = (means["A"] - means["R"]) / gap if gap > 0 else 0.0
    decided = [fs for fs in fm["A"] if abs(fm["A"][fs] - fm["R"][fs]) > 1e-9]
    wins = sum(1 for fs in decided if fm["A"][fs] > fm["R"][fs])
    controls = {"determinism": det, "gate_audit": gate, "integrity_E_eq_A": intE, "integrity_D_eq_R": intD,
                "perm_rate": round(statistics.mean(perm), 4), "perm_collapses": statistics.mean(perm) <= 0.25}
    ok = all(v for v in controls.values() if isinstance(v, bool))
    sign_ok = decided and wins >= (2 * len(decided)) / 3
    met = ok and means["A"] >= 0.90 and capture >= 0.90 and sign_ok
    verdict = "INVALID" if not ok else ("MET" if met else "NULL")
    out = {"gate": "AGDE-2", "B": B, "family_seeds": [f.family_seed for f in fams],
           "arm_means_B2": means, "capture_vs_oracle": round(capture, 4),
           "A_gt_R": f"{wins}/{len(decided)}",
           "secondary_B1_active_mean": round(statistics.mean(b1_blind), 4),
           "secondary_B1_capture_vs_apriori_blind_ceiling_0.75":
               round((statistics.mean(b1_blind) - means["R"]) / (0.75 - means["R"]), 4) if means["R"] < 0.75 else None,
           "controls": controls, "verdict": verdict}
    with open("experiments/agde_2.result.json", "w") as fj:
        json.dump(out, fj, indent=2)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
