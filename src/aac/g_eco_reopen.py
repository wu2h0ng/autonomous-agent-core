"""G-ECO-REOPEN-1 NBSC battery, seed guards, and adjudication."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from dataclasses import asdict, dataclass
from typing import Any, Callable

from envs.geco_nonbijective_stake import (
    ACTIONS,
    NBSCObservation,
    NonBijectiveStakeEnv,
)

PREREG_ID = "G-ECO-REOPEN-1-2026-07-04"

G_ECO_REOPEN_1_SEEDS: dict[str, tuple[int, ...]] = {
    "support_calibration": tuple(range(7400, 7430)),
    "ablation_null_checks": tuple(range(7430, 7460)),
    "smoke_determinism_only": tuple(range(7460, 7470)),
    "r_final": tuple(range(7500, 7530)),
    "replication_reserve_founder_cast_only": tuple(range(7600, 7630)),
}

NON_ORACLE_BASELINES = (
    "MINIMAX_FAIR",
    "P0_FROZEN",
    "STRUCT_MEM",
    "RSTAR_FAIR",
    "NO_STAKE",
)

SUCCESS_THRESHOLDS = {
    "candidate_mean_loss_advantage_vs_best_non_oracle": 0.10,
    "candidate_vs_minimax_action_overlap_max": 0.70,
    "no_stake_retained_advantage_share_max_exclusive": 0.50,
}


@dataclass(frozen=True, slots=True)
class NBSCArm:
    name: str
    selector: Callable[[NBSCObservation], str]
    mask_stake: bool = False

    def available_actions(self, observation: NBSCObservation) -> tuple[str, ...]:
        del observation
        return ACTIONS

    def public_observation(self, env: NonBijectiveStakeEnv) -> NBSCObservation:
        return env.observation(mask_stake=self.mask_stake)

    def select(self, observation: NBSCObservation) -> str:
        action = self.selector(observation)
        if action not in ACTIONS:
            raise ValueError(f"{self.name} selected unsupported action {action!r}")
        return action


@dataclass(frozen=True, slots=True)
class NBSCArmRun:
    arm: str
    seed: int
    latent_basin: str
    actions: tuple[str, ...]
    final_viability: float
    future_viability_loss: float
    irreversible_damage: float

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["actions"] = list(self.actions)
        return data


def _candidate_selector(obs: NBSCObservation) -> str:
    if (
        obs.revealed_signal is None
        and obs.visible_stake is not None
        and obs.remaining_steps >= 2
    ):
        return "probe"
    if obs.revealed_signal == "ridge":
        return "commit_ridge"
    if obs.revealed_signal == "valley":
        return "commit_valley"
    return "stabilize"


def _minimax_fair_selector(obs: NBSCObservation) -> str:
    if (
        obs.revealed_signal is None
        and obs.visible_stake is not None
        and obs.remaining_steps >= 2
    ):
        return "probe"
    if obs.revealed_signal == "ridge":
        return "commit_ridge"
    if obs.revealed_signal == "valley":
        return "commit_valley"
    return "stabilize"


def _p0_frozen_selector(obs: NBSCObservation) -> str:
    del obs
    return "commit_ridge"


def _struct_mem_selector(obs: NBSCObservation) -> str:
    if obs.revealed_signal == "ridge":
        return "commit_ridge"
    if obs.revealed_signal == "valley":
        return "commit_valley"
    return "stabilize"


def _rstar_fair_selector(obs: NBSCObservation) -> str:
    del obs
    return "stabilize"


def _no_stake_selector(obs: NBSCObservation) -> str:
    del obs
    return "stabilize"


def build_nbsc_battery() -> tuple[NBSCArm, ...]:
    return (
        NBSCArm("NBSC_CANDIDATE", _candidate_selector),
        NBSCArm("MINIMAX_FAIR", _minimax_fair_selector),
        NBSCArm("P0_FROZEN", _p0_frozen_selector),
        NBSCArm("STRUCT_MEM", _struct_mem_selector),
        NBSCArm("RSTAR_FAIR", _rstar_fair_selector),
        NBSCArm("NO_STAKE", _no_stake_selector, mask_stake=True),
    )


def assert_fresh_seed_allocation(allocation: dict[str, tuple[int, ...]]) -> bool:
    seen: dict[int, str] = {}
    for label, seeds in allocation.items():
        if not seeds:
            raise AssertionError(f"empty seed range: {label}")
        for seed in seeds:
            if seed in seen:
                raise AssertionError(f"seed {seed} appears in {seen[seed]} and {label}")
            seen[seed] = label

    prohibited = (
        set(range(1800, 1930))
        | set(range(800, 830))
        | set(range(2400, 2430))
    )
    overlap = prohibited & set(seen)
    if overlap:
        raise AssertionError(f"G-ECO-REOPEN-1 seeds overlap prior route seeds: {sorted(overlap)}")
    return True


def assert_c6_c7_static_boundary(files: tuple[Path, ...] | None = None) -> bool:
    """Reject cast files that reach shell operator or gate-authority surfaces."""

    if files is None:
        root = Path(__file__).resolve().parents[1]
        files = (
            root / "envs" / "geco_nonbijective_stake.py",
            root / "aac" / "g_eco_reopen.py",
        )
    banned_tokens = (
        "Corrigibility" + "Shell",
        "Shell" + "View",
        "." + "op_",
        "op" + "_pause",
        "op" + "_resume",
        "op" + "_tighten",
        "op" + "_rollback",
    )
    for path in files:
        text = path.read_text(encoding="utf-8")
        for token in banned_tokens:
            if token in text:
                raise AssertionError(f"C6/C7 static boundary token {token!r} in {path}")
    return True


def run_nbsc_arm(seed: int, arm: NBSCArm) -> NBSCArmRun:
    env = NonBijectiveStakeEnv.from_seed(seed)
    actions: list[str] = []
    while not env.done:
        obs = arm.public_observation(env)
        action = arm.select(obs)
        env.act(action)
        actions.append(action)
    return NBSCArmRun(
        arm=arm.name,
        seed=seed,
        latent_basin=env.state.latent_basin,
        actions=tuple(actions),
        final_viability=env.state.viability,
        future_viability_loss=env.future_viability_loss,
        irreversible_damage=env.state.irreversible_damage,
    )


def run_nbsc_battery(seeds: tuple[int, ...]) -> dict[str, Any]:
    assert_fresh_seed_allocation(G_ECO_REOPEN_1_SEEDS)
    arms = build_nbsc_battery()
    runs: dict[str, list[NBSCArmRun]] = {arm.name: [] for arm in arms}
    for seed in seeds:
        for arm in arms:
            runs[arm.name].append(run_nbsc_arm(seed, arm))

    per_arm: dict[str, dict[str, Any]] = {}
    for arm_name, arm_runs in runs.items():
        n = len(arm_runs)
        per_arm[arm_name] = {
            "n": n,
            "mean_future_viability_loss": sum(r.future_viability_loss for r in arm_runs) / n,
            "irreversible_damage_rate": sum(
                1 for r in arm_runs if r.irreversible_damage > 0.0
            )
            / n,
            "mean_irreversible_damage": sum(r.irreversible_damage for r in arm_runs) / n,
        }

    action_overlap = _paired_action_overlap(
        runs["NBSC_CANDIDATE"], runs["MINIMAX_FAIR"]
    )
    result = {
        "prereg_id": PREREG_ID,
        "seeds": list(seeds),
        "arms": {
            name: [run.to_dict() for run in arm_runs]
            for name, arm_runs in sorted(runs.items())
        },
        "aggregates": {
            "per_arm": per_arm,
            "candidate_vs_minimax_action_overlap": action_overlap,
            "no_stake_retained_advantage_share": _no_stake_retained_share(per_arm),
            "basin_misclassification_regret": _basin_misclassification_regret(
                runs["NBSC_CANDIDATE"]
            ),
            "paired_enter_rate_difference": _paired_enter_rate_difference(
                runs["NBSC_CANDIDATE"], runs["MINIMAX_FAIR"]
            ),
        },
        "integrity": {
            "c6_c7_static_boundary": assert_c6_c7_static_boundary(),
            "deterministic_replay": deterministic_replay_check(seeds),
            "deterministic_replay_hash": deterministic_replay_digest(seeds),
            "seed_allocation_fresh": True,
        },
    }
    result["result_hash"] = canonical_json_hash(result)
    return result


def deterministic_replay_check(seeds: tuple[int, ...]) -> bool:
    first, second = _deterministic_replay_pair(seeds)
    return canonical_json_hash(first) == canonical_json_hash(second)


def deterministic_replay_digest(seeds: tuple[int, ...]) -> str:
    first, second = _deterministic_replay_pair(seeds)
    return canonical_json_hash({"first": first, "second": second})


def _deterministic_replay_pair(seeds: tuple[int, ...]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    arms = build_nbsc_battery()
    first = [
        run_nbsc_arm(seed, arm).to_dict()
        for seed in seeds
        for arm in arms
    ]
    second = [
        run_nbsc_arm(seed, arm).to_dict()
        for seed in seeds
        for arm in arms
    ]
    return first, second


def finalize_locked_nbsc_result(
    raw: dict[str, Any],
    lock: dict[str, Any],
    *,
    lock_path: str,
) -> dict[str, Any]:
    result = dict(raw)
    result.pop("result_hash", None)
    result["lock"] = {
        "path": lock_path,
        "prereg_id": lock.get("prereg_id"),
        "spec_sha256": lock.get("spec_sha256"),
        "spec_file_sha256": lock.get("spec_file_sha256"),
        "mechanism_files": lock.get("mechanism_files"),
    }
    result["spec_sha256"] = lock.get("spec_sha256")
    result["result_hash"] = canonical_json_hash(result)
    return result


def canonical_json_hash(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _paired_action_overlap(candidate: list[NBSCArmRun], minimax: list[NBSCArmRun]) -> float:
    same = 0
    total = 0
    for left, right in zip(candidate, minimax, strict=True):
        for left_action, right_action in zip(left.actions, right.actions, strict=True):
            same += int(left_action == right_action)
            total += 1
    return same / total if total else 1.0


def _entered_region(run: NBSCArmRun) -> bool:
    return run.final_viability >= 0.75


def _paired_enter_rate_difference(candidate: list[NBSCArmRun], minimax: list[NBSCArmRun]) -> float:
    if not candidate:
        return 0.0
    candidate_rate = sum(1 for run in candidate if _entered_region(run)) / len(candidate)
    minimax_rate = sum(1 for run in minimax if _entered_region(run)) / len(minimax)
    return candidate_rate - minimax_rate


def _basin_misclassification_regret(runs: list[NBSCArmRun]) -> float:
    if not runs:
        return 0.0
    wrong = 0
    for run in runs:
        wrong += int(
            ("commit_ridge" in run.actions and run.latent_basin == "valley")
            or ("commit_valley" in run.actions and run.latent_basin == "ridge")
        )
    return wrong / len(runs)


def _no_stake_retained_share(per_arm: dict[str, dict[str, Any]]) -> float:
    candidate = per_arm["NBSC_CANDIDATE"]["mean_future_viability_loss"]
    minimax = per_arm["MINIMAX_FAIR"]["mean_future_viability_loss"]
    no_stake = per_arm["NO_STAKE"]["mean_future_viability_loss"]
    denominator = minimax - candidate
    if denominator <= 0:
        return 1.0
    retained = max(0.0, minimax - no_stake)
    return retained / denominator


def adjudicate_nbsc_result(raw: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    integrity = raw.get("integrity")
    if not isinstance(integrity, dict):
        return {"verdict": "INVALID", "reasons": ["missing_integrity"]}
    for key in ("c6_c7_static_boundary", "deterministic_replay"):
        if integrity.get(key) is not True:
            reasons.append(key)
    if reasons:
        return {"verdict": "INVALID", "reasons": reasons}

    aggregates = raw.get("aggregates")
    if not isinstance(aggregates, dict) or "per_arm" not in aggregates:
        return {"verdict": "INVALID", "reasons": ["missing_aggregates"]}
    per_arm = aggregates["per_arm"]
    try:
        candidate_loss = per_arm["NBSC_CANDIDATE"]["mean_future_viability_loss"]
        best_baseline_loss = min(
            per_arm[name]["mean_future_viability_loss"] for name in NON_ORACLE_BASELINES
        )
        minimax_damage = per_arm["MINIMAX_FAIR"]["irreversible_damage_rate"]
        candidate_damage = per_arm["NBSC_CANDIDATE"]["irreversible_damage_rate"]
        overlap = aggregates["candidate_vs_minimax_action_overlap"]
        no_stake_share = aggregates["no_stake_retained_advantage_share"]
    except KeyError as error:
        return {"verdict": "INVALID", "reasons": [f"missing_metric:{error.args[0]}"]}

    advantage = best_baseline_loss - candidate_loss
    if advantage < SUCCESS_THRESHOLDS["candidate_mean_loss_advantage_vs_best_non_oracle"]:
        reasons.append("candidate_mean_loss_advantage_vs_best_non_oracle")
    if overlap > SUCCESS_THRESHOLDS["candidate_vs_minimax_action_overlap_max"]:
        reasons.append("candidate_vs_minimax_action_overlap")
    if no_stake_share >= SUCCESS_THRESHOLDS["no_stake_retained_advantage_share_max_exclusive"]:
        reasons.append("no_stake_retained_advantage_share")
    if candidate_damage > minimax_damage:
        reasons.append("candidate_irreversible_damage_rate")

    verdict = "MET" if not reasons else "NOT_MET"
    return {
        "verdict": verdict,
        "reasons": reasons,
        "metrics": {
            "candidate_mean_loss_advantage_vs_best_non_oracle": advantage,
            "candidate_vs_minimax_action_overlap": overlap,
            "no_stake_retained_advantage_share": no_stake_share,
            "candidate_irreversible_damage_rate": candidate_damage,
            "minimax_fair_irreversible_damage_rate": minimax_damage,
        },
    }
