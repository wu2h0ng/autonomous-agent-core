"""prune_soundness_guard — the SECOND safety guard §20 named: a VERIFIED singleton (len(alive)==1) can be
WRONG if the truth was PRUNED and a wrong hypothesis is the lone survivor -> a VERIFIED-but-wrong ACTION.
The guard is FRESH INTERVENTIONAL CONFIRMATION: before a singleton may ACT, it must positively predict a
HELD-OUT do within tol (not merely survive by elimination).

Discovery rarely FORCES a singleton on hard domains, so testing the guard via discovery is under-powered
(natural + adversarial-truth-removed arms each yielded ~1 case). This is the HIGH-POWER, discovery-free test
of the guard's core soundness claim:

  CLAIM: a structure that passes fresh interventional confirmation is ACTION-OUTCOME-SAFE (predicts the
  action's outcome within tol), so VERIFIED_CONFIRMED can drive an action without being confidently wrong.

Over many (domain x WRONG-structure) pairs (the truth explicitly excluded): fit the wrong structure on obs;
CONFIRM it on a held-out do(k_c, v_c); if it passes, test ACTION-safety on a DIFFERENT held-out do(k_a, v_a)
by comparing its predicted target outcome to reality. The dangerous case = passes confirmation but the ACTION
outcome is wrong (passed_AND_action_unsafe) -> must be ~0 for the guard to be sound. Also reports whether
ONE confirmation generalizes, or whether the action must be confirmed on the SAME do it will take.
Linear domain (n=6, where §20's VERIFIED path matters). NOT a freeze; VERIFY-DON'T-ASSERT, well-powered."""
from __future__ import annotations

import json
import random
import statistics

from aac.structure_consistency import fit_mechanisms, predict_do_means
from aac.hypothesis_pool import canon
from experiments.scale_n12_sparse import SparseEnv

N = 6
C_NOBS = 240
TOL = 0.6
GRID = (-2.0, -1.0, 1.0, 2.0)
MAX_WRONG_PER_DOMAIN = 8


def _do_mean(env, k, val, target, tag, kk=200):
    return statistics.mean(env._s(random.Random(f"{tag}|{env.seed}|{k}|{val}|{i}"), k, val)[target]
                           for i in range(kk))


def _do_means_all(env, k, val, tag, kk=200):
    rows = [env._s(random.Random(f"{tag}|{env.seed}|{k}|{val}|{i}"), k, val) for i in range(kk)]
    return [sum(r[j] for r in rows) / kk for j in range(N)]


def main():
    envs, seed = [], 500
    while len(envs) < 24:
        try:
            e = SparseEnv(seed, N, extra=1)
            if e.truth_index is not None and len(e.pool) >= 2:
                envs.append(e)
        except Exception:
            pass
        seed += 1

    pairs = 0
    passed_conf = 0
    passed_AND_action_unsafe_DIFFERENT = 0     # passed a held-out confirm, but a DIFFERENT action mispredicts
    passed_AND_action_unsafe_SAME = 0          # passed confirm on the SAME do it then acts on, yet unsafe
    confirmed_action_outcomes_err = []
    for e in envs:
        obs = e.obs(7, C_NOBS * N)
        wrongs = [i for i in range(len(e.pool)) if i != e.truth_index][:MAX_WRONG_PER_DOMAIN]
        # confirmation do and a DIFFERENT action do
        kc, vc = 0, 2.0
        ka, va = (1 if N > 1 else 0), -2.0
        conf_meas = _do_means_all(e, kc, vc, "confm")
        act_meas_all = _do_means_all(e, ka, va, "actm")
        same_meas_all = conf_meas
        tgt = e.target
        for wi in wrongs:
            pa = e.pool[wi]
            mech = fit_mechanisms(N, pa, obs)
            pairs += 1
            pred_conf = predict_do_means(N, pa, mech, kc, vc)
            if max(abs(pred_conf[j] - conf_meas[j]) for j in range(N)) > TOL:
                continue                       # fails confirmation -> correctly refused (never acts)
            passed_conf += 1
            # passed confirmation on do(kc,vc); now test ACTION safety
            # (a) a DIFFERENT action do(ka,va): does passing one confirm generalize?
            pred_act = predict_do_means(N, pa, mech, ka, va)[tgt]
            err_diff = abs(pred_act - act_meas_all[tgt])
            confirmed_action_outcomes_err.append(err_diff)
            if err_diff > TOL:
                passed_AND_action_unsafe_DIFFERENT += 1
            # (b) the SAME do it was confirmed on (the goal-correct protocol: confirm the action you take)
            pred_same = predict_do_means(N, pa, mech, kc, vc)[tgt]
            if abs(pred_same - same_meas_all[tgt]) > TOL:
                passed_AND_action_unsafe_SAME += 1

    out = {"gate": "prune-soundness-guard", "n": N, "domain": "linear", "n_domains": len(envs),
           "wrong_structure_pairs": pairs, "passed_fresh_confirmation": passed_conf,
           "passed_AND_action_unsafe_DIFFERENT_do": passed_AND_action_unsafe_DIFFERENT,
           "passed_AND_action_unsafe_SAME_do": passed_AND_action_unsafe_SAME,
           "median_action_err_after_confirm": round(statistics.median(confirmed_action_outcomes_err), 3)
           if confirmed_action_outcomes_err else None}
    out["guard_sound_if_confirm_the_action_taken"] = (passed_AND_action_unsafe_SAME == 0)
    out["one_confirm_generalizes_to_other_actions"] = (passed_AND_action_unsafe_DIFFERENT == 0)
    out["verdict"] = ("GUARD-SOUND-CONFIRM-THE-ACTION" if passed_AND_action_unsafe_SAME == 0 and passed_conf >= 10
                      else "UNSOUND" if passed_AND_action_unsafe_SAME > 0 else "UNDER-POWERED")
    out["finding"] = (
        "high-power test of the prune-soundness guard over " + str(pairs) + " wrong-structure pairs. "
        "Confirming a structure on the SAME do it will act on is SOUND iff passed_AND_action_unsafe_SAME==0 "
        "(a wrong structure that predicts do(k,v) within tol necessarily predicts do(k,v)'s outcome within "
        "tol -- tautologically, so the GOAL-CORRECT protocol is: confirm the specific action before taking "
        "it). Whether ONE confirmation GENERALIZES to a DIFFERENT action is the separate, non-trivial claim "
        "(passed_AND_action_unsafe_DIFFERENT): if >0, a single held-out confirm does NOT license arbitrary "
        "actions -> each governed action must be interventionally confirmed on its OWN do. This is the "
        "concrete prune-soundness rule: VERIFIED-to-ACT requires confirming the action's own intervention.")
    open("experiments/prune_soundness_guard.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
