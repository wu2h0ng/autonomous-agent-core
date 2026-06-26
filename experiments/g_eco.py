"""G-Eco lower-half mechanism entrypoint.

Allowed modes in this file are smoke/mechanism-check plus pre-Gate-2 candidate
write/verify. Gate-2 unlock, r-final, and verdict emission are deliberately
absent until the founder-reserved freeze object exists and is co-signed.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

from aac.g_eco import (
    GEcoHalt,
    GEcoMetrics,
    assert_no_calibration_refs_in_rfinal,
    assert_g_eco_static_firewalls,
    build_baseline_audit,
    build_calibration_refs,
    derive_threshold_freeze,
    freeze_battery_parameters,
    build_g_eco_arms,
    rfinal_arm_names,
    scan_rate_grid,
    verify_content_hash,
)
from envs.ecological_4cond import Ecological4CondEnv

RATE_SEEDS = tuple(range(1800, 1810))
CALIBRATION_SEEDS = tuple(range(1810, 1830))
RFINAL_SEEDS = tuple(range(1900, 1930))
GATE2_FILES = ("g_eco.rates.json", "g_eco.battery.json", "g_eco.thresholds.json")
PREGATE2_CANDIDATE_FILES = {
    "g_eco.rates.json": "g_eco.rates",
    "g_eco.battery.json": "g_eco.battery",
    "g_eco.thresholds.json": "g_eco.thresholds",
    "g_eco.baseline_audit.json": "g_eco.baseline_audit",
}
AUDIT_LEAK_TOKENS = (
    "arm_enter_rates",
    "enter_rate",
    "full_region_delta",
    "action_overlap",
    "margin",
)


def assert_gate2_unlocked(freeze_dir: Path) -> dict[str, Any]:
    missing = [name for name in GATE2_FILES if not (freeze_dir / name).exists()]
    if missing:
        raise RuntimeError(
            "G-Eco r-final is locked: missing Gate-2 freeze files " + ", ".join(missing)
        )
    raise RuntimeError(
        "G-Eco Gate-2 freeze verifier is not implemented in lower-half scope"
    )


def _load_candidate_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise GEcoHalt("PREGATE2_MISSING_FILE", f"missing pre-Gate-2 file: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GEcoHalt(
            "PREGATE2_INVALID_JSON",
            f"invalid pre-Gate-2 JSON in {path.name}: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise GEcoHalt(
            "PREGATE2_INVALID_JSON", f"{path.name} must contain a JSON object"
        )
    return payload


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise GEcoHalt(code, message)


def _verify_rates_payload(payload: dict[str, Any]) -> None:
    firewall = payload.get("firewall", {})
    _require(
        isinstance(firewall, dict),
        "PREGATE2_FIREWALL_INVALID",
        "rates firewall missing",
    )
    _require(
        firewall.get("no_battery_outputs_used") is True,
        "PREGATE2_FIREWALL_INVALID",
        "rates freeze must not use battery outputs",
    )
    _require(
        set(firewall.get("used_refs", ()))
        == {"naive_uniform", "HOMEOSTATIC_ORACLE", "WCREF"},
        "PREGATE2_FIREWALL_INVALID",
        "rates freeze must use only tri-border calibration references",
    )
    tri_border = payload.get("tri_border", {})
    _require(
        isinstance(tri_border, dict),
        "PREGATE2_RATES_INVALID",
        "tri-border rates missing",
    )
    _require(
        set(tri_border)
        == {
            "naive_uniform_full_region_rate",
            "homeostatic_oracle_full_region_rate",
            "wcref_full_region_rate",
        },
        "PREGATE2_RATES_INVALID",
        "rates freeze must expose only tri-border rates",
    )


def _verify_battery_payload(payload: dict[str, Any]) -> None:
    _require(
        tuple(payload.get("rfinal_arm_names", ())) == rfinal_arm_names(),
        "PREGATE2_BATTERY_INVALID",
        "battery freeze must enumerate the frozen r-final arms",
    )
    _require(
        payload.get("performance_fields_withheld") is True,
        "PREGATE2_BATTERY_INVALID",
        "battery freeze must withhold performance fields",
    )
    serialized = json.dumps(payload, sort_keys=True)
    _require(
        "enter_rate" not in serialized,
        "PREGATE2_BATTERY_LEAK",
        "battery leaked enter_rate",
    )
    candidates = payload.get("candidate_parameters", {})
    _require(
        isinstance(candidates, dict)
        and "VH" in candidates
        and "VH_noStake" in candidates,
        "PREGATE2_BATTERY_INVALID",
        "battery freeze must pin VH and VH_noStake parameters",
    )
    vh_source = (
        candidates["VH"].get("source", {}) if isinstance(candidates["VH"], dict) else {}
    )
    _require(
        isinstance(vh_source, dict)
        and vh_source.get("kind") == "calibration_grid"
        and "parameter_grid_hash" in vh_source
        and "selected_label" in vh_source,
        "PREGATE2_BATTERY_INVALID",
        "VH parameters must be calibration-grid selected with provenance",
    )


def _verify_threshold_payload(payload: dict[str, Any]) -> None:
    _require(
        set(payload.get("formula_inputs", ()))
        == {"naive_er", "oracle_er", "seed_count", "K"},
        "PREGATE2_THRESHOLDS_INVALID",
        "threshold formula inputs must stay blind to candidate/battery arms",
    )
    firewall = payload.get("firewall", {})
    _require(
        isinstance(firewall, dict)
        and firewall.get("uses_only_naive_and_oracle") is True,
        "PREGATE2_THRESHOLDS_INVALID",
        "threshold freeze must use only naive/oracle inputs",
    )
    _require(
        firewall.get("opponent_arm_level_inputs_withheld") is True,
        "PREGATE2_THRESHOLDS_INVALID",
        "threshold freeze must withhold opponent arm-level inputs",
    )
    mechanics = payload.get("verdict_mechanics", {})
    _require(
        isinstance(mechanics, dict),
        "PREGATE2_THRESHOLDS_INVALID",
        "threshold freeze must record verdict mechanics",
    )
    _require(
        mechanics.get("bootstrap")
        == {"B": 10000, "resample_seed": 611038, "ci_method": "percentile"},
        "PREGATE2_THRESHOLDS_INVALID",
        "bootstrap mechanics must be frozen",
    )
    _require(
        mechanics.get("battery_best_tie_break")
        == [
            "enter_rate_desc",
            "survival_steps_desc",
            "irreversible_loss_asc",
            "arm_name_asc",
        ],
        "PREGATE2_THRESHOLDS_INVALID",
        "battery-best tie-break must be frozen",
    )
    _require(
        mechanics.get("comparison") == {"epsilon": 1e-12, "rounding": "none"},
        "PREGATE2_THRESHOLDS_INVALID",
        "comparison epsilon/rounding must be frozen",
    )


def _verify_audit_payload(payload: dict[str, Any]) -> None:
    firewall = payload.get("firewall", {})
    _require(
        isinstance(firewall, dict)
        and firewall.get("withheld_arm_level_enter_rates") is True
        and firewall.get("theta_locked_before_arm_distribution_release") is True,
        "PREGATE2_AUDIT_INVALID",
        "baseline audit firewall flags are not armed",
    )
    halt_booleans = payload.get("halt_booleans", {})
    _require(
        isinstance(halt_booleans, dict),
        "PREGATE2_AUDIT_INVALID",
        "halt booleans missing",
    )
    _require(
        all(isinstance(value, bool) for value in halt_booleans.values()),
        "PREGATE2_AUDIT_INVALID",
        "halt outputs must remain boolean only",
    )
    mechanical_outputs = payload.get("mechanical_outputs", {})
    _require(
        isinstance(mechanical_outputs, dict)
        and mechanical_outputs.get("predicate_values_withheld") is True,
        "PREGATE2_AUDIT_INVALID",
        "audit predicate values must remain withheld",
    )
    serialized_outputs = json.dumps(mechanical_outputs, sort_keys=True)
    leaked = [token for token in AUDIT_LEAK_TOKENS if token in serialized_outputs]
    _require(
        not leaked,
        "PREGATE2_AUDIT_LEAK",
        "baseline audit leaked sealed predicate values: " + ", ".join(leaked),
    )


def verify_pregate2_candidate_bundle(out_dir: Path) -> dict[str, Any]:
    """Verify pre-Gate-2 candidates without unlocking Gate-2.

    This is a mechanical integrity/firewall check for founder/CTO review. A
    passing result is explicitly not a Gate-2 co-sign, not a freeze, not
    r-final authorization, and not a verdict.
    """
    assert_g_eco_static_firewalls()
    payloads: dict[str, dict[str, Any]] = {}
    for filename, expected_kind in PREGATE2_CANDIDATE_FILES.items():
        payload = _load_candidate_payload(out_dir / filename)
        _require(
            payload.get("kind") == expected_kind,
            "PREGATE2_KIND_MISMATCH",
            f"{filename} kind mismatch",
        )
        _require(
            payload.get("status") in {"frozen_candidate", "pregate2_mechanical_audit"},
            "PREGATE2_STATUS_INVALID",
            f"{filename} has invalid pre-Gate-2 status",
        )
        _require(
            verify_content_hash(payload),
            "PREGATE2_HASH_MISMATCH",
            f"{filename} content_hash does not match payload",
        )
        payloads[filename] = payload

    _verify_rates_payload(payloads["g_eco.rates.json"])
    _verify_battery_payload(payloads["g_eco.battery.json"])
    _verify_threshold_payload(payloads["g_eco.thresholds.json"])
    _verify_audit_payload(payloads["g_eco.baseline_audit.json"])

    return {
        "kind": "G-Eco pre-Gate-2 candidate verification",
        "gate2_locked": True,
        "verified_candidate_bundle": True,
        "static_firewalls_verified": True,
        "files": sorted(PREGATE2_CANDIDATE_FILES),
        "content_hashes": {
            filename: payload["content_hash"]
            for filename, payload in sorted(payloads.items())
        },
        "note": (
            "Mechanical candidate integrity/firewall verification only; still no "
            "founder/CTO Gate-2 co-sign, no r-final, no verdict."
        ),
    }


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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_pregate2_candidate(
    out_dir: Path,
    *,
    rate_seeds: tuple[int, ...] = RATE_SEEDS,
    audit_seeds: tuple[int, ...] = CALIBRATION_SEEDS,
    steps: int = 36,
) -> dict[str, Any]:
    """Write pre-Gate-2 freeze candidates without unlocking Gate-2.

    These files are mechanical candidates for founder/CTO review. Their
    existence is deliberately insufficient for r-final: ``assert_gate2_unlocked``
    still hard-fails until a real Gate-2 verifier exists and is co-signed.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    rates = scan_rate_grid(seeds=rate_seeds, steps=steps)
    battery = freeze_battery_parameters(rates, seeds=audit_seeds, steps=steps)
    thresholds = derive_threshold_freeze(
        naive_er=rates.naive_full_region_rate,
        oracle_er=rates.oracle_full_region_rate,
        seed_count=len(rate_seeds),
        K=4,
    )
    audit = build_baseline_audit(
        rates,
        battery,
        seeds=audit_seeds,
        steps=steps,
    )

    payloads = {
        "g_eco.rates.json": rates.to_dict(),
        "g_eco.battery.json": battery.to_dict(),
        "g_eco.thresholds.json": thresholds.to_dict(),
        "g_eco.baseline_audit.json": audit.to_dict(),
    }
    for filename, payload in payloads.items():
        _write_json(out_dir / filename, payload)
    return {
        "kind": "G-Eco pre-Gate-2 freeze candidates",
        "gate2_locked": True,
        "files": sorted(payloads),
        "note": (
            "Candidate freeze artifacts only; no founder/CTO Gate-2 co-sign, "
            "no r-final, no verdict."
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
    if args and args[0] == "pregate2-candidates":
        out_dir = Path(args[1]) if len(args) > 1 else Path(".")
        _print_result(write_pregate2_candidate(out_dir))
        return
    if args and args[0] == "pregate2-verify":
        out_dir = Path(args[1]) if len(args) > 1 else Path(".")
        _print_result(verify_pregate2_candidate_bundle(out_dir))
        return
    if args and args[0] not in {"smoke", "mechanism-check"}:
        raise SystemExit(
            "usage: python -m experiments.g_eco "
            "[smoke|mechanism-check|pregate2-candidates OUT_DIR|pregate2-verify OUT_DIR]"
        )
    _print_result(mechanism_check())


if __name__ == "__main__":
    main()
