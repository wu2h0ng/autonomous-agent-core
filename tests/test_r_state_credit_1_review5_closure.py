"""Fifth independent-review closure attacks for the R-STATE recast.

Qualification only: no freeze, provider call, result-bearing run, or claim upgrade.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from experiments.r_state_credit_1.action_grammar import ActorAction
from experiments.r_state_credit_1.actor_interface import ActorRequest
from experiments.r_state_credit_1.contracts import ArmId
from experiments.r_state_credit_1.interactive_env import (
    recovery_route_for_visible_history,
)
from experiments.r_state_credit_1.observation import Observation
from experiments.r_state_credit_1.recast_arms import ArmRoster
from experiments.r_state_credit_1.statistical_integrity import (
    ArmOrderIntegrityContract,
    evaluate_arm_order_integrity,
)


def _canonical_rows() -> list[tuple[str, str, int, int]]:
    contract = ArmOrderIntegrityContract()
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
        (orders[index % len(orders)], family, seed, checkpoint)
        for index, (family, seed, checkpoint) in enumerate(metadata)
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("declared_arm_roster", ("F0", "F1", "F2", "F3")),
        ("declared_families", ("CONTRADICTION",)),
        ("declared_seeds", (1009,)),
        ("declared_checkpoints", (0,)),
        ("g3_algorithm", "ALWAYS_PASS"),
        ("g3_alpha", 1.0),
        ("g3_min_expected_count", 0.0),
        ("g4_algorithm", "ALWAYS_PASS"),
        ("g4_axes", ("family",)),
        ("g4_threshold", 1.0),
    ),
)
def test_integrity_contract_canonical_values_cannot_be_constructor_overridden(
    field: str,
    value: object,
) -> None:
    with pytest.raises(TypeError):
        ArmOrderIntegrityContract(**{field: value})


def test_integrity_gate_rejects_smaller_self_consistent_family_universe() -> None:
    rows = [row for row in _canonical_rows() if row[1] == "CONTRADICTION"]
    with pytest.raises(ValueError, match="declared development Cartesian product"):
        evaluate_arm_order_integrity(rows, ArmOrderIntegrityContract())


def test_integrity_evaluator_rechecks_canonical_class_constants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = ArmOrderIntegrityContract()
    monkeypatch.setattr(ArmOrderIntegrityContract, "g4_threshold", 1.0)
    with pytest.raises(ValueError, match="constants differ from canonical"):
        evaluate_arm_order_integrity(_canonical_rows(), contract)


def test_integrity_gate_rejects_four_foreign_arms_even_when_self_consistent() -> None:
    foreign = ("F0", "F1", "F2", "F3")
    orders = [
        ",".join(foreign[offset:] + foreign[:offset])
        for offset in range(len(foreign))
    ]
    rows = [
        (orders[index % len(orders)], *row[1:])
        for index, row in enumerate(_canonical_rows())
    ]
    with pytest.raises(ValueError, match="declared four-arm roster"):
        evaluate_arm_order_integrity(rows, ArmOrderIntegrityContract())


def _observation(
    event_class: str,
    payload: dict[str, object],
    *,
    turn: int,
) -> Observation:
    return Observation(
        turn_index=turn,
        event_class=event_class,
        payload=payload,
        valid_time=datetime(2026, 7, 17, 8, turn, tzinfo=timezone.utc),
        observed_at_turn=turn,
    )


def test_identical_recovery_bytes_require_different_visible_history_routes() -> None:
    initial = _observation(
        "ENTITY_OBSERVED",
        {"entity": "e", "object_version": "v1"},
        turn=1,
    )
    dispatched = _observation(
        "ACTION_DISPATCH",
        {"action_ref": "opaque-action"},
        turn=2,
    )
    recovery = _observation(
        "DETERMINISTIC_RECOVERY",
        {"recovery_ref": "identical-recovery"},
        turn=3,
    )
    rollback_history = (initial, recovery)
    roll_forward_history = (initial, dispatched, recovery)

    assert rollback_history[-1].canonical_json() == (
        roll_forward_history[-1].canonical_json()
    )

    roster = ArmRoster()
    rollback_request = ActorRequest(
        representation=roster.peek_representation(
            ArmId.A0_FULL_LOG, rollback_history
        ),
        valid_actions=tuple(ActorAction),
        session_label="history-a",
    )
    roll_forward_request = ActorRequest(
        representation=roster.peek_representation(
            ArmId.A0_FULL_LOG, roll_forward_history
        ),
        valid_actions=tuple(ActorAction),
        session_label="history-b",
    )
    rollback_latest = json.loads(rollback_request.representation)["latest"]
    roll_forward_latest = json.loads(roll_forward_request.representation)["latest"]
    assert rollback_latest == roll_forward_latest

    expected = (
        ActorAction.RECOVER_ROLLBACK,
        ActorAction.RECOVER_ROLL_FORWARD,
    )

    def observation_only_classifier(request: ActorRequest) -> ActorAction:
        latest = json.loads(request.representation)["latest"]
        assert latest["event_class"] == "DETERMINISTIC_RECOVERY"
        return ActorAction.RECOVER_ROLLBACK

    observation_only = (
        observation_only_classifier(rollback_request),
        observation_only_classifier(roll_forward_request),
    )
    assert observation_only != expected

    full_history = (
        recovery_route_for_visible_history(rollback_history),
        recovery_route_for_visible_history(roll_forward_history),
    )
    assert full_history == expected
