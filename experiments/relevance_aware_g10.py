"""ADR-0034: relevance-aware G10 theory test (B/R/K attribution).

Run types:
  calibrate : choose one global RSTAR triple on seeds 1400..1419.
  r-final   : evaluate PRED-A'/B'/C' on seeds 1500..1529 using the frozen RSTAR.
  both      : calibrate, write the freeze artifact, then run r-final.

This is explanatory only. It does not retune P0 or reopen G11/C1.
"""

from __future__ import annotations

import itertools
import json
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from aac.agent import Agent
from aac.prior_organ_o1 import ResetScaffoldOrgan
from aac.relevance import RelevanceField
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.structured_regime import StructuredRegimeEnv

try:
    from experiments._g7_common import N_ACTIONS, STEPS, WINDOW, wilcoxon_one_sided
except ModuleNotFoundError:  # direct script execution
    from _g7_common import N_ACTIONS, STEPS, WINDOW, wilcoxon_one_sided  # type: ignore[no-redef]


CALIBRATION_SEEDS = tuple(range(1400, 1420))
RFINAL_SEEDS = tuple(range(1500, 1530))
GK, GTF = 0.5, 0.1
BASE_TEMP = 0.3
BTEMP = 0.03
PERIOD = 40
N_REGIMES = 5
RSTAR_FREEZE_JSON = Path("experiments/relevance_aware_g10.rstar.json")
RESULT_JSON = Path("experiments/relevance_aware_g10.result.json")


@dataclass(frozen=True, order=True)
class Condition:
    severity: float
    noise: float

    @property
    def key(self) -> str:
        return f"severity={self.severity:.2f},noise={self.noise:.2f}"


@dataclass(frozen=True, order=True)
class RStarParams:
    base_temperature: float
    inertia: float
    surprise_gain: float


@dataclass(frozen=True)
class RunResult:
    area: float
    diagnostics: dict[str, float]


@dataclass(frozen=True)
class CalibrationResult:
    best_params: RStarParams
    best_mean_area: float
    seeds: tuple[int, ...]
    conditions: tuple[Condition, ...]
    rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class EvaluationResult:
    frozen_rstar: RStarParams
    seeds: tuple[int, ...]
    conditions: tuple[Condition, ...]
    means: dict[str, dict[str, float]]
    pair_stats: dict[str, dict[str, dict[str, float]]]
    diagnostics: dict[str, dict[str, dict[str, float]]]
    predictions: dict[str, Any]


RSTAR_GRID = tuple(
    RStarParams(base_temperature=bt, inertia=inertia, surprise_gain=sg)
    for bt, inertia, sg in itertools.product(
        (0.03, 0.10, 0.30),
        (0.25, 0.50, 0.75),
        (1.0, 2.0, 4.0),
    )
)


def calibration_conditions() -> tuple[Condition, ...]:
    """Unique union of ADR-0034 D3 PRED-A' and PRED-B' conditions."""
    return (
        Condition(severity=0.10, noise=0.30),
        Condition(severity=1.00, noise=0.30),
        Condition(severity=1.00, noise=0.10),
        Condition(severity=1.00, noise=0.50),
        Condition(severity=1.00, noise=1.00),
    )


def _none() -> None:
    return None


def _o1() -> ResetScaffoldOrgan:
    return ResetScaffoldOrgan()


def _agent(seed: int, arm: str, rstar_params: RStarParams | None) -> Agent:
    gate = False
    organ_factory = _none
    base_temperature = BASE_TEMP
    relevance = RelevanceField()

    if arm == "A0":
        pass
    elif arm == "A1":
        organ_factory = _o1
    elif arm == "BT":
        base_temperature = BTEMP
    elif arm == "P0":
        gate = True
    elif arm == "RSTAR":
        if rstar_params is None:
            raise ValueError("RSTAR requires frozen RStarParams")
        base_temperature = rstar_params.base_temperature
        relevance = RelevanceField(
            inertia=rstar_params.inertia,
            surprise_gain=rstar_params.surprise_gain,
        )
    else:
        raise ValueError(f"unknown arm: {arm}")

    shell = CorrigibilityShell()
    viability = ViabilityCore(
        budget=1e9,
        metabolic_cost=0.0,
        capacity=1e9,
        safe_budget=1.0,
    )
    return Agent(
        n_actions=N_ACTIONS,
        shell=shell,
        rng=random.Random(8000 + seed),
        viability=viability,
        prior_organ=organ_factory(),
        policy_gate=gate,
        gate_kappa=GK,
        gate_temp_floor=GTF,
        base_temperature=base_temperature,
        relevance=relevance,
    )


def run_seed(
    seed: int,
    arm: str,
    condition: Condition,
    *,
    rstar_params: RStarParams | None = None,
    steps: int = STEPS,
    window: int = WINDOW,
) -> RunResult:
    """Run one arm/seed/condition through the real Agent.step(env) path."""
    env = StructuredRegimeEnv(
        n_actions=N_ACTIONS,
        rng=random.Random(7000 + seed),
        n_regimes=N_REGIMES,
        period=PERIOD,
        noise=condition.noise,
        severity=condition.severity,
    )
    agent = _agent(seed, arm, rstar_params)
    area = 0.0
    window_left = 0
    diag_sums = {"rho": 0.0, "conf": 0.0, "tau": 0.0, "w_e": 0.0}
    diag_count = 0
    for _ in range(steps):
        rec = agent.step(env)
        if rec is None:
            break
        if env.just_shifted:
            window_left = window
        if window_left > 0:
            area += env.last_regret
            for key in diag_sums:
                if key in rec:
                    diag_sums[key] += float(rec[key])
            diag_count += 1
            window_left -= 1
    diagnostics = (
        {key: diag_sums[key] / diag_count for key in diag_sums} if diag_count else {}
    )
    return RunResult(area=area, diagnostics=diagnostics)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _bootstrap_ci(
    values: list[float], n: int = 2000, seed: int = 12345
) -> tuple[float, float]:
    rng = random.Random(seed)
    m = len(values)
    means = sorted(
        sum(values[rng.randrange(m)] for _ in range(m)) / m for _ in range(n)
    )
    return means[int(0.025 * n)], means[int(0.975 * n)]


def calibrate_rstar(
    *,
    seeds: tuple[int, ...] = CALIBRATION_SEEDS,
    conditions: tuple[Condition, ...] | None = None,
    grid: tuple[RStarParams, ...] = RSTAR_GRID,
    steps: int = STEPS,
) -> CalibrationResult:
    if conditions is None:
        conditions = calibration_conditions()
    rows = []
    for params in grid:
        areas = [
            run_seed(seed, "RSTAR", condition, rstar_params=params, steps=steps).area
            for condition in conditions
            for seed in seeds
        ]
        row = {
            **asdict(params),
            "mean_area": _mean(areas),
        }
        rows.append(row)
    rows.sort(
        key=lambda r: (
            r["mean_area"],
            r["base_temperature"],
            r["inertia"],
            r["surprise_gain"],
        )
    )
    best = RStarParams(
        base_temperature=rows[0]["base_temperature"],
        inertia=rows[0]["inertia"],
        surprise_gain=rows[0]["surprise_gain"],
    )
    return CalibrationResult(
        best_params=best,
        best_mean_area=rows[0]["mean_area"],
        seeds=tuple(seeds),
        conditions=tuple(conditions),
        rows=tuple(rows),
    )


def write_rstar_freeze(
    result: CalibrationResult, path: Path = RSTAR_FREEZE_JSON
) -> None:
    path.write_text(
        json.dumps(
            {
                "adr": "ADR-0034",
                "kind": "RSTAR calibration freeze",
                "seeds": list(result.seeds),
                "conditions": [asdict(c) for c in result.conditions],
                "best_params": asdict(result.best_params),
                "best_mean_area": result.best_mean_area,
                "grid_rows": list(result.rows),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def read_rstar_freeze(path: Path = RSTAR_FREEZE_JSON) -> RStarParams:
    data = json.loads(path.read_text(encoding="utf-8"))
    seeds = tuple(data.get("seeds", ()))
    if seeds != CALIBRATION_SEEDS:
        raise ValueError(
            "RSTAR freeze artifact does not use ADR-0034 calibration seeds"
        )
    params = data["best_params"]
    return RStarParams(
        base_temperature=float(params["base_temperature"]),
        inertia=float(params["inertia"]),
        surprise_gain=float(params["surprise_gain"]),
    )


def _adv(p0: float, other: float) -> float:
    return 1.0 - p0 / other if other else 0.0


def _adv_samples(p0: list[float], other: list[float]) -> list[float]:
    return [_adv(p0[i], other[i]) for i in range(len(p0))]


def _pair_stats(p0: list[float], other: list[float]) -> dict[str, float]:
    diffs = [other[i] - p0[i] for i in range(len(p0))]
    ci = _bootstrap_ci(diffs)
    return {
        "adv": _adv(_mean(p0), _mean(other)),
        "wins": float(sum(1 for d in diffs if d > 0)),
        "wilcoxon_p": wilcoxon_one_sided(diffs),
        "ci_lower": ci[0],
        "ci_upper": ci[1],
    }


def _prediction_report(areas: dict[str, dict[str, list[float]]]) -> dict[str, Any]:
    mild = Condition(0.10, 0.30).key
    severe = Condition(1.00, 0.30).key
    low = Condition(1.00, 0.10).key
    mid1 = Condition(1.00, 0.30).key
    mid2 = Condition(1.00, 0.50).key
    high = Condition(1.00, 1.00).key

    adv_mild = _adv(_mean(areas[mild]["P0"]), _mean(areas[mild]["RSTAR"]))
    adv_severe = _adv(_mean(areas[severe]["P0"]), _mean(areas[severe]["RSTAR"]))
    gap_samples = [
        _adv_samples(areas[severe]["P0"], areas[severe]["RSTAR"])[i]
        - _adv_samples(areas[mild]["P0"], areas[mild]["RSTAR"])[i]
        for i in range(len(areas[severe]["P0"]))
    ]
    gap_ci = _bootstrap_ci(gap_samples)
    pred_a = {
        "mild_adv": adv_mild,
        "severe_adv": adv_severe,
        "severe_minus_mild_ci": gap_ci,
        "pass": adv_mild <= 0.05 and adv_severe >= 0.15 and gap_ci[0] > 0,
    }

    interior = {
        mid1: _adv(_mean(areas[mid1]["P0"]), _mean(areas[mid1]["RSTAR"])),
        mid2: _adv(_mean(areas[mid2]["P0"]), _mean(areas[mid2]["RSTAR"])),
    }
    best_mid = max(interior, key=interior.get)
    best_mid_samples = _adv_samples(areas[best_mid]["P0"], areas[best_mid]["RSTAR"])
    low_gap = [
        best_mid_samples[i] - _adv_samples(areas[low]["P0"], areas[low]["RSTAR"])[i]
        for i in range(len(best_mid_samples))
    ]
    high_gap = [
        best_mid_samples[i] - _adv_samples(areas[high]["P0"], areas[high]["RSTAR"])[i]
        for i in range(len(best_mid_samples))
    ]
    low_gap_ci = _bootstrap_ci(low_gap)
    high_gap_ci = _bootstrap_ci(high_gap)
    pred_b = {
        "best_interior_condition": best_mid,
        "best_interior_adv": interior[best_mid],
        "low_noise_adv": _adv(_mean(areas[low]["P0"]), _mean(areas[low]["RSTAR"])),
        "high_noise_adv": _adv(_mean(areas[high]["P0"]), _mean(areas[high]["RSTAR"])),
        "interior_minus_low_ci": low_gap_ci,
        "interior_minus_high_ci": high_gap_ci,
        "pass": (
            interior[best_mid]
            >= _adv(_mean(areas[low]["P0"]), _mean(areas[low]["RSTAR"])) + 0.05
            and interior[best_mid]
            >= _adv(_mean(areas[high]["P0"]), _mean(areas[high]["RSTAR"])) + 0.05
            and low_gap_ci[0] > 0
            and high_gap_ci[0] > 0
        ),
    }

    margin_total = _mean(areas[severe]["A1"]) - _mean(areas[severe]["P0"])
    margin_r = _mean(areas[severe]["A1"]) - _mean(areas[severe]["RSTAR"])
    share_r = margin_r / margin_total if margin_total else 0.0
    pred_c = {
        "share_R": share_r,
        "adv_P0_RSTAR": adv_severe,
        "pass": 0.25 <= share_r <= 0.75 and adv_severe >= 0.15,
    }

    if pred_a["pass"] and pred_b["pass"] and pred_c["pass"]:
        disposition = "B/R/K trajectory account supported"
    elif share_r > 0.75 or adv_severe < 0.15:
        disposition = "relevance-aware exploration explains most of the old margin"
    elif margin_total <= 0:
        disposition = "P0 fails broadly under the new env"
    else:
        disposition = "G10 empirical result preserved; trajectory account weakened"

    return {
        "PRED_A": pred_a,
        "PRED_B": pred_b,
        "PRED_C": pred_c,
        "disposition": disposition,
    }


def evaluate_rfinal(
    *,
    frozen_rstar: RStarParams | None,
    seeds: tuple[int, ...] = RFINAL_SEEDS,
    conditions: tuple[Condition, ...] | None = None,
    steps: int = STEPS,
) -> EvaluationResult:
    if frozen_rstar is None:
        raise ValueError("r-final requires a frozen RSTAR calibration artifact")
    if conditions is None:
        conditions = calibration_conditions()
    arms = ("A0", "A1", "BT", "P0", "RSTAR")
    areas: dict[str, dict[str, list[float]]] = {
        condition.key: {arm: [] for arm in arms} for condition in conditions
    }
    diag_values: dict[str, dict[str, dict[str, list[float]]]] = {
        condition.key: {
            arm: {k: [] for k in ("rho", "conf", "tau", "w_e")} for arm in arms
        }
        for condition in conditions
    }
    for condition in conditions:
        for seed in seeds:
            for arm in arms:
                result = run_seed(
                    seed,
                    arm,
                    condition,
                    rstar_params=frozen_rstar if arm == "RSTAR" else None,
                    steps=steps,
                )
                areas[condition.key][arm].append(result.area)
                for key, value in result.diagnostics.items():
                    diag_values[condition.key][arm][key].append(value)

    means = {
        condition.key: {arm: _mean(areas[condition.key][arm]) for arm in arms}
        for condition in conditions
    }
    pair_stats = {
        condition.key: {
            arm: _pair_stats(areas[condition.key]["P0"], areas[condition.key][arm])
            for arm in ("A0", "A1", "BT", "RSTAR")
        }
        for condition in conditions
    }
    diagnostics = {
        condition.key: {
            arm: {
                key: _mean(values) if values else 0.0
                for key, values in diag_values[condition.key][arm].items()
            }
            for arm in arms
        }
        for condition in conditions
    }
    predictions = _prediction_report(areas)
    return EvaluationResult(
        frozen_rstar=frozen_rstar,
        seeds=tuple(seeds),
        conditions=tuple(conditions),
        means=means,
        pair_stats=pair_stats,
        diagnostics=diagnostics,
        predictions=predictions,
    )


def write_result(result: EvaluationResult, path: Path = RESULT_JSON) -> None:
    path.write_text(
        json.dumps(
            {
                "adr": "ADR-0034",
                "kind": "r-final",
                "frozen_rstar": asdict(result.frozen_rstar),
                "seeds": list(result.seeds),
                "conditions": [asdict(c) for c in result.conditions],
                "means": result.means,
                "pair_stats": result.pair_stats,
                "diagnostics": result.diagnostics,
                "predictions": result.predictions,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _print_calibration(result: CalibrationResult) -> None:
    print(
        "ADR-0034 RSTAR calibration "
        f"seeds={result.seeds[0]}..{result.seeds[-1]} "
        f"conditions={len(result.conditions)}"
    )
    for row in result.rows[:10]:
        print(
            "  "
            f"bt={row['base_temperature']:.2f} inertia={row['inertia']:.2f} "
            f"surprise_gain={row['surprise_gain']:.1f} area={row['mean_area']:.1f}"
        )
    print(f"FROZEN RSTAR: {result.best_params} area={result.best_mean_area:.1f}")


def _print_evaluation(result: EvaluationResult) -> None:
    print(
        "ADR-0034 r-final "
        f"seeds={result.seeds[0]}..{result.seeds[-1]} "
        f"RSTAR={result.frozen_rstar}"
    )
    for condition in result.conditions:
        print(f"\n== {condition.key} ==")
        for arm, value in result.means[condition.key].items():
            print(f"  {arm:5s}: {value:8.1f}")
        for arm, stats in result.pair_stats[condition.key].items():
            print(
                f"  P0 vs {arm:5s}: adv={stats['adv']:+.3f} "
                f"wins={stats['wins']:.0f}/{len(result.seeds)} "
                f"p={stats['wilcoxon_p']:.6f} "
                f"CI=[{stats['ci_lower']:.1f},{stats['ci_upper']:.1f}]"
            )
    print("\nPREDICTIONS:")
    print(json.dumps(result.predictions, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    cmd = args[0] if args else "r-final"
    if cmd == "calibrate":
        result = calibrate_rstar()
        write_rstar_freeze(result)
        _print_calibration(result)
    elif cmd in {"r-final", "rfinal"}:
        result = evaluate_rfinal(frozen_rstar=read_rstar_freeze())
        write_result(result)
        _print_evaluation(result)
    elif cmd == "both":
        cal = calibrate_rstar()
        write_rstar_freeze(cal)
        _print_calibration(cal)
        result = evaluate_rfinal(frozen_rstar=cal.best_params)
        write_result(result)
        _print_evaluation(result)
    else:
        raise SystemExit(
            "usage: python -m experiments.relevance_aware_g10 [calibrate|r-final|both]"
        )


if __name__ == "__main__":
    main()
