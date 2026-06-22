"""ADR-0029: risk-calibration de-risk in a STATIONARY env (no adaptation component).

C3 and the survival axis were shadows of adaptation speed. Removing regime shifts leaves
only risk calibration: does the gate avoid a high-variance catastrophe trap better than the
cheap arms? Mechanism hypothesis (ADR-0029 §1): the gate keys on the leader's confidence,
not variance, so it should provide NO independent risk-aversion — broad exploration already
diversifies away from the trap. Predicted RED. The probe confirms empirically.

Env (stationary): 7 safe actions ~N(2.0,0.3); 1 trap action ~N(2.6,0.5) but returns
catastrophe -30 with prob p_cat. Trap has the highest apparent mean (tempting to greedy)
but the worst true EV. Tight budget; death at budget<=0. Metric: survival steps + catastrophes.

Arms reuse ADR-0028 temperature regimes: GATED / EXPLOITER (greedy) / EXPLORER (broad).

Decision rule (ADR-0029 §3): R-1 GATED.survival > max(EXPLOITER,EXPLORER) >=21/30 & p<0.05.
GREEN => independent risk axis; RED => 3rd single-lever confirmation.

Run: PYTHONPATH=src python -m experiments.risk_calibration_c1 [calibrate]
"""

from __future__ import annotations

import itertools
import math
import random
import sys

try:
    from experiments.survival_axis_c1 import EXPLOITER, EXPLORER, GATED, _build
    from experiments._g7_common import wilcoxon_one_sided
    from experiments.confidence_gated_g10 import _bootstrap_ci_mean
except ModuleNotFoundError:  # direct script execution
    from survival_axis_c1 import EXPLOITER, EXPLORER, GATED, _build  # type: ignore
    from _g7_common import wilcoxon_one_sided  # type: ignore[no-redef]
    from confidence_gated_g10 import _bootstrap_ci_mean  # type: ignore[no-redef]

N_ACTIONS = 8
STEPS = 2000
ARMS = (EXPLORER, EXPLOITER, GATED)
CAL_SEEDS = tuple(range(1090, 1100))
RFINAL_SEEDS = tuple(range(1100, 1130))

# FROZEN env-validity (see ADR-0029 §3 / status log).
B0_FROZEN = 40.0
M_FROZEN = 1.5
PCAT_FROZEN = 0.05


class StationaryRiskEnv:
    """No regime shifts. One high-variance catastrophe trap among safe actions."""

    def __init__(
        self,
        n_actions: int,
        rng: random.Random,
        p_cat: float,
        safe_mean: float = 2.0,
        safe_sd: float = 0.3,
        trap_mean: float = 2.6,
        trap_sd: float = 0.5,
        cat: float = -30.0,
        trap: int = 0,
    ) -> None:
        self.n_actions = n_actions
        self.rng = rng
        self.p_cat = p_cat
        self.safe_mean, self.safe_sd = safe_mean, safe_sd
        self.trap_mean, self.trap_sd, self.cat, self.trap = (
            trap_mean,
            trap_sd,
            cat,
            trap,
        )
        self.catastrophes = 0

    def act(self, action: int) -> float:
        if action == self.trap:
            if self.rng.random() < self.p_cat:
                self.catastrophes += 1
                return self.cat
            return self.trap_mean + self.rng.gauss(0.0, self.trap_sd)
        return self.safe_mean + self.rng.gauss(0.0, self.safe_sd)


def _run(arm: str, seed: int, b0: float, m: float, p_cat: float) -> tuple[int, int]:
    env = StationaryRiskEnv(N_ACTIONS, random.Random(7000 + seed), p_cat)
    agent = _build(arm, seed, b0, m)
    survived = 0
    for _ in range(STEPS):
        rec = agent.step(env)
        if rec is None:
            break
        survived += 1
    return survived, env.catastrophes


def calibrate() -> None:
    print("risk-calibration calibration (env-validity) seeds=1090..1099")
    print(
        f"{'B0':>5} {'m':>5} {'pcat':>5} | {'EXPLORER sv/cat':>16} | {'EXPLOITER sv/cat':>16} | {'GATED sv/cat':>16}"
    )
    for b0, m, pc in itertools.product((40.0,), (1.5,), (0.03, 0.05, 0.08)):
        rows = {a: [_run(a, s, b0, m, pc) for s in CAL_SEEDS] for a in ARMS}
        cells = {
            a: (
                sum(s for s, _ in rows[a]) / len(rows[a]),
                sum(c for _, c in rows[a]) / len(rows[a]),
            )
            for a in ARMS
        }
        print(
            f"{b0:>5.0f} {m:>5.1f} {pc:>5.2f} | "
            + " | ".join(f"{cells[a][0]:8.0f} /{cells[a][1]:5.1f}" for a in ARMS)
        )


def gate() -> None:
    b0, m, pc = B0_FROZEN, M_FROZEN, PCAT_FROZEN
    seeds = RFINAL_SEEDS
    n = len(seeds)
    sv: dict[str, list[float]] = {a: [] for a in ARMS}
    cat: dict[str, list[float]] = {a: [] for a in ARMS}
    print(
        f"risk-calibration de-risk r-final (ADR-0029) seeds=1100..1129 B0={b0} m={m} p_cat={pc}"
    )
    print(f"{'seed':>4} | " + " ".join(f"{a + ' sv/cat':>16}" for a in ARMS))
    for s in seeds:
        row = {a: _run(a, s, b0, m, pc) for a in ARMS}
        for a in ARMS:
            sv[a].append(float(row[a][0]))
            cat[a].append(float(row[a][1]))
        print(
            f"{s:>4} | " + " ".join(f"{row[a][0]:8d}/{row[a][1]:4d}    " for a in ARMS)
        )

    mean_sv = {a: sum(sv[a]) / n for a in ARMS}
    mean_cat = {a: sum(cat[a]) / n for a in ARMS}
    best_cheap = max(EXPLOITER, EXPLORER, key=lambda a: mean_sv[a])
    g_gt_best = sum(1 for i in range(n) if sv[GATED][i] > sv[best_cheap][i])
    p_r1 = wilcoxon_one_sided([sv[GATED][i] - sv[best_cheap][i] for i in range(n)])
    ci_lo, ci_hi = _bootstrap_ci_mean(
        [sv[GATED][i] - sv[best_cheap][i] for i in range(n)]
    )
    need = math.ceil(0.7 * n)

    print("\nAGGREGATE (survival higher=better, catastrophes lower=better):")
    for a in ARMS:
        print(f"  {a:>9}: survival {mean_sv[a]:.0f}  catastrophes {mean_cat[a]:.1f}")
    validity = mean_sv[EXPLOITER] < mean_sv[EXPLORER]  # greedy must suffer the trap

    print("\nADR-0029 §3 DECISION RULE:")
    print(
        f"  validity (greedy suffers trap: EXPLOITER survival < EXPLORER): {'OK' if validity else 'FAIL'}"
    )
    print(f"  best cheap arm on survival = {best_cheap} ({mean_sv[best_cheap]:.0f})")
    r1 = g_gt_best >= need and p_r1 < 0.05
    print(
        f"  R-1 GATED.survival > {best_cheap} {g_gt_best}/{n}(>= {need}) & p={p_r1:.4f}<0.05 "
        f"(gap CI [{ci_lo:+.0f},{ci_hi:+.0f}]): {'PASS' if r1 else 'FAIL'}"
    )

    verdict = "GREEN" if (validity and r1) else "RED"
    print(f"\n  RISK-CALIBRATION VERDICT: {verdict}")
    if verdict == "GREEN":
        print(
            "  Independent risk axis (no adaptation) → founder may reconsider a 2-axis G11."
        )
    else:
        print(
            "  Gate has no independent risk-aversion; broad exploration already diversifies\n"
            "  away from the trap. THIRD single-lever confirmation; G10 stands, close the hunt."
        )


if __name__ == "__main__":
    (calibrate if len(sys.argv) > 1 and sys.argv[1] == "calibrate" else gate)()
