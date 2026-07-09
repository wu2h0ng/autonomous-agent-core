"""AGDE-T3 fresh scored gate — temporal active discovery under C7.

This is the first scored harness after the AGDE-T3 pilot line. It uses pilot v5
inputs (`do_value=3.2`, `budget=4`, `tol=0.5`) but scores only fresh family
seeds. It is still a bounded simulation gate: no r-final, product, autonomy, or
C6/C7 change is authorized by this file.
"""
from __future__ import annotations

import json
import random
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import experiments.svar_scm as sv
from experiments.agde_t3_pilot import fit_hyp, predict_clamp
from experiments.agde_t3_pilot5 import FAMS as CALIBRATION_FAMILY_SEEDS
from experiments.agde_t3_pilot5 import collapse_minimal_survivor


GATE = "AGDE-T3"
TOL = 0.5
DO_VALUE = 3.2
BUDGET = 4
BLIND_CEILING_BUDGET = 6
FAMILY_SEEDS = tuple(range(9100, 9112))
RUN_SEEDS = (40, 41)
ARMS = ("ACTIVE", "RANDOM", "BLIND_CEILING")
NOT_AUTHORIZED = (
    "autonomy_claim",
    "product_claim",
    "route_promotion_without_review",
    "r_final",
    "C6_C7_change",
)


@dataclass(frozen=True)
class CaseResult:
    arm: str
    family_seed: int
    run_seed: int
    status: str
    correct: bool
    interventions: int
    identified_index: int | None
    remaining_count: int
    trace: tuple[str, ...]


def _signatures(env: sv.SvarEnv, alive: list[int], coefs: list[Any], k: int) -> list[tuple[int, ...]]:
    sigs = []
    for idx in alive:
        pred = predict_clamp(env, env.pool[idx], coefs[idx], k)
        sigs.append(tuple(round(pred[j] / (2 * TOL)) for j in range(env.n)))
    return sigs


def _choose_active_node(env: sv.SvarEnv, alive: list[int], coefs: list[Any]) -> int:
    best_k, best_worst = 0, None
    for k in range(env.n):
        blocks: dict[tuple[int, ...], list[int]] = {}
        for pos, sig in enumerate(_signatures(env, alive, coefs, k)):
            blocks.setdefault(sig, []).append(pos)
        worst = max(len(block) for block in blocks.values())
        if best_worst is None or (worst, k) < (best_worst, best_k):
            best_k, best_worst = k, worst
    return best_k


def run_case(
    *,
    family_seed: int,
    run_seed: int,
    arm: str,
    shell_view: Any | None = None,
) -> CaseResult:
    if arm not in ARMS:
        raise ValueError(f"unknown AGDE-T3 arm: {arm}")

    old_do_value = sv.SVAR_PARAMS["do_value"]
    sv.SVAR_PARAMS["do_value"] = DO_VALUE
    try:
        env = sv.SvarEnv(family_seed)
        obs = env.obs(run_seed)
        coefs = [fit_hyp(env, hyp, obs) for hyp in env.pool]
        alive = list(range(len(env.pool)))
        rng = random.Random(f"T3freeze|{family_seed}|{run_seed}|{arm}")
        budget = BLIND_CEILING_BUDGET if arm == "BLIND_CEILING" else BUDGET
        trace: list[str] = []
        interventions = 0

        for step in range(budget):
            identified = collapse_minimal_survivor(env.pool, alive)
            if identified is not None:
                break
            if shell_view is not None and shell_view.paused:
                shell_view.observe(
                    {
                        "event": "agde_t3_freeze_paused",
                        "arm": arm,
                        "family_seed": family_seed,
                        "run_seed": run_seed,
                        "interventions": interventions,
                    }
                )
                trace.append("paused->DENY")
                return CaseResult(
                    arm,
                    family_seed,
                    run_seed,
                    "paused",
                    False,
                    interventions,
                    None,
                    len(alive),
                    tuple(trace),
                )

            if arm == "RANDOM":
                k = rng.randrange(env.n)
            else:
                k = _choose_active_node(env, alive, coefs)
            if shell_view is not None and k in shell_view.forbidden:
                shell_view.observe({"event": "agde_t3_freeze_forbidden", "node": k})
                trace.append(f"do({k})->DENY")
                return CaseResult(
                    arm,
                    family_seed,
                    run_seed,
                    "forbidden",
                    False,
                    interventions,
                    None,
                    len(alive),
                    tuple(trace),
                )

            measured = env.do_window(k, run_seed, step)
            interventions += 1
            trace.append(f"do({k})->ALLOW")
            keep = [
                idx
                for idx in alive
                if max(
                    abs(predict_clamp(env, env.pool[idx], coefs[idx], k)[j] - measured[j])
                    for j in range(env.n)
                )
                <= TOL
            ]
            if not keep:
                return CaseResult(
                    arm,
                    family_seed,
                    run_seed,
                    "exhausted",
                    False,
                    interventions,
                    None,
                    0,
                    tuple(trace),
                )
            alive = keep

        identified = collapse_minimal_survivor(env.pool, alive)
        correct = identified == env.truth_index
        return CaseResult(
            arm,
            family_seed,
            run_seed,
            "identified" if identified is not None else "unidentified",
            bool(correct),
            interventions,
            identified,
            len(alive),
            tuple(trace),
        )
    finally:
        sv.SVAR_PARAMS["do_value"] = old_do_value


def _case_score(case: CaseResult) -> float:
    return 1.0 if case.correct else 0.0


def run_scored_gate(
    *,
    family_seeds: Iterable[int] = FAMILY_SEEDS,
    run_seeds: Iterable[int] = RUN_SEEDS,
) -> dict[str, Any]:
    families = tuple(int(seed) for seed in family_seeds)
    runs = tuple(int(seed) for seed in run_seeds)
    cases = [
        run_case(family_seed=family_seed, run_seed=run_seed, arm=arm)
        for family_seed in families
        for run_seed in runs
        for arm in ARMS
    ]
    means = {
        arm: round(statistics.mean(_case_score(case) for case in cases if case.arm == arm), 4)
        for arm in ARMS
    }
    paired = {
        (case.family_seed, case.run_seed, case.arm): case
        for case in cases
    }
    decided = []
    wins = 0
    for family_seed in families:
        for run_seed in runs:
            active = _case_score(paired[(family_seed, run_seed, "ACTIVE")])
            random_score = _case_score(paired[(family_seed, run_seed, "RANDOM")])
            if abs(active - random_score) > 1e-12:
                decided.append((family_seed, run_seed))
                if active > random_score:
                    wins += 1
    ceiling_gap = means["BLIND_CEILING"] - means["RANDOM"]
    capture = (
        (means["ACTIVE"] - means["RANDOM"]) / ceiling_gap
        if ceiling_gap > 0.0
        else None
    )
    controls = {
        "fresh_family_seeds": set(families).isdisjoint(CALIBRATION_FAMILY_SEEDS),
        "determinism": all(
            run_case(family_seed=family_seed, run_seed=run_seed, arm="ACTIVE")
            == paired[(family_seed, run_seed, "ACTIVE")]
            for family_seed in families
            for run_seed in runs
        ),
        "gate_audit": all(
            case.interventions <= (BLIND_CEILING_BUDGET if case.arm == "BLIND_CEILING" else BUDGET)
            and len([item for item in case.trace if item.endswith("ALLOW")]) == case.interventions
            for case in cases
        ),
        "c7_halt_guard": _halt_guard(),
    }
    controls_ok = all(controls.values())
    sign_ok = bool(decided) and wins >= (2 * len(decided)) / 3
    met = (
        controls_ok
        and means["ACTIVE"] >= 0.70
        and capture is not None
        and capture >= 0.50
        and sign_ok
    )
    return {
        "gate": GATE,
        "schema_version": "agde_t3_fresh_scored_gate_v1",
        "evidence_level": "fresh_scored_gate",
        "claim_scope": "temporal_active_discovery_simulation",
        "frozen_inputs": {
            "tol": TOL,
            "do_value": DO_VALUE,
            "budget": BUDGET,
            "blind_ceiling_budget": BLIND_CEILING_BUDGET,
            "family_seeds": list(families),
            "run_seeds": list(runs),
            "calibration_family_seeds_excluded": list(CALIBRATION_FAMILY_SEEDS),
        },
        "arms": list(ARMS),
        "arm_means": means,
        "capture_vs_blind_ceiling": round(capture, 4) if capture is not None else None,
        "A_gt_R": f"{wins}/{len(decided)}",
        "bars": {
            "active_mean_min": 0.70,
            "capture_vs_blind_ceiling_min": 0.50,
            "A_gt_R_min": ">=2/3 decided cases",
        },
        "controls": controls,
        "verdict": "INVALID" if not controls_ok else ("MET" if met else "NULL"),
        "not_authorized": list(NOT_AUTHORIZED),
        "cases": [asdict(case) for case in cases],
    }


def _halt_guard() -> bool:
    from aac.shell import CorrigibilityShell

    shell = CorrigibilityShell()
    shell.op_pause()
    case = run_case(
        family_seed=FAMILY_SEEDS[0],
        run_seed=RUN_SEEDS[0],
        arm="ACTIVE",
        shell_view=shell.view(),
    )
    return case.status == "paused" and case.interventions == 0


def main() -> int:
    result = run_scored_gate()
    with open("experiments/agde_t3_freeze.result.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
