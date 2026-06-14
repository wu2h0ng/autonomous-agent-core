"""G10 completeness check (ADR-0030): does the P0 subject-side win survive the
empirical traps that could make the -40% misleading?

Arms (frozen G9 gate {kappa=0.5, temp_floor=0.1}; base_temperature additive):
  A0 baseline+none | A1 baseline+O1 | B-temp baseline+fixed-low-temp+none | P0 gated+none

Settings:
  A proxy   : StructuredRegimeEnv, budget=1e9/cost=0; metrics window-area, whole-run
              mean regret, total reward (T1 vs B-temp, T2 metric spillover, margin)
  B stake   : finite budget + positive metabolic_cost; metric survival steps (T3)
  C nostruct: StalenessEnv (no transferable structure) (T5b structure theft)
  D spectrum: n_regimes x noise (T5a)

  calibrate : pick B-temp's fixed base_temperature on disjoint seeds 970..989.
  (no arg)  : the pre-committed completeness r-final, seeds 1000..1029.

Run: PYTHONPATH=src python -m experiments.completeness_g10 [calibrate]
"""
from __future__ import annotations

import random
import sys

from aac.agent import Agent
from aac.prior_organ_o1 import ResetScaffoldOrgan
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.staleness import StalenessEnv
from envs.structured_regime import StructuredRegimeEnv

try:
    from experiments._g7_common import N_ACTIONS, STEPS, WINDOW, wilcoxon_one_sided
except ModuleNotFoundError:  # direct script execution
    from _g7_common import N_ACTIONS, STEPS, WINDOW, wilcoxon_one_sided  # type: ignore[no-redef]

CAL_SEEDS = tuple(range(970, 990))
RFINAL_SEEDS = tuple(range(1000, 1030))
SPECTRUM_SEEDS = tuple(range(1000, 1010))

# FROZEN via calibrate (2026-06-14, seeds 970..989): lowest mean area among
# base_temperature in {0.01..0.3} = B-temp's strongest config (anti-straw-man).
BTEMP_FROZEN = 0.03
# G9 frozen gate (unchanged).
GK, GTF = 0.5, 0.1


def _run(seed, *, organ, gate, base_temp, nostruct=False, n_regimes=5, noise=0.3,
         budget=1e9, cost=0.0, steps=STEPS):
    if nostruct:
        env = StalenessEnv(n_actions=N_ACTIONS, rng=random.Random(7000 + seed), noise=noise)
    else:
        env = StructuredRegimeEnv(n_actions=N_ACTIONS, rng=random.Random(7000 + seed),
                                  n_regimes=n_regimes, noise=noise)
    shell = CorrigibilityShell()
    viability = ViabilityCore(budget=budget, metabolic_cost=cost, capacity=100.0, safe_budget=50.0)
    agent = Agent(n_actions=N_ACTIONS, shell=shell, rng=random.Random(8000 + seed),
                  viability=viability, prior_organ=organ(), policy_gate=gate,
                  gate_kappa=GK, gate_temp_floor=GTF, base_temperature=base_temp)
    area = 0.0
    wl = 0
    treward = 0.0
    tregret = 0.0
    alive = 0
    for _ in range(steps):
        rec = agent.step(env)
        if rec is None:
            break
        alive += 1
        treward += rec["reward"]
        tregret += env.last_regret
        if env.just_shifted:
            wl = WINDOW
        if wl > 0:
            area += env.last_regret
            wl -= 1
    return {"area": area, "mean_regret": tregret / max(1, alive),
            "total_reward": treward, "alive": alive}


_NONE = (lambda: None)
_O1 = (lambda: ResetScaffoldOrgan())


def _arm(seed, name, **kw):
    return _run(seed, **kw)


def _mean(xs):
    return sum(xs) / len(xs)


def _wins(a, b):  # count of a_i < b_i  (lower area is better)
    return sum(1 for i in range(len(a)) if a[i] < b[i])


def _bootstrap_ci(diffs, n=2000, seed=12345):
    rng = random.Random(seed)
    means = []
    m = len(diffs)
    for _ in range(n):
        s = sum(diffs[rng.randrange(m)] for _ in range(m)) / m
        means.append(s)
    means.sort()
    return means[int(0.025 * n)], means[int(0.975 * n)]


def calibrate():
    print(f"B-temp calibration | seeds {CAL_SEEDS[0]}..{CAL_SEEDS[-1]} (structured, proxy)")
    rows = []
    for bt in (0.01, 0.02, 0.03, 0.05, 0.1, 0.15, 0.2, 0.3):
        m = _mean([_run(s, organ=_NONE, gate=False, base_temp=bt)["area"] for s in CAL_SEEDS])
        rows.append((m, bt))
        print(f"  base_temperature={bt} -> area {m:.1f}")
    rows.sort()
    print(f"\nFROZEN B-temp base_temperature = {rows[0][1]}  (area {rows[0][0]:.1f})")
    print("  (set BTEMP_FROZEN)")


def gate():
    seeds = RFINAL_SEEDS
    print(f"G10 COMPLETENESS r-final (ADR-0030) seeds {seeds[0]}..{seeds[-1]}  "
          f"B-temp base_temp={BTEMP_FROZEN}  gate {{kappa={GK},floor={GTF}}}\n")

    # ---- Setting A: proxy metrics (T1, T2, margin) ----
    A = {k: {m: [] for m in ("area", "mean_regret", "total_reward")} for k in ("A0", "A1", "Bt", "P0")}
    cfg = {"A0": dict(organ=_NONE, gate=False, base_temp=0.3),
           "A1": dict(organ=_O1, gate=False, base_temp=0.3),
           "Bt": dict(organ=_NONE, gate=False, base_temp=BTEMP_FROZEN),
           "P0": dict(organ=_NONE, gate=True, base_temp=0.3)}
    for s in seeds:
        for k, c in cfg.items():
            r = _run(s, **c)
            for m in A[k]:
                A[k][m].append(r[m])
    print("== Setting A (proxy) ==  arm: window-area | whole-run mean-regret | total-reward")
    for k in ("A0", "A1", "Bt", "P0"):
        print(f"  {k:3s}: {_mean(A[k]['area']):8.1f} | {_mean(A[k]['mean_regret']):.4f} | {_mean(A[k]['total_reward']):9.1f}")

    p0a, a0a, a1a, bta = A["P0"]["area"], A["A0"]["area"], A["A1"]["area"], A["Bt"]["area"]
    ct1_wins = _wins(p0a, bta)
    ct1_p = wilcoxon_one_sided([bta[i] - p0a[i] for i in range(len(seeds))])
    margin = _mean(p0a) <= 0.8 * _mean(a1a)
    # T2: directions agree (P0 better on mean-regret and total-reward vs A0 and B-temp)
    t2 = (_mean(A["P0"]["mean_regret"]) < min(_mean(A["A0"]["mean_regret"]), _mean(A["Bt"]["mean_regret"]))
          and _mean(A["P0"]["total_reward"]) > max(_mean(A["A0"]["total_reward"]), _mean(A["Bt"]["total_reward"])))
    print(f"\n  margin  mean(P0)={_mean(p0a):.1f} <= {0.8*_mean(a1a):.1f}=0.8*A1: {'PASS' if margin else 'FAIL'}")
    print(f"  T1 (vs B-temp)  P0<B-temp {ct1_wins}/{len(seeds)} & Wilcoxon p={ct1_p:.6f}: "
          f"{'PASS' if (ct1_wins>=27 and ct1_p<0.01) else 'FAIL'}")
    print(f"  T2 (metric spillover)  P0 best on mean-regret AND total-reward: {'PASS' if t2 else 'FAIL'}")
    print(f"  sanity  P0<A0 {_wins(p0a,a0a)}/{len(seeds)}  P0<A1 {_wins(p0a,a1a)}/{len(seeds)}")
    ci = _bootstrap_ci([a1a[i] - p0a[i] for i in range(len(seeds))])
    print(f"  effect vs A1: mean reduction {_mean(a1a)-_mean(p0a):.1f}  bootstrap95 CI [{ci[0]:.1f},{ci[1]:.1f}]")

    # ---- Setting B: real stake survival (T3) ----
    print("\n== Setting B (real stake: budget=60, metabolic_cost=2.0) ==  arm: median survival steps")
    surv = {}
    for k, c in (("A0", dict(organ=_NONE, gate=False, base_temp=0.3)),
                 ("Bt", dict(organ=_NONE, gate=False, base_temp=BTEMP_FROZEN)),
                 ("P0", dict(organ=_NONE, gate=True, base_temp=0.3))):
        surv[k] = [_run(s, budget=60.0, cost=2.0, **c)["alive"] for s in seeds]
        srt = sorted(surv[k])
        print(f"  {k:3s}: median {srt[len(srt)//2]:5d}  mean {_mean(surv[k]):7.1f}")
    ct3_a0 = wilcoxon_one_sided([surv["P0"][i] - surv["A0"][i] for i in range(len(seeds))])
    ct3_bt = wilcoxon_one_sided([surv["P0"][i] - surv["Bt"][i] for i in range(len(seeds))])
    ct3 = ct3_a0 < 0.05 and ct3_bt < 0.05
    print(f"  T3 (stake)  P0 survives > A0 (p={ct3_a0:.6f}) AND > B-temp (p={ct3_bt:.6f}): "
          f"{'PASS' if ct3 else 'FAIL'}")

    # ---- Setting C: unstructured env (T5b) ----
    print("\n== Setting C (StalenessEnv: no transferable structure) ==  arm: window-area")
    nos = {}
    for k, c in (("A0", dict(organ=_NONE, gate=False, base_temp=0.3)),
                 ("Bt", dict(organ=_NONE, gate=False, base_temp=BTEMP_FROZEN)),
                 ("P0", dict(organ=_NONE, gate=True, base_temp=0.3))):
        nos[k] = [_run(s, nostruct=True, **c)["area"] for s in seeds]
        print(f"  {k:3s}: {_mean(nos[k]):8.1f}")
    ct5b_p = wilcoxon_one_sided([nos["A0"][i] - nos["P0"][i] for i in range(len(seeds))])
    adv = 1 - _mean(nos["P0"]) / _mean(nos["A0"])
    verdict5b = "GENERAL FIX (not structure theft)" if (adv > 0 and ct5b_p < 0.01) else "weak/none -> possible structure dependence"
    print(f"  T5b  P0 vs A0 advantage {adv:.3f}, p={ct5b_p:.6f} -> {verdict5b}")

    # ---- Setting D: spectrum (T5a) ----
    print("\n== Setting D (spectrum, seeds 1000..1009) ==  P0 advantage vs A1 / vs B-temp")
    for nr in (2, 5, 10, 20):
        for ns in (0.1, 0.3, 0.5, 1.0):
            p0 = _mean([_run(s, organ=_NONE, gate=True, base_temp=0.3, n_regimes=nr, noise=ns)["area"] for s in SPECTRUM_SEEDS])
            a1 = _mean([_run(s, organ=_O1, gate=False, base_temp=0.3, n_regimes=nr, noise=ns)["area"] for s in SPECTRUM_SEEDS])
            bt = _mean([_run(s, organ=_NONE, gate=False, base_temp=BTEMP_FROZEN, n_regimes=nr, noise=ns)["area"] for s in SPECTRUM_SEEDS])
            print(f"  nr={nr:2d} noise={ns:.1f}: vsA1 {1-p0/a1:+.3f}  vsBt {1-p0/bt:+.3f}")

    # ---- Completeness verdict ----
    crit_t1 = ct1_wins >= 27 and ct1_p < 0.01
    complete = crit_t1 and ct3 and margin and t2
    print("\nCOMPLETENESS VERDICT (T1 & T3 & margin & T2 are the flip-the-conclusion gates):")
    print(f"  T1 {'PASS' if crit_t1 else 'FAIL'} | T3 {'PASS' if ct3 else 'FAIL'} | "
          f"margin {'PASS' if margin else 'FAIL'} | T2 {'PASS' if t2 else 'FAIL'} | "
          f"T5b {verdict5b}")
    print(f"  => P0 stands as a real adaptive, stake-grounded mechanism: {'YES' if complete else 'NO'}")
    if not crit_t1:
        print("  T1 FAIL: a fixed low temperature suffices -> the gate's adaptivity is a red herring; "
              "the honest result is 'baseline policy was mis-tuned' (bitter-lesson variant). "
              "Undercuts ADR-0024/G10's 'new mechanism' framing.")
    if not ct3:
        print("  T3 FAIL: the -40% does not transfer to survival -> toy-metric artifact (stake-first section 2.6).")


if __name__ == "__main__":
    (calibrate if len(sys.argv) > 1 and sys.argv[1] == "calibrate" else gate)()
