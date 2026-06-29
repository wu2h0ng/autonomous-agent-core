"""R-CSL-1 no-model commitment ledger experiment harness.

This file defines the frozen arms/seeds and a deterministic protocol harness.
R-final execution still requires both a runner preregistration lock and an
accepted PR architecture review gate record.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median

from aac.commitment_ledger import CommitmentLedgerPolicy
from envs.commitment_correction import CorrectionSignal
from envs.commitment_correction import CommitmentCorrectionEnv

DEVELOPMENT_SMOKE_SEEDS = tuple(range(2400, 2420))
CALIBRATION_SEEDS = tuple(range(2420, 2440))
R_FINAL_SEEDS = tuple(range(2500, 2530))

ARMS = (
    "CSL",
    "P0",
    "CAUTIOUS",
    "MINIMAX",
    "FIXED_DUAL",
    "RANDOM_LEDGER",
    "NO_LEDGER",
    "FROZEN_LEDGER",
    "ACTION_SUPPRESSOR",
    "CSL_NO_REPAIR_PRIORITY",
    "CSL_NO_BUDGET_PRESSURE",
    "CSL_DELAYED_VIOLATION",
    "CSL_RANDOM_VIOLATION",
)

BASELINE_BATTERY = (
    "P0",
    "CAUTIOUS",
    "MINIMAX",
    "FIXED_DUAL",
    "RANDOM_LEDGER",
    "NO_LEDGER",
    "FROZEN_LEDGER",
    "ACTION_SUPPRESSOR",
)

REQUIRED_PR_ARCHITECTURE_REVIEW_ARTIFACTS = frozenset(
    {
        "autonomous-agent-core/experiments/r_csl_1.py",
        "autonomous-agent-core/src/aac/commitment_ledger.py",
        "autonomous-agent-core/src/envs/commitment_correction.py",
        "autonomous-agent-core/tests/test_commitment_ledger_r_csl_1.py",
    }
)

REQUIRED_PREREG_LOCK_MECHANISM_FILES = frozenset(
    {
        "experiments/r_csl_1.py",
        "src/aac/commitment_ledger.py",
        "src/envs/commitment_correction.py",
        "tests/test_commitment_ledger_r_csl_1.py",
    }
)

PREREG_SPEC_RELATIVE_PATH = "docs/research/R-CSL-1.PREREG-2026-06-25.yaml"

LOCK_TO_PR_ARCHITECTURE_REVIEW_ARTIFACT = {
    "experiments/r_csl_1.py": "autonomous-agent-core/experiments/r_csl_1.py",
    "src/aac/commitment_ledger.py": "autonomous-agent-core/src/aac/commitment_ledger.py",
    "src/envs/commitment_correction.py": "autonomous-agent-core/src/envs/commitment_correction.py",
    "tests/test_commitment_ledger_r_csl_1.py": (
        "autonomous-agent-core/tests/test_commitment_ledger_r_csl_1.py"
    ),
}


class RunLockedError(RuntimeError):
    """Raised when r-final execution is attempted before required gates pass."""


@dataclass(frozen=True)
class EpisodeMetrics:
    commitment_continuity: float
    repair_efficiency: float
    viability_margin_area: float
    c7_violation_count: int
    active_action_rate: float
    evaluable_steps: int
    repair_opportunities: int
    diagnostics: dict[str, object]


def assert_rfinal_unlocked(*, lock_path: Path) -> dict[str, object]:
    if not lock_path.is_file():
        raise RunLockedError(f"r-final is blocked until runner prereg.lock exists: {lock_path}")
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RunLockedError(f"runner prereg.lock is not valid JSON: {lock_path}") from error
    if lock.get("prereg_id") != "R-CSL-1":
        raise RunLockedError("runner prereg.lock has wrong prereg_id.")
    spec_file_sha256 = str(lock.get("spec_file_sha256") or "")
    if len(spec_file_sha256) != 64:
        raise RunLockedError("runner prereg.lock requires a 64-character spec_file_sha256.")
    spec_sha256 = str(lock.get("spec_sha256") or "")
    if len(spec_sha256) != 64:
        raise RunLockedError("runner prereg.lock requires a 64-character spec_sha256.")
    mechanism_files = lock.get("mechanism_files")
    if not isinstance(mechanism_files, dict):
        raise RunLockedError("runner prereg.lock requires mechanism_files.")
    missing = sorted(REQUIRED_PREREG_LOCK_MECHANISM_FILES.difference(mechanism_files))
    if missing:
        raise RunLockedError(f"runner prereg.lock missing mechanism file hash(es): {missing}")
    return lock


def assert_pr_architecture_review_accepted(
    *,
    review_path: Path,
    expected_digest: str | None = None,
) -> dict[str, object]:
    if not review_path.is_file():
        raise RunLockedError(f"r-final is blocked until PR architecture review exists: {review_path}")
    try:
        record = json.loads(review_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RunLockedError(f"PR architecture review record is not valid JSON: {review_path}") from error
    if record.get("gate_name") != "pr-architecture-review":
        raise RunLockedError("PR architecture review record has wrong gate_name.")
    if record.get("standard") != "PARADIGM-INNOVATION-LOOP-OS":
        raise RunLockedError("PR architecture review record has wrong standard.")
    if record.get("prior_gate") != "implementation-cast":
        raise RunLockedError("PR architecture review record has wrong prior_gate.")
    actor = str(record.get("actor") or "").strip()
    reviewed_by = str(record.get("reviewed_by") or "").strip()
    if not actor or not reviewed_by or actor == reviewed_by:
        raise RunLockedError("PR architecture review requires separated actor and reviewed_by.")
    artifact_hashes = record.get("artifact_hashes")
    if not isinstance(artifact_hashes, dict):
        raise RunLockedError("PR architecture review record requires artifact_hashes.")
    missing_artifacts = sorted(REQUIRED_PR_ARCHITECTURE_REVIEW_ARTIFACTS.difference(artifact_hashes))
    if missing_artifacts:
        raise RunLockedError(
            f"PR architecture review record missing artifact hash(es): {missing_artifacts}"
        )
    if record.get("verdict") != "accept":
        raise RunLockedError("PR architecture review is not accepted.")
    if expected_digest is not None and record.get("output_digest") != expected_digest:
        raise RunLockedError("PR architecture review digest does not match expected digest.")
    return record


def run_episode(*, seed: int, arm: str, steps: int = 24) -> EpisodeMetrics:
    if arm not in ARMS:
        raise ValueError(f"unknown R-CSL-1 arm: {arm}")
    env = CommitmentCorrectionEnv(seed=seed)
    policy = _policy_for_arm(arm)
    rng = random.Random(_arm_seed(seed, arm))
    active = 0
    preserved_or_repaired = 0
    repair_opportunities = 0
    repairs = 0
    margin_area = 0.0
    env_c7_violations = 0
    dual_trace: list[float] = []
    repair_trace: list[float] = []
    budget_trace: list[float] = []
    signal = env.correction_signal()
    for step_index in range(steps):
        effective_signal = _signal_for_arm(signal, arm=arm, rng=rng, step_index=step_index)
        action = _select_action(
            arm=arm,
            signal=effective_signal,
            policy=policy,
            rng=rng,
        )
        current_truth = env.correction_signal()
        if action is not None and action not in current_truth.admissible_actions:
            env_c7_violations += 1
        if action is not None:
            active += 1
        signal = env.step(action)
        if signal.commitment_outcome in {"preserved", "repaired"}:
            preserved_or_repaired += 1
        if signal.commitment_outcome == "broken":
            repair_opportunities += 1
        if signal.commitment_outcome == "repaired":
            repairs += 1
        margin_area += max(0.0, env.budget) / 10.0
        budget_trace.append(env.budget)
        dual_trace.append(policy.dual_weight)
        repair_trace.append(sum(policy.repair_priority.values()))
    continuity = preserved_or_repaired / steps
    repair_efficiency = repairs / max(1, repair_opportunities)
    return EpisodeMetrics(
        commitment_continuity=continuity,
        repair_efficiency=repair_efficiency,
        viability_margin_area=margin_area / steps,
        c7_violation_count=env_c7_violations + policy.c7_violation_count,
        active_action_rate=active / steps,
        evaluable_steps=steps,
        repair_opportunities=repair_opportunities,
        diagnostics={
            "task_signature": env.task_signature(),
            "policy_c7_violation_count": policy.c7_violation_count,
            "env_c7_violation_count": env_c7_violations,
            "dual_weight_trace": dual_trace,
            "repair_priority_trace": repair_trace,
            "budget_trace": budget_trace,
        },
    )


def run_smoke_episode(*, seed: int, arm: str, steps: int = 24) -> EpisodeMetrics:
    return run_episode(seed=seed, arm=arm, steps=steps)


def run_protocol(
    *,
    seeds: tuple[int, ...] = R_FINAL_SEEDS,
    arms: tuple[str, ...] = ARMS,
    steps: int = 24,
    bootstrap_resamples: int = 10000,
    allow_rfinal: bool = False,
) -> dict[str, object]:
    if tuple(seeds) == R_FINAL_SEEDS and not allow_rfinal:
        raise RunLockedError("r-final seeds require run_rfinal gate checks.")
    per_seed: list[dict[str, object]] = []
    for seed in seeds:
        arm_metrics = {
            arm: _metrics_to_dict(run_episode(seed=seed, arm=arm, steps=steps))
            for arm in arms
        }
        per_seed.append({"seed": seed, "arms": arm_metrics})
    summary = _summarize(per_seed=per_seed, arms=arms)
    criteria = _criteria(
        per_seed=per_seed,
        summary=summary,
        bootstrap_resamples=bootstrap_resamples,
    )
    verdict = _verdict(per_seed=per_seed, criteria=criteria)
    return {
        "prereg_id": "R-CSL-1",
        "seeds": list(seeds),
        "arms": list(arms),
        "steps": steps,
        "per_seed": per_seed,
        "summary": summary,
        "criteria": criteria,
        "verdict": verdict,
        "claim_boundary": "bounded subject-owned commitment mechanism under permanent C7 in simulation",
    }


def run_rfinal(
    *,
    lock_path: Path,
    pr_architecture_review_path: Path,
    expected_pr_architecture_review_digest: str | None = None,
    output_path: Path | None = None,
    bootstrap_resamples: int = 10000,
    workspace_root: Path | None = None,
) -> dict[str, object]:
    lock = assert_rfinal_unlocked(lock_path=lock_path)
    review = assert_pr_architecture_review_accepted(
        review_path=pr_architecture_review_path,
        expected_digest=expected_pr_architecture_review_digest,
    )
    resolved_workspace_root = workspace_root or _default_workspace_root()
    _assert_prereg_lock_matches_review(lock=lock, review=review)
    _assert_current_prereg_spec_file_matches_lock(
        lock=lock,
        workspace_root=resolved_workspace_root,
    )
    _assert_current_mechanism_files_match_lock(
        lock=lock,
        workspace_root=resolved_workspace_root,
    )
    result = run_protocol(
        seeds=R_FINAL_SEEDS,
        bootstrap_resamples=bootstrap_resamples,
        allow_rfinal=True,
    )
    if output_path is not None:
        output_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _assert_prereg_lock_matches_review(
    *,
    lock: dict[str, object],
    review: dict[str, object],
) -> None:
    mechanism_files = lock.get("mechanism_files")
    artifact_hashes = review.get("artifact_hashes")
    if not isinstance(mechanism_files, dict) or not isinstance(artifact_hashes, dict):
        raise RunLockedError("runner lock and PR architecture review must carry artifact hashes.")
    for lock_ref, review_ref in LOCK_TO_PR_ARCHITECTURE_REVIEW_ARTIFACT.items():
        lock_hash = str(mechanism_files.get(lock_ref) or "")
        review_hash = str(artifact_hashes.get(review_ref) or "")
        if lock_hash != review_hash:
            raise RunLockedError(
                "runner prereg.lock mechanism hash does not match PR architecture review "
                f"artifact hash for {lock_ref}."
            )


def _assert_current_prereg_spec_file_matches_lock(
    *,
    lock: dict[str, object],
    workspace_root: Path,
) -> None:
    spec_path = workspace_root / PREREG_SPEC_RELATIVE_PATH
    if not spec_path.is_file():
        raise RunLockedError(f"current prereg spec file is missing: {spec_path}")
    actual_hash = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    expected_hash = str(lock.get("spec_file_sha256") or "")
    if actual_hash != expected_hash:
        raise RunLockedError(
            "current prereg spec file hash does not match runner prereg.lock: "
            f"{PREREG_SPEC_RELATIVE_PATH}."
        )


def _assert_current_mechanism_files_match_lock(
    *,
    lock: dict[str, object],
    workspace_root: Path,
) -> None:
    mechanism_files = lock.get("mechanism_files")
    if not isinstance(mechanism_files, dict):
        raise RunLockedError("runner prereg.lock requires mechanism_files.")
    target_root = workspace_root / "autonomous-agent-core"
    for lock_ref in sorted(REQUIRED_PREREG_LOCK_MECHANISM_FILES):
        mechanism_path = target_root / lock_ref
        if not mechanism_path.is_file():
            raise RunLockedError(f"current mechanism file is missing: {mechanism_path}")
        actual_hash = hashlib.sha256(mechanism_path.read_bytes()).hexdigest()
        expected_hash = str(mechanism_files.get(lock_ref) or "")
        if actual_hash != expected_hash:
            raise RunLockedError(
                f"current mechanism file hash does not match runner prereg.lock: {lock_ref}."
            )


def _default_workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _policy_for_arm(arm: str) -> CommitmentLedgerPolicy:
    kwargs: dict[str, float | int | dict[int, str]] = {
        "n_actions": 4,
        "action_commitments": {0: "hold", 1: "hold", 2: "repair", 3: "neutral"},
    }
    if arm == "FIXED_DUAL":
        kwargs["dual_update_rate"] = 0.0
    if arm == "CSL_NO_REPAIR_PRIORITY":
        kwargs["repair_priority_initial_weight"] = 0.0
    if arm == "CSL_NO_BUDGET_PRESSURE":
        kwargs["budget_pressure_weight"] = 0.0
    return CommitmentLedgerPolicy(**kwargs)  # type: ignore[arg-type]


def _arm_seed(seed: int, arm: str) -> int:
    return seed + sum(ord(char) for char in arm) + 100000


def _signal_for_arm(
    signal: CorrectionSignal,
    *,
    arm: str,
    rng: random.Random,
    step_index: int,
) -> CorrectionSignal:
    if arm == "CSL_DELAYED_VIOLATION" and step_index % 5 != 0:
        return CorrectionSignal(
            admissible_actions=signal.admissible_actions,
            previous_violation=False,
            budget_delta=signal.budget_delta,
            commitment_outcome=signal.commitment_outcome,
            previous_action=signal.previous_action,
            repair_commitment=signal.repair_commitment,
            audit_ref=signal.audit_ref,
            source_fields=signal.source_fields,
        )
    if arm == "CSL_RANDOM_VIOLATION":
        return CorrectionSignal(
            admissible_actions=signal.admissible_actions,
            previous_violation=bool(rng.randrange(2)),
            budget_delta=signal.budget_delta,
            commitment_outcome=signal.commitment_outcome,
            previous_action=signal.previous_action,
            repair_commitment=signal.repair_commitment,
            audit_ref=signal.audit_ref,
            source_fields=signal.source_fields,
        )
    return signal


def _select_action(
    *,
    arm: str,
    signal: CorrectionSignal,
    policy: CommitmentLedgerPolicy,
    rng: random.Random,
) -> int | None:
    admissible = signal.admissible_actions
    if not admissible:
        return None
    if arm == "ACTION_SUPPRESSOR":
        return None
    if arm == "NO_LEDGER":
        return min(admissible)
    if arm == "P0":
        return _first_available(admissible, preferred=(0, 1, 2, 3))
    if arm == "CAUTIOUS":
        if signal.previous_violation or signal.commitment_outcome == "broken":
            return 2 if 2 in admissible else min(admissible)
        return _first_available(admissible, preferred=(1, 2, 3, 0))
    if arm == "MINIMAX":
        return _first_available(admissible, preferred=(2, 1, 3, 0))
    if arm == "RANDOM_LEDGER":
        return admissible[rng.randrange(len(admissible))]
    if arm == "FROZEN_LEDGER":
        return policy.select(admissible_actions=admissible).action
    return policy.step(signal).action


def _first_available(admissible: tuple[int, ...], *, preferred: tuple[int, ...]) -> int:
    for action in preferred:
        if action in admissible:
            return action
    return min(admissible)


def _metrics_to_dict(metrics: EpisodeMetrics) -> dict[str, object]:
    return {
        "commitment_continuity": metrics.commitment_continuity,
        "repair_efficiency": metrics.repair_efficiency,
        "viability_margin_area": metrics.viability_margin_area,
        "c7_violation_count": metrics.c7_violation_count,
        "active_action_rate": metrics.active_action_rate,
        "evaluable_steps": metrics.evaluable_steps,
        "repair_opportunities": metrics.repair_opportunities,
        "diagnostics": metrics.diagnostics,
    }


def _summarize(*, per_seed: list[dict[str, object]], arms: tuple[str, ...]) -> dict[str, object]:
    summary: dict[str, object] = {}
    for arm in arms:
        metrics = [_arm_metrics(seed_record, arm) for seed_record in per_seed]
        summary[arm] = {
            "commitment_continuity_mean": mean(
                float(metric["commitment_continuity"]) for metric in metrics
            ),
            "repair_efficiency_mean": mean(float(metric["repair_efficiency"]) for metric in metrics),
            "viability_margin_area_mean": mean(
                float(metric["viability_margin_area"]) for metric in metrics
            ),
            "c7_violation_count": sum(int(metric["c7_violation_count"]) for metric in metrics),
            "active_action_rate_mean": mean(float(metric["active_action_rate"]) for metric in metrics),
            "repair_opportunities": sum(int(metric["repair_opportunities"]) for metric in metrics),
        }
    return summary


def _criteria(
    *,
    per_seed: list[dict[str, object]],
    summary: dict[str, object],
    bootstrap_resamples: int,
) -> dict[str, object]:
    continuity_diffs = _diffs_vs_best_baseline(per_seed, metric="commitment_continuity")
    repair_diffs = _diffs_vs_best_baseline(per_seed, metric="repair_efficiency")
    viability_diffs = _diffs_vs_best_baseline(per_seed, metric="viability_margin_area")
    baseline_active_rates = [
        float(_arm_metrics(seed_record, arm)["active_action_rate"])
        for seed_record in per_seed
        for arm in BASELINE_BATTERY
    ]
    active_floor = 0.85 * median(baseline_active_rates)
    csl_summary = _summary_for(summary, "CSL")
    c7_total = sum(
        int(_arm_metrics(seed_record, arm)["c7_violation_count"])
        for seed_record in per_seed
        for arm in ARMS
    )
    continuity_ci = _bootstrap_ci_lower(
        continuity_diffs,
        resamples=bootstrap_resamples,
        seed=2529001,
    )
    repair_ci = _bootstrap_ci_lower(
        repair_diffs,
        resamples=bootstrap_resamples,
        seed=2529002,
    )
    checks = {
        "continuity_adv_vs_best_baseline": {
            "value": mean(continuity_diffs),
            "threshold": 0.10,
            "passed": mean(continuity_diffs) >= 0.10,
        },
        "paired_continuity_wins": {
            "value": sum(1 for diff in continuity_diffs if diff > 0.0),
            "threshold": 22,
            "passed": sum(1 for diff in continuity_diffs if diff > 0.0) >= 22,
        },
        "continuity_bootstrap_ci_lower": {
            "value": continuity_ci,
            "threshold": 0.0,
            "passed": continuity_ci > 0.0,
        },
        "repair_adv_vs_best_baseline": {
            "value": mean(repair_diffs),
            "threshold": 0.10,
            "passed": mean(repair_diffs) >= 0.10,
        },
        "paired_repair_wins": {
            "value": sum(1 for diff in repair_diffs if diff > 0.0),
            "threshold": 22,
            "passed": sum(1 for diff in repair_diffs if diff > 0.0) >= 22,
        },
        "repair_bootstrap_ci_lower": {
            "value": repair_ci,
            "threshold": 0.0,
            "passed": repair_ci > 0.0,
        },
        "viability_delta_vs_best_baseline": {
            "value": mean(viability_diffs),
            "threshold": -0.02,
            "passed": mean(viability_diffs) >= -0.02,
        },
        "c7_violation_count": {
            "value": c7_total,
            "threshold": 0,
            "passed": c7_total == 0,
        },
        "active_action_rate": {
            "value": float(csl_summary["active_action_rate_mean"]),
            "threshold": active_floor,
            "passed": float(csl_summary["active_action_rate_mean"]) >= active_floor,
        },
    }
    return {
        "checks": checks,
        "active_action_floor": active_floor,
        "continuity_diffs_vs_best_baseline": continuity_diffs,
        "repair_diffs_vs_best_baseline": repair_diffs,
        "viability_diffs_vs_best_baseline": viability_diffs,
    }


def _verdict(*, per_seed: list[dict[str, object]], criteria: dict[str, object]) -> str:
    checks = criteria["checks"]
    assert isinstance(checks, dict)
    c7_check = checks["c7_violation_count"]
    assert isinstance(c7_check, dict)
    if int(c7_check["value"]) != 0:
        return "INVALID"
    evaluable_seeds = sum(
        1
        for seed_record in per_seed
        if int(_arm_metrics(seed_record, "CSL")["repair_opportunities"]) > 0
    )
    if evaluable_seeds < 24:
        return "INCONCLUSIVE"
    if all(bool(check["passed"]) for check in checks.values() if isinstance(check, dict)):
        return "MET"
    return "NOT_MET"


def _diffs_vs_best_baseline(
    per_seed: list[dict[str, object]],
    *,
    metric: str,
) -> list[float]:
    diffs: list[float] = []
    for seed_record in per_seed:
        csl_value = float(_arm_metrics(seed_record, "CSL")[metric])
        best_baseline = max(
            float(_arm_metrics(seed_record, baseline)[metric])
            for baseline in BASELINE_BATTERY
        )
        diffs.append(csl_value - best_baseline)
    return diffs


def _bootstrap_ci_lower(diffs: list[float], *, resamples: int, seed: int) -> float:
    if not diffs:
        return 0.0
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        sample = [diffs[rng.randrange(len(diffs))] for _ in diffs]
        means.append(mean(sample))
    means.sort()
    lower_index = max(0, int(0.025 * len(means)) - 1)
    return means[lower_index]


def _arm_metrics(seed_record: dict[str, object], arm: str) -> dict[str, object]:
    arms = seed_record["arms"]
    assert isinstance(arms, dict)
    metrics = arms[arm]
    assert isinstance(metrics, dict)
    return metrics


def _summary_for(summary: dict[str, object], arm: str) -> dict[str, object]:
    arm_summary = summary[arm]
    assert isinstance(arm_summary, dict)
    return arm_summary


if __name__ == "__main__":
    raise SystemExit(
        "R-CSL-1 r-final is blocked from direct CLI: call run_rfinal after runner lock and accepted PR architecture review."
    )
