"""Phase A acceptance for the strong-locus crossover harness.

Verifies the four core infrastructure pieces before Phase B arms are built:
  1. SCM generator produces a world that a linear-Gaussian likelihood mismatches.
  2. Placebo world passes §4.4 non-identifiability gate.
  3. Structure scorer computes held-out AP/SHD and refuses ground-truth DAG.
  4. Plumbing instrument separates {clean-wrong, truncated, timeout, unparseable}.

Pure stdlib. Run from the autonomous-agent-core root:
    PYTHONPATH=src python experiments/phase_a_acceptance.py
"""
from __future__ import annotations

import random
import sys
from dataclasses import asdict, dataclass

sys.path.insert(0, "src")
sys.path.insert(0, "experiments")

from scm_generator import generate_scm, residual_linear_gaussian_fit, SCMConfig
from aac.structure_scorer import (
    empirical_truth_from_interventions,
    score_oracle_wrong_parameters,
    score_structure,
)
from aac.placebo_world import generate_placebo, validate_placebo_nonidentifiability
from aac.plumbing_instrument import FailureKind, PlumbingInstrument, split_score


@dataclass
class AcceptanceResult:
    check: str
    passed: bool
    value: float | dict | str
    threshold: str


def main() -> int:
    results: list[AcceptanceResult] = []

    # 1. Generate mismatched world
    world = generate_scm(SCMConfig(n_nodes=6, n_obs=500, seed=42))

    # 1a. Linear-Gaussian mismatch check
    r2_per_node = residual_linear_gaussian_fit(world.observational, world.dag)
    avg_r2 = sum(r2_per_node.values()) / len(r2_per_node)
    results.append(
        AcceptanceResult(
            check="linear_gaussian_mismatch",
            passed=avg_r2 < 0.95,
            value=round(avg_r2, 3),
            threshold="avg R^2 < 0.95",
        )
    )

    # 2. Split interventions into S (consultable) and T (held-out)
    all_keys = list(world.interventions.keys())
    rng = random.Random(123)
    rng.shuffle(all_keys)
    held_out_keys = all_keys[: len(all_keys) // 2]
    held_out = {k: world.interventions[k] for k in held_out_keys}

    # 3. Structure scorer: perfect prediction on held-out T
    truth = empirical_truth_from_interventions(
        held_out, world.observational, effect_threshold=1.5
    )
    perfect_scores = {e: 1.0 for e in truth}
    perfect_result = score_structure(
        perfect_scores, held_out, world.observational, effect_threshold=1.5
    )
    results.append(
        AcceptanceResult(
            check="perfect_prediction_ap",
            passed=perfect_result.ap >= 0.99,
            value=round(perfect_result.ap, 3),
            threshold="AP >= 0.99",
        )
    )
    results.append(
        AcceptanceResult(
            check="perfect_prediction_shd",
            passed=perfect_result.shd == 0,
            value=perfect_result.shd,
            threshold="SHD == 0",
        )
    )

    # 4. Oracle-wrong-parameters sanity arm
    oracle_result = score_oracle_wrong_parameters(
        world.dag, held_out, world.observational, effect_threshold=1.5
    )
    results.append(
        AcceptanceResult(
            check="oracle_wrong_params_not_perfect",
            passed=oracle_result.ap < 0.99 or oracle_result.shd > 0,
            value={"ap": round(oracle_result.ap, 3), "shd": oracle_result.shd},
            threshold="AP < 0.99 or SHD > 0",
        )
    )

    # 5. Placebo world §4.4 gate
    placebo_interv, placebo_obs = generate_placebo(
        world.observational, world.interventions, seed=99
    )
    placebo_validation = validate_placebo_nonidentifiability(
        world.observational, placebo_obs, placebo_interv
    )
    results.append(
        AcceptanceResult(
            check="placebo_ap",
            passed=placebo_validation.max_ap <= placebo_validation.ap_threshold,
            value=round(placebo_validation.max_ap, 3),
            threshold=f"AP <= {placebo_validation.ap_threshold}",
        )
    )
    results.append(
        AcceptanceResult(
            check="placebo_covariance_distance",
            passed=placebo_validation.covariance_distance
            <= placebo_validation.covariance_threshold,
            value=round(placebo_validation.covariance_distance, 4),
            threshold=f"distance <= {placebo_validation.covariance_threshold}",
        )
    )

    # 6. Plumbing instrument separation
    instr = PlumbingInstrument(run_id="phase_a", arm="acceptance")
    instr.log_clean_wrong("step1", "clean wrong")
    instr.log_truncated("step2", "truncated")
    instr.log_timeout("step3", "timeout")
    instr.log_unparseable("step4", "unparseable")
    counts = instr.counts()
    all_four_present = all(counts[k.value] == 1 for k in FailureKind)
    results.append(
        AcceptanceResult(
            check="plumbing_kind_separation",
            passed=all_four_present,
            value=counts,
            threshold="each of 4 kinds == 1",
        )
    )
    score_split = split_score(0.25, instr)
    results.append(
        AcceptanceResult(
            check="plumbing_score_not_pooled",
            passed=score_split["pooled"] != score_split["pooled"],  # NaN
            value={k: v for k, v in score_split.items() if k != "pooled"},
            threshold="pooled == NaN when plumbing failures exist",
        )
    )

    # Report
    print("=" * 60)
    print("Phase A Acceptance — Strong-Locus Crossover Harness")
    print("=" * 60)
    all_passed = True
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.check}: {r.value} (threshold: {r.threshold})")
        if not r.passed:
            all_passed = False
    print("=" * 60)
    print("OVERALL:", "PASS" if all_passed else "FAIL")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
