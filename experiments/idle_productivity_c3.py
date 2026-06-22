"""C3 idle-productivity de-risk (ADR-0026): does the endogeny axis carry a directed signal?

G3 found idle-gain not established in a STRUCTURE-FREE env. This probe re-tests it in
the STRUCTURED env (recurring regime library) where route-C mechanisms win, asking the
narrow question: does the subject's directed idle drive (IdleDrives) lower post-idle
work regret more than (a) the agent just running its policy during idle [POLICY] and
(b) uniform-random idle activity [RANDOM]?

Fairness: all three arms call Agent.step every step, so StructuredRegimeEnv.act draws
exactly one noise sample per step and the forced shift is keyed on the loop step => env
randomness (regimes AND noise) is identical across arms. (RANDOM uses its own rng for the
idle choice; the only residual is that POLICY consumes the agent rng during idle — a
mean-neutral sampling effect, not a regime/noise confound.)

Schedule: work 40 / idle 8; a recurring regime shift is forced at the first idle step of
every cycle, so the following work faces a regime the idle window could have learned.
Metric: mean post-idle work regret over the first 10 work steps of each cycle >= 1.

Decision rule (ADR-0026 s4, frozen): C3-A DIRECTED<POLICY >=21/30 & p<0.05 & bootstrapCI>0;
C3-B DIRECTED<RANDOM >=21/30 & p<0.05. Verdict GREEN/AMBER/RED informs ADR-0025/G11.

Run: PYTHONPATH=src python -m experiments.idle_productivity_c3
"""

from __future__ import annotations

import math
import random

from aac.agent import Agent
from aac.idle_drives import IdleDrives
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.idle_windows import IdleWindowEnv
from envs.structured_regime import StructuredRegimeEnv

try:
    from experiments._g7_common import wilcoxon_one_sided
    from experiments.confidence_gated_g10 import _bootstrap_ci_mean
except ModuleNotFoundError:  # direct script execution
    from _g7_common import wilcoxon_one_sided  # type: ignore[no-redef]
    from confidence_gated_g10 import _bootstrap_ci_mean  # type: ignore[no-redef]

N_ACTIONS = 8
WORK, IDLE = 40, 8
CYCLE = WORK + IDLE
POST_IDLE_K = 10
STEPS = 2000
N_REGIMES = 5
NOISE = 0.3
SEEDS = tuple(range(900, 930))


class _RandomIdleDrives:
    """Undirected idle: same step path as IdleDrives, uniform-random choice.

    Uses its OWN rng (not the agent rng), so env randomness stays identical across arms.
    """

    def __init__(self, n_actions: int, rng: random.Random) -> None:
        self.n_actions = n_actions
        self.rng = rng

    def observe(self, action: int) -> None:
        pass

    def select(self, model, forbidden: frozenset[int] = frozenset()) -> tuple[int, str]:
        cands = [a for a in range(self.n_actions) if a not in forbidden] or list(
            range(self.n_actions)
        )
        return self.rng.choice(cands), "random"


def _run(seed: int, idle_factory) -> float:
    inner = StructuredRegimeEnv(
        n_actions=N_ACTIONS,
        rng=random.Random(7000 + seed),
        n_regimes=N_REGIMES,
        period=10**9,
        noise=NOISE,
    )
    env = IdleWindowEnv(inner, work_period=WORK, idle_period=IDLE)
    shell = CorrigibilityShell()
    viability = ViabilityCore(
        budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0
    )
    agent = Agent(
        n_actions=N_ACTIONS,
        shell=shell,
        rng=random.Random(8000 + seed),
        viability=viability,
        idle_drives=idle_factory(seed),
    )
    total = 0.0
    n = 0
    for step in range(STEPS):
        phase = step % CYCLE
        cycle = step // CYCLE
        if phase == WORK:  # first idle step: force a recurring shift
            env.force_regime_change()
        record = agent.step(env)
        if (
            record is not None
            and not record["idle"]
            and cycle >= 1
            and phase < POST_IDLE_K
        ):
            total += inner.last_regret
            n += 1
    return total / n if n else float("inf")


def main() -> None:
    arms = {
        "DIRECTED": lambda s: IdleDrives(n_actions=N_ACTIONS),
        "RANDOM": lambda s: _RandomIdleDrives(N_ACTIONS, random.Random(4000 + s)),
        "POLICY": lambda s: None,
    }
    print(
        f"C3 idle-productivity de-risk (ADR-0026) seeds=900..929 steps={STEPS} "
        f"work={WORK} idle={IDLE} postK={POST_IDLE_K}"
    )
    print(f"{'seed':>4} | {'DIRECTED':>9} {'RANDOM':>9} {'POLICY':>9}")
    areas: dict[str, list[float]] = {x: [] for x in arms}
    for seed in SEEDS:
        row = {x: _run(seed, f) for x, f in arms.items()}
        for x, v in row.items():
            areas[x].append(v)
        print(f"{seed:>4} | " + " ".join(f"{row[x]:9.3f}" for x in arms))

    n = len(SEEDS)
    mean = {x: sum(v) / n for x, v in areas.items()}
    d, r, p = areas["DIRECTED"], areas["RANDOM"], areas["POLICY"]
    d_lt_p = sum(1 for i in range(n) if d[i] < p[i])
    d_lt_r = sum(1 for i in range(n) if d[i] < r[i])
    wil_p = wilcoxon_one_sided([p[i] - d[i] for i in range(n)])  # H1: POLICY > DIRECTED
    wil_r = wilcoxon_one_sided(
        [r[i] - d[i] for i in range(n)]
    )  # H1: RANDOM  > DIRECTED
    red_p = [p[i] - d[i] for i in range(n)]
    ci_lo, ci_hi = _bootstrap_ci_mean(red_p)
    med_p = sorted(red_p)[n // 2]
    need = math.ceil(0.7 * n)  # 21/30

    print("\nAGGREGATE (mean post-idle work regret, lower=better):")
    for x in arms:
        print(f"  {x}: {mean[x]:.3f}")
    print(
        f"  DIRECTED vs POLICY: mean reduction {mean['POLICY'] - mean['DIRECTED']:+.3f} "
        f"(median {med_p:+.3f}), bootstrap95%CI [{ci_lo:+.3f}, {ci_hi:+.3f}]"
    )
    print(
        f"  DIRECTED vs RANDOM: mean reduction {mean['RANDOM'] - mean['DIRECTED']:+.3f}"
    )

    print("\nC3 PRE-REGISTERED DECISION RULE (ADR-0026 §4):")
    a = d_lt_p >= need and wil_p < 0.05 and ci_lo > 0
    print(
        f"  C3-A DIRECTED<POLICY {d_lt_p}/{n}(>= {need}) & p={wil_p:.4f}<0.05 & CIlo={ci_lo:+.3f}>0: "
        f"{'PASS' if a else 'FAIL'}"
    )
    b = d_lt_r >= need and wil_r < 0.05
    print(
        f"  C3-B DIRECTED<RANDOM {d_lt_r}/{n}(>= {need}) & p={wil_r:.4f}<0.05: "
        f"{'PASS' if b else 'FAIL'}"
    )
    print("  C3-C6/C7: see tests/test_idle_productivity_c3.py")

    verdict = "GREEN" if (a and b) else "AMBER" if a else "RED"
    print(f"\n  C3 VERDICT: {verdict}")
    if verdict == "GREEN":
        print(
            "  Endogeny is a directed win in structure → C1 includes the idle axis with IdleDrives."
        )
    elif verdict == "AMBER":
        print(
            "  Idle activity helps but direction does not (G3 pattern persists in structure) →\n"
            "  C1 may use idle activity but must not claim a directed advantage."
        )
    else:
        print(
            "  Idle yields no post-work gain even in structure →\n"
            "  drop the endogeny axis from C1; rely on reframe / survival / robustness."
        )


if __name__ == "__main__":
    main()
