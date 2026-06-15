"""ADR-0035/G12: P7 transferable ecological-structure environment gate."""
from __future__ import annotations

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
from envs.ecological_regime import EcologicalRegimeEnv
from experiments.relevance_aware_g10 import RSTAR_FREEZE_JSON, RStarParams

try:
    from experiments._g7_common import N_ACTIONS, STEPS, WINDOW, wilcoxon_one_sided
except ModuleNotFoundError:  # direct script execution
    from _g7_common import N_ACTIONS, STEPS, WINDOW, wilcoxon_one_sided  # type: ignore[no-redef]


RFINAL_SEEDS = tuple(range(1700, 1730))
N_REGIMES = 5
PERIOD = 40
GK, GTF = 0.5, 0.1
BASE_TEMP = 0.3
BTEMP = 0.03
RESULT_JSON = Path("experiments/ecological_g12.result.json")


@dataclass(frozen=True)
class G12Cell:
    name: str
    structured: bool
    reversible: bool
    label: str


@dataclass(frozen=True)
class RunResult:
    post_shift_regret_area: float
    irreversible_damage: float
    damage_weighted_loss: float
    recovery_steps: float
    conflict_stability: float
    resource_survival: float


def g12_cells() -> tuple[G12Cell, ...]:
    return (
        G12Cell("C00", structured=False, reversible=True, label="thin/reversible"),
        G12Cell("C01", structured=False, reversible=False, label="thin/irreversible"),
        G12Cell("C10", structured=True, reversible=True, label="ecological/reversible"),
        G12Cell("C11", structured=True, reversible=False, label="ecological/irreversible"),
    )


def load_rstar_params(path: Path = RSTAR_FREEZE_JSON) -> RStarParams:
    data = json.loads(path.read_text(encoding="utf-8"))
    params = data["best_params"]
    return RStarParams(
        base_temperature=float(params["base_temperature"]),
        inertia=float(params["inertia"]),
        surprise_gain=float(params["surprise_gain"]),
    )


def _none() -> None:
    return None


def _o1() -> ResetScaffoldOrgan:
    return ResetScaffoldOrgan()


def _agent(seed: int, arm: str, rstar_params: RStarParams) -> Agent:
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
        base_temperature = rstar_params.base_temperature
        relevance = RelevanceField(
            inertia=rstar_params.inertia,
            surprise_gain=rstar_params.surprise_gain,
        )
    else:
        raise ValueError(f"unknown arm: {arm}")

    return Agent(
        n_actions=N_ACTIONS,
        shell=CorrigibilityShell(),
        rng=random.Random(8000 + seed),
        viability=ViabilityCore(
            budget=1e9,
            metabolic_cost=0.0,
            capacity=1e9,
            safe_budget=1.0,
        ),
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
    cell: G12Cell,
    *,
    rstar_params: RStarParams | None = None,
    steps: int = STEPS,
    window: int = WINDOW,
) -> RunResult:
    if rstar_params is None:
        rstar_params = load_rstar_params()
    env = EcologicalRegimeEnv(
        n_actions=N_ACTIONS,
        n_regimes=N_REGIMES,
        period=PERIOD,
        rng=random.Random(9000 + seed),
        structured=cell.structured,
        reversible=cell.reversible,
        noise=0.3,
    )
    agent = _agent(seed, arm, rstar_params)
    area = 0.0
    window_left = 0
    age = 0
    recovered = True
    recovery: list[float] = []
    last_action: int | None = None
    switches = 0
    actions = 0

    for _ in range(steps):
        rec = agent.step(env)
        if rec is None:
            break
        action = int(rec["action"])
        if last_action is not None and action != last_action:
            switches += 1
        last_action = action
        actions += 1

        if window_left > 0:
            area += env.last_regret
            if not recovered and env.last_regret <= 0.5:
                recovery.append(float(age))
                recovered = True
            age += 1
            window_left -= 1
            if window_left == 0 and not recovered:
                recovery.append(float(window + 1))
                recovered = True

        if env.just_shifted:
            window_left = window
            age = 0
            recovered = False

    if window_left > 0 and not recovered:
        recovery.append(float(window + 1))

    avg_recovery = sum(recovery) / len(recovery) if recovery else float(window + 1)
    conflict_stability = 1.0 - switches / max(1, actions - 1)
    damage = env.irreversible_damage
    return RunResult(
        post_shift_regret_area=area,
        irreversible_damage=damage,
        damage_weighted_loss=area + damage,
        recovery_steps=avg_recovery,
        conflict_stability=conflict_stability,
        resource_survival=env.resource_survival,
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _bootstrap_ci(values: list[float], n: int = 2000, seed: int = 12345) -> tuple[float, float]:
    rng = random.Random(seed)
    m = len(values)
    means = sorted(sum(values[rng.randrange(m)] for _ in range(m)) / m for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def cell_stats(
    *,
    p0_loss: list[float],
    cheap_loss: list[float],
    p0_damage: list[float],
    cheap_damage: list[float],
    irreversible: bool,
) -> dict[str, Any]:
    diffs = [cheap_loss[i] - p0_loss[i] for i in range(len(p0_loss))]
    ci = _bootstrap_ci(diffs)
    adv = 1.0 - _mean(p0_loss) / _mean(cheap_loss) if _mean(cheap_loss) else 0.0
    wins = sum(1 for diff in diffs if diff > 0.0)
    p = wilcoxon_one_sided(diffs)
    damage_diffs = [cheap_damage[i] - p0_damage[i] for i in range(len(p0_damage))]
    damage_ci = _bootstrap_ci(damage_diffs)
    damage_adv = (
        1.0 - _mean(p0_damage) / _mean(cheap_damage)
        if _mean(cheap_damage)
        else 0.0
    )
    win = adv >= 0.20 and wins >= 24 and p < 0.01 and ci[0] > 0.0
    if irreversible:
        win = win and damage_adv >= 0.20 and damage_ci[0] > 0.0
    return {
        "adv": adv,
        "wins": wins,
        "wilcoxon_p": p,
        "ci_lower": ci[0],
        "ci_upper": ci[1],
        "damage_adv": damage_adv,
        "damage_ci_lower": damage_ci[0],
        "damage_ci_upper": damage_ci[1],
        "win": win,
    }


def evaluate_g12(
    *,
    seeds: tuple[int, ...] = RFINAL_SEEDS,
    steps: int = STEPS,
    rstar_params: RStarParams | None = None,
) -> dict[str, Any]:
    if rstar_params is None:
        rstar_params = load_rstar_params()
    arms = ("A0", "A1", "BT", "RSTAR", "P0")
    results: dict[str, dict[str, list[dict[str, float]]]] = {}
    cells = g12_cells()
    for cell in cells:
        results[cell.name] = {arm: [] for arm in arms}
        for seed in seeds:
            for arm in arms:
                run = run_seed(seed, arm, cell, rstar_params=rstar_params, steps=steps)
                results[cell.name][arm].append(asdict(run))

    summaries: dict[str, Any] = {}
    wins: dict[str, bool] = {}
    for cell in cells:
        means = {
            arm: {
                metric: _mean([row[metric] for row in results[cell.name][arm]])
                for metric in (
                    "post_shift_regret_area",
                    "irreversible_damage",
                    "damage_weighted_loss",
                    "recovery_steps",
                    "conflict_stability",
                    "resource_survival",
                )
            }
            for arm in arms
        }
        cheap_arms = ("A0", "A1", "BT", "RSTAR")
        best_cheap = min(
            cheap_arms,
            key=lambda arm: means[arm]["damage_weighted_loss"],
        )
        stats = cell_stats(
            p0_loss=[
                row["damage_weighted_loss"] for row in results[cell.name]["P0"]
            ],
            cheap_loss=[
                row["damage_weighted_loss"] for row in results[cell.name][best_cheap]
            ],
            p0_damage=[
                row["irreversible_damage"] for row in results[cell.name]["P0"]
            ],
            cheap_damage=[
                row["irreversible_damage"] for row in results[cell.name][best_cheap]
            ],
            irreversible=not cell.reversible,
        )
        summaries[cell.name] = {
            "label": cell.label,
            "structured": cell.structured,
            "reversible": cell.reversible,
            "means": means,
            "best_cheap": best_cheap,
            "stats_vs_best_cheap": stats,
        }
        wins[cell.name] = bool(stats["win"])

    interpretation = interpret_wins(summaries)
    return {
        "adr": "ADR-0035",
        "kind": "G12 r-final",
        "seeds": list(seeds),
        "steps": steps,
        "rstar": asdict(rstar_params),
        "cells": summaries,
        "wins": wins,
        "interpretation": interpretation,
    }


def interpret_wins(summaries: dict[str, Any]) -> str:
    wins = {cell: bool(s["stats_vs_best_cheap"]["win"]) for cell, s in summaries.items()}
    adv = {cell: float(s["stats_vs_best_cheap"]["adv"]) for cell, s in summaries.items()}
    if wins["C11"] and (
        sum(wins.values()) == 1
        or all(adv["C11"] >= adv[cell] + 0.10 for cell in ("C00", "C01", "C10"))
    ):
        return "P7 ecological-irreversible axis supported"
    if wins["C01"] and wins["C11"] and not wins["C00"] and not wins["C10"]:
        return "Irreversibility, not transferable structure, is the active variable"
    if wins["C10"] and wins["C11"] and not wins["C00"] and not wins["C01"]:
        return "Transferable structure, not irreversibility, is the active variable"
    if all(wins.values()):
        return "P0 generalizes broadly; 2x2 does not isolate a new axis"
    if not any(wins.values()):
        return "P7 environment axis downgraded"
    return "Inconclusive"


def write_result(result: dict[str, Any], path: Path = RESULT_JSON) -> None:
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _print_result(result: dict[str, Any]) -> None:
    print(f"ADR-0035/G12 r-final seeds={result['seeds'][0]}..{result['seeds'][-1]}")
    for name, summary in result["cells"].items():
        print(f"\n== {name} {summary['label']} best_cheap={summary['best_cheap']} ==")
        for arm, metrics in summary["means"].items():
            print(
                f"  {arm:5s}: loss={metrics['damage_weighted_loss']:8.1f} "
                f"area={metrics['post_shift_regret_area']:8.1f} "
                f"damage={metrics['irreversible_damage']:8.1f} "
                f"recovery={metrics['recovery_steps']:5.1f}"
            )
        stats = summary["stats_vs_best_cheap"]
        print(
            f"  P0 vs best cheap: adv={stats['adv']:+.3f} wins={stats['wins']}/30 "
            f"p={stats['wilcoxon_p']:.6f} CI=[{stats['ci_lower']:.1f},{stats['ci_upper']:.1f}] "
            f"damage_adv={stats['damage_adv']:+.3f} "
            f"damage_CI=[{stats['damage_ci_lower']:.1f},{stats['damage_ci_upper']:.1f}] "
            f"WIN={stats['win']}"
        )
    print(f"\nINTERPRETATION: {result['interpretation']}")


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] not in {"r-final", "rfinal"}:
        raise SystemExit("usage: python -m experiments.ecological_g12 [r-final]")
    result = evaluate_g12()
    write_result(result)
    _print_result(result)


if __name__ == "__main__":
    main()
