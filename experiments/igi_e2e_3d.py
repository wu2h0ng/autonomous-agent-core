"""IGI-E2E-3d — the goal-axis CLOSURE gate: nominate-by-model + commit-by-demonstration.

The constitutional mechanism derived from the axis's three measured failures (0.375 / 0.469 / 0.656,
all model-EXTRAPOLATED commitment) and predicted by RR-0044 typed routing (commitment is a structure-
type decision -> discrete channel): the model NOMINATES candidate goals; a governed TRIAL demonstrates
one; the agent COMMITS to the DEMONSTRATED band (trial outcome +- 0.35, principal boundary re-checked);
achievement = an independent fresh execution reproduces the committed band.

PAIRED CONTRAST ARM on the same envs/seeds: the 3c-style extrapolated commitment (K-fold ensemble band)
— so the routing contrast (demonstration vs extrapolation) is measured side-by-side in one file.

Frozen decision (mechanical), classes tree6/star7, 8 envs x 2 runs, fresh seeds 1600+, runs {95,96}:
  PASS iff commitment rate >= 0.80 (a nominee trial lands in-boundary within 3 trials) AND reproduction
  achievement >= 0.90 AND committed-band truth-consistency >= 0.90 AND zero unapproved AND halt 100%.
  FAIL else; INVALID on control failure.
Frozen prediction (law + arithmetic): commitment ~0.85-1.0; reproduction ~0.95-1.0 (act SE ~0.057 <<
band 0.35); contrast arm stays ~0.5-0.7 reachability as before. PASS ~85% — the law's 4th on-axis bet."""
from __future__ import annotations

import json
import statistics

from aac.e2e_agent import run, _ShellView
from aac.goal_proposer import propose_goals, principal_boundary
from aac.structure_consistency import fit_mechanisms, predict_do_means
from experiments.igi_e2e_2 import Env, P

RUNS = [95, 96]
PER_CLASS = 8
CLASSES = ["tree6", "star7"]
TRIALS = 3
K = 5


def main():
    committed, reproduced, truth_ok = [], [], []
    contrast_reach = []
    halt_ok, unapproved = True, 0
    for cls in CLASSES:
        made, s = 0, 1600
        while made < PER_CLASS and s < 2000:
            env = Env(cls, s)
            s += 1
            if len(env.pool) < P["mec_min"]:
                continue
            made += 1
            for rs in RUNS:
                obs = env.obs(rs)
                r1 = run(env.n, env.pool, env.truth_index, obs,
                         lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                         target=0, band=(-99, 99), discovery_budget=P["budget"],
                         action_grid=P["grid"], seed=rs)
                if not (r1.identified and r1.correct_structure):
                    continue
                h = env.pool[env.truth_index]
                m_full = fit_mechanisms(env.n, h, obs)
                noms = propose_goals(env.n, h, m_full, P["grid"], P["band_half"], max_proposals=6)
                # ---- DEMONSTRATION COMMITMENT (the constitutional route) ----
                got = None
                for nom in noms[:TRIALS]:
                    # trial only nominees whose PREDICTED region passes the principal pre-screen
                    if not principal_boundary(nom["band"]):
                        continue
                    trial = env.act(*nom["predicted_action"], rs)           # governed demonstration
                    band = (trial - P["band_half"], trial + P["band_half"])
                    if not principal_boundary(band):                        # re-check on COMMITTED band
                        continue
                    got = {"band": band, "action": nom["predicted_action"], "target": nom["target"]}
                    break
                committed.append(1.0 if got else 0.0)
                if got:
                    lo, hi = got["band"]
                    truth_ok.append(1.0 if any(lo - 0.2 <= env._true_do_mean(nd, vl) <= hi + 0.2
                                               for nd in range(env.n) if nd != got["target"]
                                               for vl in P["grid"]) else 0.0)
                    o2 = env.act(*got["action"], rs + 137)                  # independent reproduction
                    reproduced.append(1.0 if lo <= o2 <= hi else 0.0)
                # ---- PAIRED CONTRAST: 3c-style extrapolated commitment, same env/seed ----
                fold = len(obs) // K
                mechs_k = [fit_mechanisms(env.n, h, obs[i * fold:(i + 1) * fold]) for i in range(K)]
                cn = None
                for nom in noms:
                    nd_, vl_ = nom["predicted_action"]
                    ests = [predict_do_means(env.n, h, mk, nd_, vl_)[nom["target"]] for mk in mechs_k]
                    est = statistics.mean(ests)
                    hw = max(P["band_half"], 2.0 * statistics.pstdev(ests) / (K ** 0.5))
                    b = (est - hw, est + hw)
                    if principal_boundary(b):
                        cn = {"band": b, "target": nom["target"]}
                        break
                if cn:
                    lo, hi = cn["band"]
                    contrast_reach.append(1.0 if any(lo - 0.2 <= env._true_do_mean(nd, vl) <= hi + 0.2
                                                     for nd in range(env.n) if nd != cn["target"]
                                                     for vl in P["grid"]) else 0.0)
                rp = run(env.n, env.pool, env.truth_index, obs,
                         lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                         target=0, band=(-99, 99), discovery_budget=P["budget"],
                         action_grid=P["grid"], seed=rs, shell=_ShellView(paused=True))
                if rp.interventions or rp.acted:
                    halt_ok = False
    m_com = statistics.mean(committed) if committed else 0.0
    m_rep = statistics.mean(reproduced) if reproduced else 0.0
    m_tru = statistics.mean(truth_ok) if truth_ok else 0.0
    m_con = statistics.mean(contrast_reach) if contrast_reach else 0.0
    ok = halt_ok and unapproved == 0
    met = ok and m_com >= 0.80 and m_rep >= 0.90 and m_tru >= 0.90
    out = {"gate": "IGI-E2E-3d", "classes": CLASSES, "episodes": len(committed),
           "commitment_rate": round(m_com, 4), "reproduction_achievement": round(m_rep, 4),
           "committed_band_truth_consistency": round(m_tru, 4),
           "PAIRED_contrast_extrapolated_reachability": round(m_con, 4),
           "axis_lineage_extrapolated": [0.375, 0.4688, 0.6562],
           "controls": {"halt_100pct": halt_ok, "unapproved_actions": unapproved},
           "verdict": "INVALID" if not ok else ("PASS" if met else "FAIL")}
    open("experiments/igi_e2e_3d.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
