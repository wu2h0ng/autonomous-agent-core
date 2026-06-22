"""ADR-0036/G13: bounded consequence prior over frozen P0.

Default mode is development/audit only. The r-final path is locked behind an
explicit freeze artifact so it cannot be run before the scar screen, C6/C7
tests, and thresholds are committed.
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from aac.agent import Agent
from aac.consequence_prior import BoundedConsequencePriorOrgan, CautiousScarOrgan
from aac.prior_organ_o1 import ResetScaffoldOrgan
from aac.relevance import RelevanceField
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.consequence_scar import ConsequenceScarEnv
from experiments.ecological_g12 import load_rstar_params

try:
    from experiments._g7_common import N_ACTIONS, STEPS, WINDOW, wilcoxon_one_sided
except ModuleNotFoundError:  # direct script execution
    from _g7_common import N_ACTIONS, STEPS, WINDOW, wilcoxon_one_sided  # type: ignore[no-redef]


DEVELOPMENT_SEEDS = tuple(range(1750, 1770))
RFINAL_SEEDS = tuple(range(1800, 1830))
N_REGIMES = 5
PERIOD = 40
GK, GTF = 0.5, 0.1
BASE_TEMP = 0.3
BTEMP = 0.03
EPSILON = 1e-9
FREEZE_JSON = Path("experiments/consequence_prior_g13.freeze.json")
DEV_RESULT_JSON = Path("experiments/consequence_prior_g13.development.json")
RFINAL_RESULT_JSON = Path("experiments/consequence_prior_g13.result.json")


@dataclass(frozen=True)
class G13Cell:
    name: str
    structured: bool
    reversible: bool
    label: str


@dataclass(frozen=True)
class RunResult:
    post_shift_regret_area: float
    first_window_regret_area: float
    irreversible_damage: float
    damage_weighted_loss: float
    first_window_damage_weighted_loss: float
    recovery_steps: float
    resource_survival: float


def g13_cells() -> tuple[G13Cell, ...]:
    return (
        G13Cell("C00", structured=False, reversible=True, label="thin/reversible"),
        G13Cell("C01", structured=False, reversible=False, label="thin/irreversible"),
        G13Cell("C10", structured=True, reversible=True, label="ecological/reversible"),
        G13Cell(
            "C11", structured=True, reversible=False, label="ecological/irreversible"
        ),
    )


def _none() -> None:
    return None


def _o1() -> ResetScaffoldOrgan:
    return ResetScaffoldOrgan()


def _cp() -> BoundedConsequencePriorOrgan:
    return BoundedConsequencePriorOrgan()


def _cautious() -> CautiousScarOrgan:
    return CautiousScarOrgan()


def _agent(seed: int, arm: str) -> Agent:
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
    elif arm == "RSTAR":
        params = load_rstar_params()
        base_temperature = params.base_temperature
        relevance = RelevanceField(
            inertia=params.inertia,
            surprise_gain=params.surprise_gain,
        )
    elif arm == "P0":
        gate = True
    elif arm == "CP":
        gate = True
        organ_factory = _cp
    elif arm == "CAUTIOUS":
        gate = True
        organ_factory = _cautious
    else:
        raise ValueError(f"unknown arm: {arm}")

    return Agent(
        n_actions=N_ACTIONS,
        shell=CorrigibilityShell(),
        rng=random.Random(8100 + seed),
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
    cell: G13Cell,
    *,
    steps: int = STEPS,
    window: int = WINDOW,
) -> RunResult:
    cell_offset = {"C00": 0, "C01": 100_000, "C10": 200_000, "C11": 300_000}[cell.name]
    env = ConsequenceScarEnv(
        n_actions=N_ACTIONS,
        n_regimes=N_REGIMES,
        period=PERIOD,
        rng=random.Random(9100 + cell_offset + seed),
        structured=cell.structured,
        reversible=cell.reversible,
        noise=0.25,
    )
    agent = _agent(seed, arm)
    area = 0.0
    window_left = 0
    age = 0
    recovered = True
    recovery: list[float] = []
    current_window_area = 0.0
    first_window_area: float | None = None

    for _ in range(steps):
        rec = agent.step(env)
        if rec is None:
            break
        if window_left > 0:
            area += env.last_regret
            current_window_area += env.last_regret
            if not recovered and env.last_regret <= 0.5:
                recovery.append(float(age))
                recovered = True
            age += 1
            window_left -= 1
            if window_left == 0 and not recovered:
                recovery.append(float(window + 1))
                recovered = True
            if window_left == 0 and first_window_area is None:
                first_window_area = current_window_area
        if env.just_shifted:
            window_left = window
            age = 0
            recovered = False
            current_window_area = 0.0

    if window_left > 0 and not recovered:
        recovery.append(float(window + 1))
    if first_window_area is None:
        first_window_area = current_window_area
    avg_recovery = sum(recovery) / len(recovery) if recovery else float(window + 1)
    damage = env.irreversible_damage
    return RunResult(
        post_shift_regret_area=area,
        first_window_regret_area=first_window_area,
        irreversible_damage=damage,
        damage_weighted_loss=area + damage,
        first_window_damage_weighted_loss=first_window_area + damage,
        recovery_steps=avg_recovery,
        resource_survival=env.resource_survival,
    )


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


def _adv_samples(candidate: list[float], p0: list[float]) -> list[float]:
    out: list[float] = []
    for i, base in enumerate(p0):
        out.append(0.0 if base <= EPSILON else (base - candidate[i]) / base)
    return out


def pair_stats(
    *,
    candidate_loss: list[float],
    p0_loss: list[float],
    candidate_damage: list[float],
    p0_damage: list[float],
    candidate_stale_loss: list[float] | None = None,
    p0_stale_loss: list[float] | None = None,
) -> dict[str, Any]:
    diffs = [p0_loss[i] - candidate_loss[i] for i in range(len(p0_loss))]
    ci = _bootstrap_ci(diffs)
    adv_values = _adv_samples(candidate_loss, p0_loss)
    damage_adv_values = _adv_samples(candidate_damage, p0_damage)
    stale_candidate = (
        candidate_stale_loss if candidate_stale_loss is not None else candidate_loss
    )
    stale_p0 = p0_stale_loss if p0_stale_loss is not None else p0_loss
    stale_harm = [
        max(0.0, stale_candidate[i] - stale_p0[i]) for i in range(len(stale_p0))
    ]
    harm_seed_count = sum(
        1
        for i in range(len(stale_p0))
        if stale_p0[i] > EPSILON and stale_harm[i] > 0.10 * stale_p0[i]
    )
    return {
        "candidate_loss_mean": _mean(candidate_loss),
        "p0_loss_mean": _mean(p0_loss),
        "candidate_damage_mean": _mean(candidate_damage),
        "p0_damage_mean": _mean(p0_damage),
        "adv": _mean(adv_values),
        "wins": sum(1 for d in diffs if d > 0.0),
        "wilcoxon_p": wilcoxon_one_sided(diffs),
        "ci_lower": ci[0],
        "ci_upper": ci[1],
        "damage_adv": _mean(damage_adv_values),
        "stale_prior_harm": _mean(stale_harm),
        "harm_seed_count": harm_seed_count,
        "near_zero_loss_denominators": sum(1 for v in p0_loss if v <= EPSILON),
        "near_zero_damage_denominators": sum(1 for v in p0_damage if v <= EPSILON),
    }


def _metric_series(
    results: dict[str, dict[str, list[dict[str, float]]]],
    cell: str,
    arm: str,
    metric: str,
) -> list[float]:
    return [row[metric] for row in results[cell][arm]]


def _collapse_series(
    results: dict[str, dict[str, list[dict[str, float]]]],
    cells: tuple[G13Cell, ...],
    arm: str,
    metric: str,
    *,
    reversible: bool,
) -> list[float]:
    selected = [cell.name for cell in cells if cell.reversible is reversible]
    n = len(results[selected[0]][arm])
    return [
        sum(results[cell][arm][i][metric] for cell in selected) / len(selected)
        for i in range(n)
    ]


def _specificity_stats(
    *,
    r1_cp_loss: list[float],
    r1_p0_loss: list[float],
    reversible_cell_stats: dict[str, dict[str, Any]],
    results: dict[str, dict[str, list[dict[str, float]]]],
) -> dict[str, Any]:
    r1_adv = _mean(_adv_samples(r1_cp_loss, r1_p0_loss))
    max_reversible_cell = max(
        reversible_cell_stats,
        key=lambda name: reversible_cell_stats[name]["CP_vs_P0"]["adv"],
    )
    max_rev_adv = reversible_cell_stats[max_reversible_cell]["CP_vs_P0"]["adv"]
    per_seed = []
    for i in range(len(r1_cp_loss)):
        r1_sample = _adv_samples([r1_cp_loss[i]], [r1_p0_loss[i]])[0]
        c00 = _adv_samples(
            [results["C00"]["CP"][i]["damage_weighted_loss"]],
            [results["C00"]["P0"][i]["damage_weighted_loss"]],
        )[0]
        c10 = _adv_samples(
            [results["C10"]["CP"][i]["damage_weighted_loss"]],
            [results["C10"]["P0"][i]["damage_weighted_loss"]],
        )[0]
        per_seed.append(r1_sample - max(c00, c10))
    ci = _bootstrap_ci(per_seed)
    return {
        "irreversible_adv": r1_adv,
        "max_reversible_adv": max_rev_adv,
        "max_reversible_cell": max_reversible_cell,
        "contrast": r1_adv - max_rev_adv,
        "contrast_ci_lower": ci[0],
        "contrast_ci_upper": ci[1],
    }


def _cheap_caution_capture(
    *,
    p0_damage: list[float],
    cp_damage: list[float],
    cautious_damage: list[float],
) -> float:
    cp_reduction = _mean([p0_damage[i] - cp_damage[i] for i in range(len(p0_damage))])
    cautious_reduction = _mean(
        [p0_damage[i] - cautious_damage[i] for i in range(len(p0_damage))]
    )
    if cp_reduction <= EPSILON:
        return 0.0
    return cautious_reduction / cp_reduction


def _any_reversible_cell_harm_count(
    results: dict[str, dict[str, list[dict[str, float]]]],
) -> int:
    count = 0
    n = len(results["C00"]["P0"])
    for i in range(n):
        harmed = False
        for cell in ("C00", "C10"):
            p0 = results[cell]["P0"][i]["first_window_damage_weighted_loss"]
            cp = results[cell]["CP"][i]["first_window_damage_weighted_loss"]
            if p0 > EPSILON and cp - p0 > 0.10 * p0:
                harmed = True
        if harmed:
            count += 1
    return count


def scar_validity_screen(summary: dict[str, Any]) -> dict[str, Any]:
    env_r0 = ConsequenceScarEnv(
        n_actions=N_ACTIONS,
        rng=random.Random(1),
        structured=True,
        reversible=True,
    )
    env_r1 = ConsequenceScarEnv(
        n_actions=N_ACTIONS,
        rng=random.Random(1),
        structured=True,
        reversible=False,
    )
    r1_situation = env_r1.situation()
    forbidden_keys = {
        "best_action",
        "hidden_best_action",
        "hidden_hazard_action",
        "damage_oracle",
        "evaluator_damage",
    }
    features = r1_situation["public_consequence_features"]
    scar_values = [float(row["scar_delta"]) for row in features]
    risky = max(range(len(scar_values)), key=lambda i: scar_values[i])
    safe = min(range(len(scar_values)), key=lambda i: scar_values[i])
    env_r1.act(risky)
    before = env_r1.irreversible_damage
    env_r1.force_regime_change()
    env_r0.act(risky)
    env_r0.force_regime_change()
    cheap_capture = (
        summary.get("collapse", {}).get("R1", {}).get("cheap_caution_capture", 0.0)
    )
    return {
        "external_irreversible": before > 0.0 and env_r1.irreversible_damage == before,
        "reversible_rolls_back_current_damage": env_r0.current_damage == 0.0
        and env_r0.irreversible_damage == 0.0,
        "foresight_avoidable": scar_values[risky] > scar_values[safe],
        "no_label_leak": not (set(r1_situation) & forbidden_keys),
        "cheap_not_trivially_avoided": cheap_capture < 0.95,
        "cheap_caution_capture": cheap_capture,
        "valid": (
            before > 0.0
            and env_r1.irreversible_damage == before
            and env_r0.current_damage == 0.0
            and env_r0.irreversible_damage == 0.0
            and scar_values[risky] > scar_values[safe]
            and not (set(r1_situation) & forbidden_keys)
            and cheap_capture < 0.95
        ),
    }


def evaluate_g13(
    *,
    seeds: tuple[int, ...] = DEVELOPMENT_SEEDS,
    steps: int = STEPS,
) -> dict[str, Any]:
    arms = ("A0", "A1", "BT", "RSTAR", "P0", "CP", "CAUTIOUS")
    cells = g13_cells()
    results: dict[str, dict[str, list[dict[str, float]]]] = {}
    for cell in cells:
        results[cell.name] = {arm: [] for arm in arms}
        for seed in seeds:
            for arm in arms:
                run = run_seed(seed, arm, cell, steps=steps)
                results[cell.name][arm].append(asdict(run))

    cell_summary: dict[str, Any] = {}
    for cell in cells:
        means = {
            arm: {
                metric: _mean([row[metric] for row in results[cell.name][arm]])
                for metric in (
                    "post_shift_regret_area",
                    "first_window_regret_area",
                    "irreversible_damage",
                    "damage_weighted_loss",
                    "first_window_damage_weighted_loss",
                    "recovery_steps",
                    "resource_survival",
                )
            }
            for arm in arms
        }
        cell_summary[cell.name] = {
            "label": cell.label,
            "structured": cell.structured,
            "reversible": cell.reversible,
            "means": means,
            "CP_vs_P0": pair_stats(
                candidate_loss=_metric_series(
                    results, cell.name, "CP", "damage_weighted_loss"
                ),
                p0_loss=_metric_series(
                    results, cell.name, "P0", "damage_weighted_loss"
                ),
                candidate_damage=_metric_series(
                    results, cell.name, "CP", "irreversible_damage"
                ),
                p0_damage=_metric_series(
                    results, cell.name, "P0", "irreversible_damage"
                ),
                candidate_stale_loss=_metric_series(
                    results, cell.name, "CP", "first_window_damage_weighted_loss"
                ),
                p0_stale_loss=_metric_series(
                    results, cell.name, "P0", "first_window_damage_weighted_loss"
                ),
            ),
            "CAUTIOUS_vs_P0": pair_stats(
                candidate_loss=_metric_series(
                    results, cell.name, "CAUTIOUS", "damage_weighted_loss"
                ),
                p0_loss=_metric_series(
                    results, cell.name, "P0", "damage_weighted_loss"
                ),
                candidate_damage=_metric_series(
                    results, cell.name, "CAUTIOUS", "irreversible_damage"
                ),
                p0_damage=_metric_series(
                    results, cell.name, "P0", "irreversible_damage"
                ),
                candidate_stale_loss=_metric_series(
                    results, cell.name, "CAUTIOUS", "first_window_damage_weighted_loss"
                ),
                p0_stale_loss=_metric_series(
                    results, cell.name, "P0", "first_window_damage_weighted_loss"
                ),
            ),
        }

    collapse: dict[str, Any] = {}
    for name, reversible in (("R0", True), ("R1", False)):
        cp_loss = _collapse_series(
            results, cells, "CP", "damage_weighted_loss", reversible=reversible
        )
        p0_loss = _collapse_series(
            results, cells, "P0", "damage_weighted_loss", reversible=reversible
        )
        cautious_loss = _collapse_series(
            results, cells, "CAUTIOUS", "damage_weighted_loss", reversible=reversible
        )
        cp_damage = _collapse_series(
            results, cells, "CP", "irreversible_damage", reversible=reversible
        )
        p0_damage = _collapse_series(
            results, cells, "P0", "irreversible_damage", reversible=reversible
        )
        cautious_damage = _collapse_series(
            results, cells, "CAUTIOUS", "irreversible_damage", reversible=reversible
        )
        cp_stale_loss = _collapse_series(
            results,
            cells,
            "CP",
            "first_window_damage_weighted_loss",
            reversible=reversible,
        )
        p0_stale_loss = _collapse_series(
            results,
            cells,
            "P0",
            "first_window_damage_weighted_loss",
            reversible=reversible,
        )
        cautious_stale_loss = _collapse_series(
            results,
            cells,
            "CAUTIOUS",
            "first_window_damage_weighted_loss",
            reversible=reversible,
        )
        collapse[name] = {
            "CP_vs_P0": pair_stats(
                candidate_loss=cp_loss,
                p0_loss=p0_loss,
                candidate_damage=cp_damage,
                p0_damage=p0_damage,
                candidate_stale_loss=cp_stale_loss,
                p0_stale_loss=p0_stale_loss,
            ),
            "CAUTIOUS_vs_P0": pair_stats(
                candidate_loss=cautious_loss,
                p0_loss=p0_loss,
                candidate_damage=cautious_damage,
                p0_damage=p0_damage,
                candidate_stale_loss=cautious_stale_loss,
                p0_stale_loss=p0_stale_loss,
            ),
            "cheap_caution_capture": _cheap_caution_capture(
                p0_damage=p0_damage,
                cp_damage=cp_damage,
                cautious_damage=cautious_damage,
            ),
            "reversible_spillover": (
                max(0.0, _mean(_adv_samples(cp_loss, p0_loss))) if reversible else 0.0
            ),
        }
    collapse["R0"]["CP_vs_P0"]["reversible_any_cell_harm_seed_count"] = (
        _any_reversible_cell_harm_count(results)
    )

    specificity = _specificity_stats(
        r1_cp_loss=_collapse_series(
            results, cells, "CP", "damage_weighted_loss", reversible=False
        ),
        r1_p0_loss=_collapse_series(
            results, cells, "P0", "damage_weighted_loss", reversible=False
        ),
        reversible_cell_stats={name: cell_summary[name] for name in ("C00", "C10")},
        results=results,
    )
    summary = {
        "adr": "ADR-0036",
        "kind": "G13 development" if seeds == DEVELOPMENT_SEEDS else "G13 evaluation",
        "seeds": list(seeds),
        "steps": steps,
        "cells": cell_summary,
        "collapse": collapse,
        "specificity": specificity,
        "gate_preview": gate_preview(collapse=collapse, specificity=specificity),
    }
    summary["scar_validity_screen"] = scar_validity_screen(summary)
    return summary


def gate_preview(
    *, collapse: dict[str, Any], specificity: dict[str, Any]
) -> dict[str, Any]:
    r1 = collapse["R1"]["CP_vs_P0"]
    r0 = collapse["R0"]["CP_vs_P0"]
    stale_bound = 0.05 * r0["p0_loss_mean"]
    return {
        "G13_1_irreversible_benefit": (
            r1["adv"] >= 0.10
            and r1["wins"] >= 24
            and r1["wilcoxon_p"] < 0.01
            and r1["ci_lower"] > 0.0
            and r1["damage_adv"] >= 0.10
        ),
        "G13_2_scar_specificity": (
            specificity["contrast"] >= 0.10 and specificity["contrast_ci_lower"] > 0.0
        ),
        "G13_3_no_stale_prior_harm": (
            r0["adv"] >= -0.05
            and r0["stale_prior_harm"] <= stale_bound
            and r0["reversible_any_cell_harm_seed_count"] <= 3
        ),
        "note": "Preview only; r-final remains locked until freeze/audit artifacts exist.",
    }


def write_result(result: dict[str, Any], path: Path) -> None:
    path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def assert_rfinal_unlocked(path: Path = FREEZE_JSON) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(
            "G13 r-final is locked: missing experiments/consequence_prior_g13.freeze.json"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("adr") != "ADR-0036" or data.get("rfinal_unlocked") is not True:
        raise RuntimeError("G13 r-final freeze artifact is present but not unlocked")
    if tuple(data.get("development_seeds", ())) != DEVELOPMENT_SEEDS:
        raise RuntimeError("G13 freeze artifact does not record the frozen dev seeds")
    if tuple(data.get("rfinal_seeds", ())) != RFINAL_SEEDS:
        raise RuntimeError(
            "G13 freeze artifact does not record the frozen r-final seeds"
        )
    return data


def _print_summary(result: dict[str, Any]) -> None:
    print(f"{result['kind']} seeds={result['seeds'][0]}..{result['seeds'][-1]}")
    print(f"scar_validity_screen={result['scar_validity_screen']}")
    for name, group in result["collapse"].items():
        cp = group["CP_vs_P0"]
        print(
            f"{name}: CP_vs_P0 adv={cp['adv']:+.3f} wins={cp['wins']}/"
            f"{len(result['seeds'])} p={cp['wilcoxon_p']:.6f} "
            f"damage_adv={cp['damage_adv']:+.3f} "
            f"cheap_capture={group['cheap_caution_capture']:+.3f}"
        )
    spec = result["specificity"]
    print(
        "specificity: "
        f"contrast={spec['contrast']:+.3f} "
        f"CI=[{spec['contrast_ci_lower']:.3f},{spec['contrast_ci_upper']:.3f}]"
    )
    print(f"gate_preview={result['gate_preview']}")


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    cmd = args[0] if args else "development"
    if cmd in {"development", "dev"}:
        result = evaluate_g13(seeds=DEVELOPMENT_SEEDS)
        write_result(result, DEV_RESULT_JSON)
        _print_summary(result)
    elif cmd in {"r-final", "rfinal"}:
        assert_rfinal_unlocked()
        result = evaluate_g13(seeds=RFINAL_SEEDS)
        result["kind"] = "G13 r-final"
        write_result(result, RFINAL_RESULT_JSON)
        _print_summary(result)
    else:
        raise SystemExit(
            "usage: python -m experiments.consequence_prior_g13 [development|r-final]"
        )


if __name__ == "__main__":
    main()
