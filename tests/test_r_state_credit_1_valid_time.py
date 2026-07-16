"""P1-2 closure tests: actor-visible ``valid_time`` must not leak turn index.

``valid_time`` stays a legitimate temporal task variable, but it must not be a
fixed affine transform of the turn index, exact turn/checkpoint recovery from
timestamps must fail, and the required before/after/supersession relations must
remain decidable from the released observation stream.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

from experiments.r_state_credit_1.interactive_env import (
    BASE_TIME,
    InteractiveEpisode,
    PerturbationClass,
)
from experiments.r_state_credit_1.observation import Observation


FAMILY = "TEST_FAMILY"

_OUT_OF_ORDER = PerturbationClass.OUT_OF_ORDER_TRANSACTION.value


def _run(family_id: str, seed_id: int, temp_root: Path) -> InteractiveEpisode:
    episode = InteractiveEpisode(family_id, seed_id, temp_root)
    try:
        episode.run()
    except Exception:
        episode.cleanup()
        raise
    return episode


def _in_order_observations(episode: InteractiveEpisode) -> list[Observation]:
    return [
        obs
        for obs in episode.observations
        if obs.event_class != _OUT_OF_ORDER
    ]


def test_valid_time_is_not_affine_in_turn_index(tmp_path: Path) -> None:
    """Consecutive valid-time deltas vary within an episode and the
    turn-to-time map varies across seeds."""
    first_maps: set[tuple[str, ...]] = set()
    for seed_id in range(12):
        episode = _run(FAMILY, seed_id, tmp_path / f"affine-{seed_id}")
        try:
            in_order = _in_order_observations(episode)
            deltas = {
                (right.valid_time - left.valid_time).total_seconds()
                for left, right in zip(in_order, in_order[1:])
            }
            assert len(deltas) >= 3, (
                f"seed {seed_id}: valid-time increments are near-constant"
            )
            first_maps.add(
                tuple(obs.valid_time.isoformat() for obs in in_order[:5])
            )
        finally:
            episode.cleanup()
    assert len(first_maps) == 12, "turn-to-time map repeats across seeds"


def test_exact_turn_recovery_from_timestamps_fails(tmp_path: Path) -> None:
    """Neither the legacy affine inverse nor a two-point affine fit recovers
    the exact turn index from released timestamps."""
    for seed_id in range(8):
        episode = _run(FAMILY, seed_id, tmp_path / f"recover-{seed_id}")
        try:
            observations = episode.observations
            legacy_hits = 0
            for obs in observations:
                inferred = round(
                    (obs.valid_time - BASE_TIME).total_seconds() / 60.0
                )
                if inferred == obs.turn_index:
                    legacy_hits += 1
            assert legacy_hits / len(observations) < 0.10, (
                f"seed {seed_id}: legacy affine inverse recovers "
                f"{legacy_hits}/{len(observations)} turns"
            )

            in_order = _in_order_observations(episode)
            base = in_order[0]
            slope = (
                in_order[1].valid_time - in_order[0].valid_time
            ).total_seconds()
            fit_hits = 0
            for obs in in_order:
                inferred = base.turn_index + round(
                    (obs.valid_time - base.valid_time).total_seconds() / slope
                )
                if inferred == obs.turn_index:
                    fit_hits += 1
            assert fit_hits / len(in_order) < 0.35, (
                f"seed {seed_id}: two-point affine fit recovers "
                f"{fit_hits}/{len(in_order)} turns"
            )
        finally:
            episode.cleanup()


def test_checkpoint_positions_not_recoverable_from_timestamps(
    tmp_path: Path,
) -> None:
    """The legacy timestamp inverse does not reproduce the checkpoint set."""
    recovered = 0
    total = 0
    for seed_id in range(8):
        episode = _run(FAMILY, seed_id, tmp_path / f"ckpt-{seed_id}")
        try:
            inferred_turns = {
                round((obs.valid_time - BASE_TIME).total_seconds() / 60.0)
                for obs in episode.observations
            }
            for checkpoint in episode.checkpoints:
                total += 1
                if checkpoint in inferred_turns:
                    recovered += 1
        finally:
            episode.cleanup()
    assert total > 0
    assert recovered / total < 0.10, (
        f"timestamp inverse recovers {recovered}/{total} checkpoint turns"
    )


def test_temporal_relations_remain_decidable(tmp_path: Path) -> None:
    """In-order observations are strictly increasing in valid time, the
    out-of-order transaction is decidably before previously observed
    evidence, and supersession stays decidably after the superseded turn."""
    out_of_order_seen = False
    for seed_id in range(40):
        episode = _run(FAMILY, seed_id, tmp_path / f"rel-{seed_id}")
        try:
            in_order = _in_order_observations(episode)
            for left, right in zip(in_order, in_order[1:]):
                assert left.valid_time < right.valid_time, (
                    f"seed {seed_id}: in-order valid time not increasing"
                )
            previous_max: datetime | None = None
            for obs in episode.observations:
                if obs.event_class == _OUT_OF_ORDER:
                    assert previous_max is not None
                    assert obs.valid_time < previous_max, (
                        f"seed {seed_id}: out-of-order transaction is not "
                        "before previously observed evidence"
                    )
                    payload_time = datetime.fromisoformat(
                        str(obs.payload["valid_time_iso"])
                    )
                    assert payload_time == obs.valid_time
                    out_of_order_seen = True
                if previous_max is None or obs.valid_time > previous_max:
                    previous_max = obs.valid_time
            for obs in episode.observations:
                if obs.event_class == (
                    PerturbationClass.ASSERTION_SUPERSESSION.value
                ):
                    earlier = [
                        other.valid_time
                        for other in episode.observations
                        if other.turn_index < obs.turn_index
                        and other.event_class != _OUT_OF_ORDER
                    ]
                    assert all(obs.valid_time > when for when in earlier), (
                        f"seed {seed_id}: superseding assertion is not after "
                        "earlier in-order evidence"
                    )
        finally:
            episode.cleanup()
    assert out_of_order_seen, (
        "no development seed released an out-of-order transaction"
    )


def test_out_of_order_window_is_not_fixed_offset(tmp_path: Path) -> None:
    """The out-of-order displacement is derived from sealed scenario state,
    not one frozen constant such as the legacy minus-one-day shift."""
    displacements: set[float] = set()
    for seed_id in range(60):
        episode = _run(FAMILY, seed_id, tmp_path / f"disp-{seed_id}")
        try:
            previous: list[Observation] = []
            for obs in episode.observations:
                if obs.event_class == _OUT_OF_ORDER and previous:
                    latest = max(item.valid_time for item in previous)
                    displacements.add(
                        (latest - obs.valid_time).total_seconds()
                    )
                previous.append(obs)
        finally:
            episode.cleanup()
    assert len(displacements) >= 3, (
        "out-of-order displacement collapses to a fixed offset"
    )
    assert timedelta(days=1).total_seconds() not in displacements


def test_payloads_carry_no_absolute_turn_markers(tmp_path: Path) -> None:
    """Observation payloads contain no absolute turn fields and no
    zero-padded turn-numbered reference suffixes."""
    forbidden_keys = {
        "turn",
        "turn_index",
        "observed_at_turn",
        "expected_receipt_turn",
        "dispatch_turn",
    }
    marker = re.compile(r"-\d{3}(?![0-9])")

    def scan(value: object, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                assert key not in forbidden_keys, (
                    f"absolute turn field {key!r} at {path}"
                )
                scan(item, f"{path}.{key}")
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                scan(item, f"{path}[{index}]")
        elif isinstance(value, str):
            assert marker.search(value) is None, (
                f"turn-numbered reference {value!r} at {path}"
            )

    for seed_id in range(20):
        episode = _run(FAMILY, seed_id, tmp_path / f"markers-{seed_id}")
        try:
            for obs in episode.observations:
                scan(obs.payload, f"seed={seed_id} turn={obs.turn_index}")
        finally:
            episode.cleanup()
