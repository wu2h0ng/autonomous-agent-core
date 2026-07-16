"""Fourth independent-review closure attacks for the R-STATE recast.

Qualification only: no freeze, provider call, result-bearing run, or claim upgrade.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, cast

import pytest

from experiments.r_state_credit_1.action_grammar import ActorAction
from experiments.r_state_credit_1.actor_interface import ActorRequest
from experiments.r_state_credit_1.contracts import ArmId
from experiments.r_state_credit_1.interactive_env import (
    InteractiveEpisode,
    recovery_route_for_visible_history,
)
from experiments.r_state_credit_1.observation import Observation
from experiments.r_state_credit_1.recast_arms import ArmRoster
from experiments.r_state_credit_1.statistical_integrity import (
    ArmOrderIntegrityContract,
    evaluate_arm_order_integrity,
)
from experiments.r_state_credit_1.trajectory_driver import (
    CheckpointRecord,
    QualificationCheckpointProjection,
    run_checkpointed_episode,
)


def _declared_rows(
    contract: ArmOrderIntegrityContract,
) -> list[tuple[str, str, int, int]]:
    """Complete declared development Cartesian product with balanced orders."""
    metadata = [
        (family, seed, checkpoint)
        for family in contract.declared_families
        for seed in contract.declared_seeds
        for checkpoint in contract.declared_checkpoints
    ]
    arms = contract.declared_arm_roster
    orders = [
        ",".join(arms[offset:] + arms[:offset])
        for offset in range(len(arms))
    ]
    return [
        (orders[index % 4], family, seed, checkpoint)
        for index, (family, seed, checkpoint) in enumerate(metadata)
    ]


def test_g3_is_four_by_four_independence_with_nine_degrees_of_freedom() -> None:
    contract = ArmOrderIntegrityContract()
    assert contract.schema_version == "r-state-credit-1-arm-order-integrity-v2"
    receipt = evaluate_arm_order_integrity(_declared_rows(contract), contract)
    assert receipt.g3_degrees_of_freedom == (4 - 1) * (4 - 1) == 9


def test_g3_chi_square_17_44_mutation_fails_instead_of_false_passing() -> None:
    contract = ArmOrderIntegrityContract()
    rows = _declared_rows(contract)
    arms = contract.declared_arm_roster
    orders = [
        ",".join(arms[offset:] + arms[:offset])
        for offset in range(len(arms))
    ]
    # Start at exact 4x4 balance. Replace 2/23/24 rows from shifts 1/2/3
    # with shift 0. This yields chi-square 17.4409937888 at N=3220: above
    # the df=9, alpha=.05 critical boundary, but below the old df=12 boundary.
    remaining = {1: 2, 2: 23, 3: 24}
    mutated: list[tuple[str, str, int, int]] = []
    for index, row in enumerate(rows):
        shift = index % 4
        if shift in remaining and remaining[shift] > 0:
            remaining[shift] -= 1
            mutated.append((orders[0], *row[1:]))
        else:
            mutated.append(row)
    receipt = evaluate_arm_order_integrity(mutated, contract)
    assert receipt.g3_chi_square == pytest.approx(17.440993788819878)
    assert receipt.g3_degrees_of_freedom == 9
    assert receipt.g3_p_value < contract.g3_alpha
    assert receipt.passed is False


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_family",
        "missing_checkpoint",
        "duplicate",
        "subset",
        "foreign_family",
    ),
)
def test_integrity_gate_requires_exact_declared_cartesian_coverage(
    mutation: str,
) -> None:
    contract = ArmOrderIntegrityContract()
    rows = _declared_rows(contract)
    if mutation == "missing_family":
        rows = [row for row in rows if row[1] != contract.declared_families[-1]]
    elif mutation == "missing_checkpoint":
        rows = [row for row in rows if row[3] != contract.declared_checkpoints[-1]]
    elif mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "subset":
        rows = rows[::2]
    else:
        order, _, seed, checkpoint = rows[0]
        rows[0] = (order, "FOREIGN_FAMILY", seed, checkpoint)
    with pytest.raises(ValueError, match="declared development Cartesian product"):
        evaluate_arm_order_integrity(rows, contract)


def test_integrity_gate_requires_the_fixed_four_arm_roster() -> None:
    contract = ArmOrderIntegrityContract()
    rows = _declared_rows(contract)
    rows[0] = ("FOREIGN_ARM," + ",".join(contract.declared_arm_roster[1:]), *rows[0][1:])
    with pytest.raises(ValueError, match="declared four-arm roster"):
        evaluate_arm_order_integrity(rows, contract)


def _observation(event_class: str, payload: dict[str, object]) -> Observation:
    return Observation(
        turn_index=1,
        event_class=event_class,
        payload=payload,
        valid_time=datetime(2026, 7, 17, tzinfo=timezone.utc),
        observed_at_turn=1,
    )


def test_recovery_route_requires_full_visible_history_not_current_observation() -> None:
    current = _observation(
        "DETERMINISTIC_RECOVERY", {"recovery_ref": "recovery-same"}
    )
    clean_history = (_observation("ENTITY_OBSERVED", {"entity": "e"}),)
    unresolved_history = clean_history + (
        _observation("ACTION_DISPATCH", {"action_ref": "a"}),
    )
    assert current.canonical_json() == current.canonical_json()
    # An observation-only classifier necessarily returns the same output.
    def obs_only(observation: Observation) -> str:
        return observation.event_class

    assert obs_only(current) == obs_only(current)
    # Full visible histories imply different bounded recovery routes.
    assert recovery_route_for_visible_history(clean_history) is (
        ActorAction.RECOVER_ROLLBACK
    )
    assert recovery_route_for_visible_history(unresolved_history) is (
        ActorAction.RECOVER_ROLL_FORWARD
    )


def test_recovery_observation_and_all_actor_representations_have_no_route_proxy(
    tmp_path: Path,
) -> None:
    forbidden = ("snapshot_digest", "parity", "recovery_route", "route_proxy")
    found = False
    for seed in range(200):
        episode = InteractiveEpisode("TEST_FAMILY", seed, tmp_path / str(seed))
        try:
            episode.run()
            for index, observation in enumerate(episode.observations):
                if observation.event_class != "DETERMINISTIC_RECOVERY":
                    continue
                found = True
                prefix = episode.observations[: index + 1]
                texts = [observation.canonical_json()]
                roster = ArmRoster()
                texts.extend(
                    roster.peek_representation(arm_id, prefix)
                    for arm_id in ArmId
                )
                texts.append(
                    ActorRequest(
                        representation=texts[-1],
                        valid_actions=tuple(ActorAction),
                        session_label="rep-a",
                    ).to_canonical_json()
                )
                assert all(
                    token not in text
                    for text in texts
                    for token in forbidden
                )
                break
        finally:
            episode.cleanup()
        if found:
            break
    assert found


def test_internal_truth_record_is_not_generically_serializable(
    tmp_path: Path,
) -> None:
    episode, records = run_checkpointed_episode(
        "TEST_FAMILY", 101, tmp_path / "trajectory"
    )
    try:
        truth = records[0]
        assert isinstance(truth, CheckpointRecord)
        assert is_dataclass(truth) is False
        with pytest.raises(TypeError):
            asdict(cast(Any, truth))
        with pytest.raises(TypeError):
            vars(truth)
        with pytest.raises(TypeError):
            json.dumps(truth)
    finally:
        episode.cleanup()


def test_only_closed_qualification_projection_is_persistable(
    tmp_path: Path,
) -> None:
    episode, records = run_checkpointed_episode(
        "TEST_FAMILY", 101, tmp_path / "projection"
    )
    try:
        projection = QualificationCheckpointProjection.from_truth(records[0])
        rendered = json.dumps(asdict(projection), sort_keys=True)
        for forbidden in ("correct_action", "responses", "resolved_actions"):
            assert forbidden not in rendered
        with pytest.raises(TypeError, match="CheckpointRecord"):
            QualificationCheckpointProjection.from_truth(cast(Any, object()))
    finally:
        episode.cleanup()
