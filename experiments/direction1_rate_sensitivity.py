"""Direction 1 rate-sensitivity cheap-falsifier scaffold.

This module defines the locked surface for a future confidence-to-temperature
rate-sensitivity sweep. It deliberately does not choose seeds, freeze a packet,
or run a sweep by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random
import time
from typing import Any

from aac.agent import Agent
from aac.prior_organ_o1 import ResetScaffoldOrgan
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.structured_regime import StructuredRegimeEnv

STEPS = 2000
WINDOW = 15
N_ACTIONS = 8
TIE_MARGIN_PCT = 0.05


def build_default_spec() -> dict[str, Any]:
    return {
        "artifact_type": "direction1_rate_sensitivity_cheap_falsifier_spec",
        "not_r_final": True,
        "environment_family": "StructuredRegimeEnv",
        "period_cells": [
            {"id": "FAST", "period": 20},
            {"id": "DEFAULT", "period": 40},
            {"id": "SLOW", "period": 80},
        ],
        "shared_constants": {
            "steps": STEPS,
            "window": WINDOW,
            "n_actions": N_ACTIONS,
            "noise": 0.3,
        },
        "arms": [
            _gated_arm("P0_FROZEN", gate_kappa=0.5, gate_temp_floor=0.1),
            _gated_arm("K025", gate_kappa=0.25, gate_temp_floor=0.1),
            _gated_arm("K100", gate_kappa=1.0, gate_temp_floor=0.1),
            _gated_arm("K200", gate_kappa=2.0, gate_temp_floor=0.1),
            _gated_arm("F003", gate_kappa=0.5, gate_temp_floor=0.03),
            _gated_arm("F020", gate_kappa=0.5, gate_temp_floor=0.2),
            _fixed_arm("A0_DEFAULT", base_temperature=0.3),
            _fixed_arm("BT_COLD", base_temperature=0.03),
            _fixed_arm("COLD_005", base_temperature=0.05),
            _fixed_arm("BROAD_200", base_temperature=2.0),
            _fixed_arm("A1_O1", base_temperature=0.3, organ="O1"),
        ],
        "tie_margin_pct": TIE_MARGIN_PCT,
        "verdicts": [
            "RATE_SENSITIVE_CANDIDATE",
            "NO_NEW_DIRECTION_1_MECHANISM",
            "INVALID",
        ],
    }


def _gated_arm(arm_id: str, *, gate_kappa: float, gate_temp_floor: float) -> dict[str, Any]:
    return {
        "id": arm_id,
        "gate": True,
        "organ": None,
        "gate_kappa": gate_kappa,
        "gate_temp_floor": gate_temp_floor,
        "base_temperature": 0.3,
    }


def _fixed_arm(
    arm_id: str, *, base_temperature: float, organ: str | None = None
) -> dict[str, Any]:
    return {
        "id": arm_id,
        "gate": False,
        "organ": organ,
        "gate_kappa": None,
        "gate_temp_floor": None,
        "base_temperature": base_temperature,
    }


def validate_spec(spec: dict[str, Any]) -> None:
    cells = {cell["id"]: cell["period"] for cell in spec.get("period_cells", [])}
    if cells != {"FAST": 20, "DEFAULT": 40, "SLOW": 80}:
        raise ValueError("period cells must be FAST=20, DEFAULT=40, SLOW=80")

    arms = {arm.get("id"): arm for arm in spec.get("arms", [])}
    required = {arm["id"] for arm in build_default_spec()["arms"]}
    if set(arms) != required:
        raise ValueError("arm set drift")
    if "RSTAR" in arms:
        raise ValueError("RSTAR is prior context, not a verdict arm")

    for arm in arms.values():
        if arm["gate"]:
            if arm.get("organ") is not None:
                raise ValueError("gated arms must not use organs")
            if arm.get("base_temperature") != 0.3:
                raise ValueError("gated arms must keep base_temperature=0.3")

    expected_fixed = {
        "A0_DEFAULT": 0.3,
        "BT_COLD": 0.03,
        "COLD_005": 0.05,
        "BROAD_200": 2.0,
        "A1_O1": 0.3,
    }
    for arm_id, base_temperature in expected_fixed.items():
        if arms[arm_id].get("gate"):
            raise ValueError(f"{arm_id} must be a fixed baseline")
        if arms[arm_id].get("base_temperature") != base_temperature:
            raise ValueError(f"{arm_id} base_temperature drift")
    if arms["A1_O1"].get("organ") != "O1":
        raise ValueError("A1_O1 baseline must use O1")


def build_env(period: int, *, seed: int, spec: dict[str, Any]) -> StructuredRegimeEnv:
    validate_spec(spec)
    constants = spec["shared_constants"]
    return StructuredRegimeEnv(
        n_actions=constants["n_actions"],
        rng=random.Random(7000 + seed),
        period=period,
        noise=constants["noise"],
    )


def build_agent(
    arm_id: str,
    *,
    seed: int,
    spec: dict[str, Any],
    shell: CorrigibilityShell | None = None,
) -> Agent:
    validate_spec(spec)
    arms = {arm["id"]: arm for arm in spec["arms"]}
    arm = arms[arm_id]
    organ = ResetScaffoldOrgan() if arm.get("organ") == "O1" else None
    return Agent(
        n_actions=spec["shared_constants"]["n_actions"],
        shell=shell if shell is not None else CorrigibilityShell(),
        rng=random.Random(8000 + seed),
        viability=ViabilityCore(
            budget=1e9,
            metabolic_cost=0.0,
            capacity=1e9,
            safe_budget=1.0,
        ),
        prior_organ=organ,
        policy_gate=arm["gate"],
        gate_kappa=arm["gate_kappa"] if arm["gate_kappa"] is not None else 1.0,
        gate_temp_floor=(
            arm["gate_temp_floor"] if arm["gate_temp_floor"] is not None else 0.1
        ),
        base_temperature=arm["base_temperature"],
    )


def run_one(seed: int, period: int, arm_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    validate_spec(spec)
    env = build_env(period, seed=seed, spec=spec)
    agent = build_agent(arm_id, seed=seed, spec=spec)
    area = 0.0
    mean_regret_numer = 0.0
    total_reward = 0.0
    window_left = 0
    shift_count = 0
    steps = spec["shared_constants"]["steps"]
    for _ in range(steps):
        rec = agent.step(env)
        if rec is None:
            break
        total_reward += rec["reward"]
        mean_regret_numer += env.last_regret
        if env.just_shifted:
            shift_count += 1
            window_left = spec["shared_constants"]["window"]
        if window_left > 0:
            area += env.last_regret
            window_left -= 1
    return {
        "period": period,
        "arm_id": arm_id,
        "seed": seed,
        "window_area": area,
        "mean_regret": mean_regret_numer / max(1, agent.steps),
        "total_reward": total_reward,
        "shift_count": shift_count,
        "steps": agent.steps,
        "invalid_flags": [],
    }


def aggregate(rows: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    validate_spec(spec)
    arms = {arm["id"]: arm for arm in spec["arms"]}
    aggregates: list[dict[str, Any]] = []
    for cell in spec["period_cells"]:
        period_rows = [row for row in rows if row["period"] == cell["period"]]
        means: dict[str, float] = {}
        for arm_id in arms:
            vals = [row["window_area"] for row in period_rows if row["arm_id"] == arm_id]
            if vals:
                means[arm_id] = sum(vals) / len(vals)
        fixed = {k: v for k, v in means.items() if not arms[k]["gate"]}
        gated = {k: v for k, v in means.items() if arms[k]["gate"]}
        best_fixed = min(fixed, key=fixed.get) if fixed else None
        best_gated = min(gated, key=gated.get) if gated else None
        aggregates.append(
            {
                "cell": cell["id"],
                "period": cell["period"],
                "mean_area_by_arm": means,
                "best_fixed_arm": best_fixed,
                "best_gated_arm": best_gated,
                "best_fixed_mean_area": fixed.get(best_fixed) if best_fixed else None,
                "best_gated_mean_area": gated.get(best_gated) if best_gated else None,
            }
        )
    return aggregates


def decide(aggregates: list[dict[str, Any]], spec: dict[str, Any]) -> str:
    validate_spec(spec)
    if len(aggregates) != 3:
        return "INVALID"
    margin = spec["tie_margin_pct"]
    by_cell = {row["cell"]: row for row in aggregates}
    required = {"FAST", "DEFAULT", "SLOW"}
    if set(by_cell) != required:
        return "INVALID"

    fixed_best_or_tied_all = True
    for row in aggregates:
        fixed = row.get("best_fixed_mean_area")
        gated = row.get("best_gated_mean_area")
        if fixed is None or gated is None:
            return "INVALID"
        tie_band = margin * fixed
        if gated < fixed - tie_band:
            fixed_best_or_tied_all = False
    if fixed_best_or_tied_all:
        return "NO_NEW_DIRECTION_1_MECHANISM"

    fast = by_cell["FAST"]
    slow = by_cell["SLOW"]
    if fast["best_gated_arm"] == slow["best_gated_arm"]:
        return "NO_NEW_DIRECTION_1_MECHANISM"
    for row in (fast, slow):
        fixed = row["best_fixed_mean_area"]
        gated = row["best_gated_mean_area"]
        if gated < fixed - margin * fixed:
            return "RATE_SENSITIVE_CANDIDATE"
    return "NO_NEW_DIRECTION_1_MECHANISM"


def empty_result_row(cell: str, period: int, arm_id: str, seed: int) -> dict[str, Any]:
    return {
        "cell": cell,
        "period": period,
        "arm_id": arm_id,
        "seed": seed,
        "window_area": 0.0,
        "mean_regret": 0.0,
        "total_reward": 0.0,
        "shift_count": 0,
        "steps": 0,
        "invalid_flags": [],
    }


def empty_period_aggregate(cell: str, period: int) -> dict[str, Any]:
    return {
        "cell": cell,
        "period": period,
        "mean_area_by_arm": {},
        "best_fixed_arm": None,
        "best_gated_arm": None,
        "best_fixed_mean_area": None,
        "best_gated_mean_area": None,
    }


def build_result_skeleton(
    spec: dict[str, Any],
    *,
    seeds: list[int],
    rows: list[dict[str, Any]],
    aggregates: list[dict[str, Any]],
) -> dict[str, Any]:
    validate_spec(spec)
    return {
        "artifact_type": "direction1_rate_sensitivity_cheap_falsifier_result",
        "not_r_final": True,
        "spec_digest": None,
        "seed_digest": None,
        "implementation_digest": None,
        "test_digest": None,
        "run_timestamp": None,
        "environment_family": spec["environment_family"],
        "rate_cells": spec["period_cells"],
        "arms": spec["arms"],
        "seeds": seeds,
        "rows": rows,
        "aggregates_by_period": aggregates,
        "tie_margin_pct": spec["tie_margin_pct"],
        "verdict": None,
        "verdict_consequence": None,
        "invalid_flags": [],
    }


def validate_result_schema(result: dict[str, Any], spec: dict[str, Any]) -> None:
    required = {
        "artifact_type",
        "not_r_final",
        "spec_digest",
        "seed_digest",
        "implementation_digest",
        "test_digest",
        "run_timestamp",
        "environment_family",
        "rate_cells",
        "arms",
        "seeds",
        "rows",
        "aggregates_by_period",
        "tie_margin_pct",
        "verdict",
        "verdict_consequence",
        "invalid_flags",
    }
    missing = required - set(result)
    if missing:
        raise ValueError(f"result schema missing: {sorted(missing)}")
    expected_cells = {cell["id"] for cell in spec["period_cells"]}
    row_cells = {row.get("cell") for row in result["rows"]}
    aggregate_cells = {row.get("cell") for row in result["aggregates_by_period"]}
    if not expected_cells <= row_cells:
        raise ValueError("result rows must cover all period cells")
    if aggregate_cells != expected_cells:
        raise ValueError("aggregates must cover exactly all period cells")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_digest(data: bytes, expected: str) -> None:
    actual = sha256_bytes(data)
    if actual != expected:
        raise ValueError("digest mismatch")


def _read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_file_digest(path: pathlib.Path, expected: str) -> None:
    require_digest(path.read_bytes(), expected)


def _canonical_spec_bytes(spec: dict[str, Any]) -> bytes:
    return json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()


def _validate_seed_doc(seed_doc: dict[str, Any]) -> list[int]:
    if seed_doc.get("not_r_final") is not True:
        raise ValueError("seed list must be not_r_final")
    seeds = seed_doc.get("seeds")
    if not isinstance(seeds, list) or not seeds:
        raise ValueError("seed list must be non-empty")
    if not all(isinstance(seed, int) for seed in seeds):
        raise ValueError("seeds must be integers")
    rule = seed_doc.get("generation_rule", {})
    if rule.get("count") != len(seeds):
        raise ValueError("seed count drift")
    return seeds


def _load_verified_inputs(
    spec_path: pathlib.Path, seeds_path: pathlib.Path, lock_path: pathlib.Path
) -> tuple[dict[str, Any], list[int], dict[str, Any]]:
    for path in (spec_path, seeds_path, lock_path):
        if not path.is_file():
            raise ValueError(f"missing required file: {path}")
    lock = _read_json(lock_path)
    if lock.get("status") != "RUN_LOCAL_LOCK_DRAFT_ONLY":
        raise ValueError("lock status is not authorized")
    if lock.get("not_r_final") is not True:
        raise ValueError("lock must be not_r_final")

    spec = _read_json(spec_path)
    validate_spec(spec)
    require_digest(_canonical_spec_bytes(spec), lock["spec"]["sha256"])

    seed_doc = _read_json(seeds_path)
    seeds = _validate_seed_doc(seed_doc)
    bound = lock["bound_files"]
    _require_file_digest(
        pathlib.Path(bound["implementation"]["path"]),
        bound["implementation"]["sha256"],
    )
    _require_file_digest(pathlib.Path(bound["tests"]["path"]), bound["tests"]["sha256"])
    _require_file_digest(seeds_path, bound["seed_list"]["sha256"])
    return spec, seeds, lock


def _run_verified_sweep(spec: dict[str, Any], seeds: list[int]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for cell in spec["period_cells"]:
        for seed in seeds:
            for arm in spec["arms"]:
                row = run_one(seed, cell["period"], arm["id"], spec)
                row["cell"] = cell["id"]
                rows.append(row)
    return rows, aggregate(rows, spec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec")
    parser.add_argument("--seeds")
    parser.add_argument("--lock")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    if not (args.spec and args.seeds and args.lock and args.out):
        return 2
    out_path = pathlib.Path(args.out)
    if out_path.exists():
        return 2
    try:
        spec, seeds, lock = _load_verified_inputs(
            pathlib.Path(args.spec), pathlib.Path(args.seeds), pathlib.Path(args.lock)
        )
        rows, aggregates = _run_verified_sweep(spec, seeds)
        result = build_result_skeleton(
            spec,
            seeds=seeds,
            rows=rows,
            aggregates=aggregates,
        )
        result["spec_digest"] = lock["spec"]["sha256"]
        result["seed_digest"] = lock["bound_files"]["seed_list"]["sha256"]
        result["implementation_digest"] = lock["bound_files"]["implementation"]["sha256"]
        result["test_digest"] = lock["bound_files"]["tests"]["sha256"]
        result["run_timestamp"] = int(time.time())
        result["verdict"] = decide(aggregates, spec)
        result["verdict_consequence"] = "cheap_falsifier_only_not_r_final"
        validate_result_schema(result, spec)
        out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        if out_path.exists():
            out_path.unlink()
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
