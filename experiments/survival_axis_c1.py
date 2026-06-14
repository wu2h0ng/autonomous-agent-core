"""ADR-0028: survival-axis de-risk — does the confidence gate win a SECOND axis?

New axis = metabolic survival under exploration cost. Exploration forgoes reward, and
reward is budget (claim-1). So a confident agent that commits (gate) conserves budget,
while a fixed explorer wastes it and a fixed exploiter is slow after a shift. The gate
should Pareto-dominate {EXPLORER, EXPLOITER} jointly on (post-shift regret, budget).

Arms (baseline policy, no organ; only the temperature regime differs):
  EXPLORER  gate off, modulate off, base_temperature 2.0   (broad sampling always)
  EXPLOITER gate off, modulate off, base_temperature 0.05  (near-greedy always)
  GATED     confidence gate {kappa=0.5, temp_floor=0.1}    (adaptive)

Survival metric = FINAL BUDGET (env-validity revision r1, ADR-0028 §3): "steps survived"
saturated/degenerated — EXPLORER died before the first shift (no post-shift regret) while
EXPLOITER ran for hundreds of steps. Final budget is the continuous metabolic-reserve
margin (0 = dead), measurable for every arm. Metric-validity fix only; mechanisms untouched.

  calibrate : sweep {B0, m} on seeds 1000..1009; pick a cell where EXPLORER has low regret
              but low budget AND EXPLOITER high budget but high regret (validity precondition).
  (no arg)  : r-final on seeds 1010..1039 with the frozen cell.

Decision rule (ADR-0028 §4): D-1 GATED.budget>EXPLORER >=21/30 & p<0.05;
D-2 GATED.regret<EXPLOITER >=21/30 & p<0.05; D-3 no regression (bootstrap CI).

Run: PYTHONPATH=src python -m experiments.survival_axis_c1 [calibrate]
"""
from __future__ import annotations

import itertools
import math
import random
import sys

from aac.agent import Agent
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.structured_regime import StructuredRegimeEnv

try:
    from experiments._g7_common import WINDOW, wilcoxon_one_sided
    from experiments.confidence_gated_g10 import _bootstrap_ci_mean
except ModuleNotFoundError:  # direct script execution
    from _g7_common import WINDOW, wilcoxon_one_sided  # type: ignore[no-redef]
    from confidence_gated_g10 import _bootstrap_ci_mean  # type: ignore[no-redef]

N_ACTIONS = 8
STEPS = 2000
N_REGIMES = 5
NOISE = 0.3
PERIOD = 60
CAL_SEEDS = tuple(range(1000, 1010))
RFINAL_SEEDS = tuple(range(1010, 1040))

EXPLORER, EXPLOITER, GATED = "EXPLORER", "EXPLOITER", "GATED"
ARMS = (EXPLORER, EXPLOITER, GATED)

# Death before any post-shift window = worst-case adaptation; score it at the max
# single-step regret (reward_high - reward_low = 5) so regret stays finite per seed.
MAX_REGRET = 5.0

# FROZEN env-validity cell (cleanest budget separation; see ADR-0028 §3 / status log).
# NB: calibration showed the validity precondition does NOT hold in any cell — the greedy
# EXPLOITER has lower regret AND higher budget than the EXPLORER, so there is no explore-cost
# tradeoff. r-final is run on this cell only to record the full GATED-vs-arms picture.
B0_FROZEN = 100.0
M_FROZEN = 1.5


def _build(arm: str, seed: int, b0: float, m: float) -> Agent:
    shell = CorrigibilityShell()
    viability = ViabilityCore(
        budget=b0, metabolic_cost=m, capacity=b0 * 100.0, safe_budget=b0 * 0.6,
    )
    if arm == GATED:
        return Agent(
            n_actions=N_ACTIONS, shell=shell, rng=random.Random(8000 + seed),
            viability=viability, policy_gate=True, gate_kappa=0.5, gate_temp_floor=0.1,
        )
    agent = Agent(
        n_actions=N_ACTIONS, shell=shell, rng=random.Random(8000 + seed),
        viability=viability, modulate_relevance=False,
    )
    agent.policy.base_temperature = 2.0 if arm == EXPLORER else 0.05
    return agent


def _run(arm: str, seed: int, b0: float, m: float) -> tuple[float, float]:
    """Return (mean post-shift regret over measured windows, final budget)."""
    env = StructuredRegimeEnv(
        n_actions=N_ACTIONS, rng=random.Random(7000 + seed),
        n_regimes=N_REGIMES, period=PERIOD, noise=NOISE,
    )
    agent = _build(arm, seed, b0, m)
    regret_sum = 0.0
    regret_n = 0
    window_left = 0
    for _ in range(STEPS):
        rec = agent.step(env)
        if rec is None:  # budget hit death threshold
            break
        if env.just_shifted:
            window_left = WINDOW
        if window_left > 0:
            regret_sum += env.last_regret
            regret_n += 1
            window_left -= 1
    regret = (regret_sum / regret_n) if regret_n else MAX_REGRET
    return regret, max(0.0, agent.viability.budget)


def calibrate() -> None:
    print(f"survival-axis calibration (env-validity) seeds=1000..1009 period={PERIOD}")
    print(f"{'B0':>5} {'m':>5} | {'EXPLORER reg/bud':>18} | {'EXPLOITER reg/bud':>18} | validity")
    for b0, m in itertools.product((60.0, 100.0), (1.5, 2.0, 2.5)):
        er = [_run(EXPLORER, s, b0, m) for s in CAL_SEEDS]
        xr = [_run(EXPLOITER, s, b0, m) for s in CAL_SEEDS]
        e_reg = sum(r for r, _ in er) / len(er)
        e_bud = sum(b for _, b in er) / len(er)
        x_reg = sum(r for r, _ in xr) / len(xr)
        x_bud = sum(b for _, b in xr) / len(xr)
        valid = "OK" if (e_reg < x_reg and x_bud > e_bud) else "--"
        print(f"{b0:>5.0f} {m:>5.1f} | {e_reg:8.3f} / {e_bud:6.0f}  | "
              f"{x_reg:8.3f} / {x_bud:6.0f}  | {valid}")


def gate() -> None:
    b0, m = B0_FROZEN, M_FROZEN
    seeds = RFINAL_SEEDS
    n = len(seeds)
    reg: dict[str, list[float]] = {a: [] for a in ARMS}
    bud: dict[str, list[float]] = {a: [] for a in ARMS}
    print(f"survival-axis de-risk r-final (ADR-0028) seeds=1010..1039 B0={b0} m={m} period={PERIOD}")
    print(f"{'seed':>4} | " + " ".join(f"{a+' reg/bud':>18}" for a in ARMS))
    for s in seeds:
        row = {a: _run(a, s, b0, m) for a in ARMS}
        for a in ARMS:
            reg[a].append(row[a][0])
            bud[a].append(row[a][1])
        print(f"{s:>4} | " + " ".join(f"{row[a][0]:8.3f}/{row[a][1]:6.0f}   " for a in ARMS))

    mean_reg = {a: sum(reg[a]) / n for a in ARMS}
    mean_bud = {a: sum(bud[a]) / n for a in ARMS}
    g_gt_e_bud = sum(1 for i in range(n) if bud[GATED][i] > bud[EXPLORER][i])
    g_lt_x_reg = sum(1 for i in range(n) if reg[GATED][i] < reg[EXPLOITER][i])
    p_d1 = wilcoxon_one_sided([bud[GATED][i] - bud[EXPLORER][i] for i in range(n)])
    p_d2 = wilcoxon_one_sided([reg[EXPLOITER][i] - reg[GATED][i] for i in range(n)])
    # D-3 no-regression CIs: GATED vs EXPLORER on regret, GATED vs EXPLOITER on budget.
    ci_reg_lo, _ = _bootstrap_ci_mean([reg[EXPLORER][i] - reg[GATED][i] for i in range(n)])
    ci_bud_lo, _ = _bootstrap_ci_mean([bud[GATED][i] - bud[EXPLOITER][i] for i in range(n)])
    need = math.ceil(0.7 * n)

    print("\nAGGREGATE (regret lower=better, budget higher=better):")
    for a in ARMS:
        print(f"  {a:>9}: regret {mean_reg[a]:.3f}  budget {mean_bud[a]:.0f}")
    validity = mean_reg[EXPLORER] < mean_reg[EXPLOITER] and mean_bud[EXPLOITER] > mean_bud[EXPLORER]

    print("\nADR-0028 §4 DECISION RULE:")
    print(f"  validity (EXPLORER low-regret & EXPLOITER high-budget): {'OK' if validity else 'FAIL'}")
    d1 = g_gt_e_bud >= need and p_d1 < 0.05
    print(f"  D-1 GATED.budget>EXPLORER {g_gt_e_bud}/{n}(>= {need}) & p={p_d1:.4f}<0.05: {'PASS' if d1 else 'FAIL'}")
    d2 = g_lt_x_reg >= need and p_d2 < 0.05
    print(f"  D-2 GATED.regret<EXPLOITER {g_lt_x_reg}/{n}(>= {need}) & p={p_d2:.4f}<0.05: {'PASS' if d2 else 'FAIL'}")
    d3 = ci_reg_lo > -0.15 and ci_bud_lo > -0.05 * (b0 * 5.0)
    print(f"  D-3 no-regression: regret gap CIlo={ci_reg_lo:+.3f}, budget gap CIlo={ci_bud_lo:+.0f}: "
          f"{'PASS' if d3 else 'FAIL'}")

    verdict = "GREEN" if (validity and d1 and d2 and d3) else (
        "AMBER" if (validity and (d1 or d2)) else "RED")
    print(f"\n  SURVIVAL-AXIS VERDICT: {verdict}")
    if verdict == "GREEN":
        print("  Survival is a genuine second winning axis served by the gate →\n"
              "  recommend founder freeze a 2-axis G11 (reframe × survival).")
    elif verdict == "AMBER":
        print("  Gate wins one extra axis but not jointly; founder decides.")
    else:
        print("  No separable second axis here; ADR-0027 consolidation stands.")


if __name__ == "__main__":
    (calibrate if len(sys.argv) > 1 and sys.argv[1] == "calibrate" else gate)()
