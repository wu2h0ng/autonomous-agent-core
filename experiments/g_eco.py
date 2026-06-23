"""G-Eco lower-half mechanism entrypoint.

Allowed modes in this file are smoke/mechanism-check only. Calibration freeze,
Gate-2 unlock, r-final, and verdict emission are deliberately absent until the
founder-reserved freeze object exists and is co-signed.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

from aac.g_eco import (
    GEcoMetrics,
    assert_no_calibration_refs_in_rfinal,
    build_calibration_refs,
    build_g_eco_arms,
    rfinal_arm_names,
)
from envs.ecological_4cond import Ecological4CondEnv

RATE_SEEDS = tuple(range(1800, 1810))
CALIBRATION_SEEDS = tuple(range(1810, 1830))
RFINAL_SEEDS = tuple(range(1900, 1930))
GATE2_FILES = ("g_eco.rates.json", "g_eco.battery.json", "g_eco.thresholds.json")


def assert_gate2_unlocked(freeze_dir: Path) -> dict[str, Any]:
    missing = [name for name in GATE2_FILES if not (freeze_dir / name).exists()]
    if missing:
        raise RuntimeError(
            "G-Eco r-final is locked: missing Gate-2 freeze files " + ", ".join(missing)
        )
    raise RuntimeError(
        "G-Eco Gate-2 freeze verifier is not implemented in lower-half scope"
    )


def run_seed(seed: int, arm_name: str, *, steps: int) -> dict[str, object]:
    arms = {arm.name: arm for arm in build_g_eco_arms()}
    if arm_name not in arms:
        raise ValueError(f"unknown G-Eco lower-half arm: {arm_name}")
    env = Ecological4CondEnv(rng=random.Random(20_000 + seed))
    arm = arms[arm_name]
    metrics = GEcoMetrics()
    for _ in range(steps):
        observation = arm.substrate.observe(env)
        action = arm.select(observation)
        if action is None:
            break
        env.act(action)
        metrics.observe(step=env.t, state=env.state, action=action, alive=env.alive)
        if not env.alive:
            break
    return metrics.summary()


def mechanism_check(
    *,
    seeds: tuple[int, ...] = RATE_SEEDS[:2],
    steps: int = 48,
) -> dict[str, Any]:
    all_arms = build_g_eco_arms(include_cheats=True)
    allowed_names = assert_no_calibration_refs_in_rfinal(all_arms, rfinal_arm_names())
    allowed = set(allowed_names)
    arms = tuple(arm for arm in all_arms if arm.name in allowed)
    refs = build_calibration_refs()
    results: dict[str, list[dict[str, object]]] = {
        arm.name: [] for arm in arms if not arm.calibration_only
    }
    for seed in seeds:
        for arm_name in results:
            results[arm_name].append(run_seed(seed, arm_name, steps=steps))
    return {
        "adr": "ADR-0038",
        "kind": "G-Eco lower-half mechanism-check",
        "seeds": list(seeds),
        "steps": steps,
        "gate2_locked": True,
        "allowed_rfinal_arms_future": list(allowed_names),
        "calibration_only_refs": [ref.name for ref in refs],
        "arms": results,
        "note": (
            "Mechanism smoke only; no §6 rate scan, no freeze JSON, "
            "no Gate-2 crossing, no r-final, no verdict."
        ),
    }


def _print_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in {"r-final", "rfinal", "freeze", "verdict"}:
        raise SystemExit(
            "G-Eco Gate-2 locked: lower-half entrypoint cannot run "
            "freeze/r-final/verdict"
        )
    if args and args[0] not in {"smoke", "mechanism-check"}:
        raise SystemExit("usage: python -m experiments.g_eco [smoke|mechanism-check]")
    _print_result(mechanism_check())


if __name__ == "__main__":
    main()
