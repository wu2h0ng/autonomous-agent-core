"""ADR-0031 / RR-0019 PREDICTION 1: residual calibrator vs frozen G10.

Run types:
  calibrate : choose (lambda, eta) on seeds 1200..1219 by maximizing PR-B vs A1.
  prereg    : print the canonical prereg lock hash after frozen params are written.
  r-final   : run the one-shot evaluation on seeds 1300..1329 (default).

The candidate is PR = frozen G10 gate + residual calibrator. The incumbent is P0
= frozen G10 gate without calibrator. A decisive PR win wounds RR-0019 Claim 1/3 and
is founder-reserved; a powered null corroborates the channel-decomposition prediction.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import sys
from pathlib import Path
from typing import Callable

from aac.agent import Agent
from aac.prior_organ_o1 import ResetScaffoldOrgan
from aac.residual_calibrator import ResidualCalibrator
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.structured_regime import StructuredRegimeEnv

try:
    from experiments._g7_common import N_ACTIONS, STEPS, WINDOW, wilcoxon_one_sided
except ModuleNotFoundError:  # direct script execution
    from _g7_common import N_ACTIONS, STEPS, WINDOW, wilcoxon_one_sided  # type: ignore[no-redef]

CAL_SEEDS = tuple(range(1200, 1220))
RFINAL_SEEDS = tuple(range(1300, 1330))

GK, GTF = 0.5, 0.1
BASE_TEMP = 0.3

# Filled by the calibration run before r-final. These initial values are placeholders
# until ADR-0031 section 7 is updated and the prereg hash is recorded.
LAMBDA_FROZEN = 0.8
ETA_FROZEN = 0.1

ADR = Path("docs/adr/ADR-0031-prediction1-residual-calibrator-vs-g10.md")
RESULT_JSON = Path("experiments/prediction1_residual_calibrator.result.json")


def _none():
    return None


def _o1():
    return ResetScaffoldOrgan()


def _cal(lambda_: float = LAMBDA_FROZEN, eta: float = ETA_FROZEN):
    return ResidualCalibrator(n_actions=N_ACTIONS, lambda_=lambda_, eta=eta)


def _run(
    seed: int,
    *,
    organ_factory: Callable[[], object | None],
    gate: bool,
    calibrator_factory: Callable[[], ResidualCalibrator | None] = lambda: None,
) -> float:
    env = StructuredRegimeEnv(n_actions=N_ACTIONS, rng=random.Random(7000 + seed))
    shell = CorrigibilityShell()
    viability = ViabilityCore(
        budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0
    )
    agent = Agent(
        n_actions=N_ACTIONS,
        shell=shell,
        rng=random.Random(8000 + seed),
        viability=viability,
        prior_organ=organ_factory(),
        policy_gate=gate,
        gate_kappa=GK,
        gate_temp_floor=GTF,
        base_temperature=BASE_TEMP,
        residual_calibrator=calibrator_factory(),
    )
    area = 0.0
    wl = 0
    for _ in range(STEPS):
        agent.step(env)
        if env.just_shifted:
            wl = WINDOW
        if wl > 0:
            area += env.last_regret
            wl -= 1
    return area


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _wins(a: list[float], b: list[float]) -> int:
    return sum(1 for i in range(len(a)) if a[i] < b[i])


def _bootstrap_ci(
    values: list[float], n: int = 5000, seed: int = 12345
) -> tuple[float, float]:
    rng = random.Random(seed)
    m = len(values)
    means = sorted(
        sum(values[rng.randrange(m)] for _ in range(m)) / m for _ in range(n)
    )
    return means[int(0.025 * n)], means[int(0.975 * n)]


def calibrate() -> None:
    print(f"PRED1 calibration seeds {CAL_SEEDS[0]}..{CAL_SEEDS[-1]}")
    a1 = [_run(s, organ_factory=_o1, gate=False) for s in CAL_SEEDS]
    grid_l = (0.1, 0.2, 0.3, 0.5, 0.8, 1.0)
    grid_e = (0.1, 0.2, 0.3, 0.5, 0.8, 1.0)
    rows: list[tuple[float, float, float, float]] = []
    for lambda_ in grid_l:
        for eta in grid_e:
            prb = [
                _run(
                    s,
                    organ_factory=_none,
                    gate=False,
                    calibrator_factory=lambda lam=lambda_, e=eta: _cal(lam, e),
                )
                for s in CAL_SEEDS
            ]
            benefit = 1.0 - _mean(prb) / _mean(a1)
            rows.append((benefit, _mean(prb), lambda_, eta))
            print(
                f"  lambda={lambda_:.1f} eta={eta:.1f} "
                f"PR-B={_mean(prb):.1f} benefit_vs_A1={benefit:+.3f}"
            )
    rows.sort(reverse=True)
    best = rows[0]
    print(
        "\nFROZEN candidate params: "
        f"lambda={best[2]:.1f} eta={best[3]:.1f} "
        f"(PR-B area {best[1]:.1f}, benefit {best[0]:+.3f})"
    )


def prereg_hash() -> str:
    """Hash the canonical prereg artifact, stable after the hash is written."""
    parts: list[tuple[str, str]] = []
    for path in (
        ADR,
        Path("src/aac/residual_calibrator.py"),
        Path("src/aac/agent.py"),
        Path("experiments/prediction1_residual_calibrator.py"),
        Path("tests/test_residual_calibrator.py"),
    ):
        text = path.read_text(encoding="utf-8")
        if path == ADR:
            text = re.sub(
                r"prereg lock hash\s*=.*",
                "prereg lock hash            = <LOCKED>",
                text,
            )
        parts.append((path.as_posix(), text))
    blob = "\n\n".join(f"--- {p} ---\n{t}" for p, t in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def prereg() -> None:
    print(prereg_hash())


def rfinal() -> None:
    seeds = RFINAL_SEEDS
    lock = prereg_hash()
    arms = {
        "A0": lambda s: _run(s, organ_factory=_none, gate=False),
        "A1": lambda s: _run(s, organ_factory=_o1, gate=False),
        "P0": lambda s: _run(s, organ_factory=_none, gate=True),
        "PR": lambda s: _run(
            s, organ_factory=_none, gate=True, calibrator_factory=_cal
        ),
        "PR-B": lambda s: _run(
            s, organ_factory=_none, gate=False, calibrator_factory=_cal
        ),
    }
    print(
        f"PREDICTION 1 r-final seeds {seeds[0]}..{seeds[-1]} "
        f"lambda={LAMBDA_FROZEN} eta={ETA_FROZEN} prereg={lock[:12]}"
    )
    areas = {name: [] for name in arms}
    for s in seeds:
        row = {name: fn(s) for name, fn in arms.items()}
        for name, value in row.items():
            areas[name].append(value)
        print(f"{s}: " + " ".join(f"{name}={row[name]:.1f}" for name in arms))

    mean = {name: _mean(values) for name, values in areas.items()}
    n = len(seeds)
    need = math.ceil(0.9 * n)
    pr_vs_p0 = [areas["P0"][i] - areas["PR"][i] for i in range(n)]
    prb_vs_a1 = [areas["A1"][i] - areas["PR-B"][i] for i in range(n)]
    pr_margin = 1.0 - mean["PR"] / mean["P0"]
    prb_margin = 1.0 - mean["PR-B"] / mean["A1"]
    pr_wins = _wins(areas["PR"], areas["P0"])
    pr_p = wilcoxon_one_sided(pr_vs_p0)
    pr_ci = _bootstrap_ci(pr_vs_p0)
    prb_ci = _bootstrap_ci(prb_vs_a1)

    decisive = pr_margin >= 0.20 and pr_wins >= need and pr_p < 0.01 and pr_ci[0] > 0
    if decisive:
        verdict = "PRED1-FALSIFIED"
    elif pr_margin > 0.0:
        verdict = "GREY"
    else:
        verdict = "PRED1-HOLDS"

    print("\nAGGREGATE:")
    for name in arms:
        print(f"  {name}: {mean[name]:.1f}")
    print("\nPREDICTION 1 GATE:")
    print(
        f"  PR vs P0 margin={pr_margin:+.3f}; wins={pr_wins}/{n}; "
        f"p={pr_p:.6f}; CI=[{pr_ci[0]:.1f},{pr_ci[1]:.1f}]"
    )
    print(
        f"  PR-B vs A1 margin={prb_margin:+.3f}; CI=[{prb_ci[0]:.1f},{prb_ci[1]:.1f}]"
    )
    print(f"  => {verdict}")
    if verdict == "PRED1-FALSIFIED":
        print("  Founder-reserved disposition: do not self-dispose or retune.")

    RESULT_JSON.write_text(
        json.dumps(
            {
                "verdict": verdict,
                "prereg_hash": lock,
                "lambda": LAMBDA_FROZEN,
                "eta": ETA_FROZEN,
                "means": mean,
                "pr_vs_p0": {
                    "margin": pr_margin,
                    "wins": pr_wins,
                    "p": pr_p,
                    "bootstrap_ci": pr_ci,
                },
                "prb_vs_a1": {
                    "margin": prb_margin,
                    "bootstrap_ci": prb_ci,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "r-final"
    if cmd == "calibrate":
        calibrate()
    elif cmd == "prereg":
        prereg()
    elif cmd in {"r-final", "rfinal"}:
        rfinal()
    else:
        raise SystemExit(
            "usage: python -m experiments.prediction1_residual_calibrator [calibrate|prereg|r-final]"
        )
