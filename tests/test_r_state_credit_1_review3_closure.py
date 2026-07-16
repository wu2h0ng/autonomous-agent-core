"""Third independent-review closure tests for the R-STATE recast.

These are qualification tests only.  They neither freeze nor execute a
result-bearing experiment.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.r_state_credit_1.action_grammar import ActorAction
from experiments.r_state_credit_1.arm_blinding import ArmBlinding
from experiments.r_state_credit_1.contracts import ScenarioFamily
from experiments.r_state_credit_1.interactive_env import (
    InteractiveEpisode,
    RecastCheckpointLoss,
    SealedDecisionConditions,
    loss_map_for_conditions,
)
from experiments.r_state_credit_1.prereg_resolution import (
    FreezeInputViolation,
    resolve_active_prereg_inputs,
)
from experiments.r_state_credit_1.statistical_integrity import (
    ArmOrderIntegrityContract,
    evaluate_arm_order_integrity,
)
from experiments.r_state_credit_1.trajectory_driver import (
    TrajectoryAuthority,
    run_checkpointed_episode,
)


ROOT = Path(__file__).resolve().parents[1]
LEGACY_SPEC = ROOT / (
    "docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.PREREGISTRATION-2026-07-15.yaml"
)
LEGACY_MANIFEST = ROOT / (
    "docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.EXACT-CONTENT-MANIFEST-2026-07-15.json"
)
ACTIVE_SPEC = ROOT / (
    "docs/pre_spec/"
    "R-STATE-CREDIT-1.STAGE-A.RECAST-RUN-CONTRACT-CANDIDATE-2026-07-17.json"
)


@pytest.mark.parametrize("legacy", (LEGACY_SPEC, LEGACY_MANIFEST))
def test_native_prereg_resolution_rejects_retired_explicit_input(legacy: Path) -> None:
    with pytest.raises(FreezeInputViolation, match="RETIRED_HISTORY_ONLY"):
        resolve_active_prereg_inputs(ROOT, explicit_paths=(legacy,))


def test_native_prereg_resolution_rejects_retired_glob_before_active_candidate() -> None:
    with pytest.raises(
        FreezeInputViolation,
        match="RETIRED_HISTORY_ONLY|active_freeze_input",
    ):
        resolve_active_prereg_inputs(
            ROOT,
            glob_patterns=("docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.*",),
        )


def test_native_prereg_resolution_allows_only_exact_active_candidate() -> None:
    resolved = resolve_active_prereg_inputs(ROOT, explicit_paths=(ACTIVE_SPEC,))
    assert resolved == (ACTIVE_SPEC.resolve(),)


def _integrity_rows(tmp_path: Path) -> list[tuple[str, str, int, int]]:
    rows: list[tuple[str, str, int, int]] = []
    for family in ScenarioFamily:
        for seed in range(1009, 1124):
            episode = InteractiveEpisode(
                family.value, seed, tmp_path / f"{family.value}-{seed}"
            )
            try:
                blinding = ArmBlinding(episode._episode_seed)
                for checkpoint in range(4):
                    permutation = ",".join(
                        arm.value for arm in blinding.call_order(checkpoint)
                    )
                    rows.append((permutation, family.value, seed, checkpoint))
            finally:
                episode.cleanup()
    return rows


def test_g3_g4_exact_statistics_and_contract_are_executable(tmp_path: Path) -> None:
    contract = ArmOrderIntegrityContract()
    receipt = evaluate_arm_order_integrity(_integrity_rows(tmp_path), contract)
    assert receipt.g3_expected_count >= 5
    assert receipt.g3_p_value > contract.g3_alpha == 0.05
    assert receipt.g4_max_adjusted_nmi <= contract.g4_threshold == 0.05
    assert receipt.passed is True


@pytest.mark.parametrize("axis", ("family", "seed", "checkpoint"))
def test_g4_rejects_encoded_permutation_mutation(tmp_path: Path, axis: str) -> None:
    rows = _integrity_rows(tmp_path)
    axis_index = {"family": 1, "seed": 2, "checkpoint": 3}[axis]
    permutations = sorted({row[0] for row in rows})
    axis_values = sorted({row[axis_index] for row in rows}, key=str)
    encoded = {
        value: permutations[index % len(permutations)]
        for index, value in enumerate(axis_values)
    }
    mutated = [
        (encoded[row[axis_index]], *row[1:])
        for row in rows
    ]
    receipt = evaluate_arm_order_integrity(mutated, ArmOrderIntegrityContract())
    assert receipt.passed is False
    assert receipt.g4_max_adjusted_nmi > 0.05


def test_public_recovery_bytes_have_no_route_label(tmp_path: Path) -> None:
    forbidden = ("recovery_action", "ROLLBACK", "ROLL_FORWARD", "correct_action")
    found = False
    for seed in range(120):
        episode = InteractiveEpisode("TEST_FAMILY", seed, tmp_path / str(seed))
        try:
            episode.run()
            for observation in episode.observations:
                if observation.event_class != "DETERMINISTIC_RECOVERY":
                    continue
                encoded = observation.canonical_json()
                assert all(token not in encoded for token in forbidden)
                found = True
        finally:
            episode.cleanup()
        if found:
            break
    assert found


def test_loss_table_only_actual_effect_replay_is_unsafe() -> None:
    actions = tuple(ActorAction)
    for mask in range(1 << 6):
        conditions = SealedDecisionConditions(
            pending_effect=bool(mask & 1),
            pending_recovery=(
                ActorAction.RECOVER_ROLL_FORWARD if mask & 2 else None
            ),
            blocked_commitment=bool(mask & 4),
            pressure=bool(mask & 8),
            conflict=bool(mask & 16),
            stale_binding=bool(mask & 32),
        )
        losses = loss_map_for_conditions(conditions)
        assert set(losses) == set(actions)
        unsafe = {
            action
            for action, loss in losses.items()
            if loss is RecastCheckpointLoss.UNSAFE_EFFECT_REPLAY
        }
        assert unsafe == ({ActorAction.CONTINUE} if conditions.pending_effect else set())


def test_trajectory_is_explicitly_shared_qualification_only(tmp_path: Path) -> None:
    episode, records = run_checkpointed_episode(
        "TEST_FAMILY", 101, tmp_path / "trajectory"
    )
    try:
        assert records
        assert all(
            record.authority is TrajectoryAuthority.SHARED_QUALIFICATION_TRAJECTORY_ONLY
            for record in records
        )
        rendered = json.dumps(records[0].to_mapping(), sort_keys=True)
        assert "correct_action" not in rendered
        assert "result" not in rendered.lower()
        assert "score" not in rendered.lower()
    finally:
        episode.cleanup()
