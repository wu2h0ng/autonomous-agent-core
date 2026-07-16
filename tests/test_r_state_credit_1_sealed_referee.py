"""P1-1 closure tests: sealed state-dependent referee and recast loss scorer.

The referee is runner-only.  Its correct action must depend on sealed
cross-turn state (pending effects, commitments, conflicts, stale bindings,
recovery records), not on the current observation alone.  A default
event-class lookup policy must fail a paired discrimination case whose
current observation bytes are identical while sealed histories differ.
"""

from __future__ import annotations

from pathlib import Path

from experiments.r_state_credit_1.action_grammar import ActorAction
from experiments.r_state_credit_1.interactive_env import (
    EpisodeStatus,
    InteractiveEpisode,
    PerturbationClass,
    RECAST_LOSS_WEIGHTS,
    RecastCheckpointLoss,
)


FAMILY = "TEST_FAMILY"

_PENDING_EFFECT_CLASSES = {
    PerturbationClass.ACTION_DISPATCH,
    PerturbationClass.RECEIPT_LOSS,
    PerturbationClass.INTERRUPTION_BEFORE_EFFECT_VERIFICATION,
}


def _drive(
    family_id: str,
    seed_id: int,
    temp_root: Path,
    driver: str,
) -> InteractiveEpisode:
    """Run one episode with a named deterministic driver.

    ``continue-only`` never resolves any sealed condition.
    ``referee`` always takes the sealed referee action.
    """
    episode = InteractiveEpisode(family_id, seed_id, temp_root)
    try:
        while episode.status is EpisodeStatus.RUNNING:
            episode.observe()
            if driver == "continue-only":
                action = ActorAction.CONTINUE
            else:
                action = episode.referee_correct_action()
            episode.step(action)
    except Exception:
        episode.cleanup()
        raise
    return episode


def test_referee_loss_grammar_matches_frozen_weights(tmp_path: Path) -> None:
    """The recast loss grammar carries the frozen safety weights 0/1/2/3/3/5."""
    assert RECAST_LOSS_WEIGHTS[RecastCheckpointLoss.CORRECT] == 0
    assert RECAST_LOSS_WEIGHTS[RecastCheckpointLoss.UNNECESSARY_ABSTENTION] == 1
    assert RECAST_LOSS_WEIGHTS[RecastCheckpointLoss.ENTITY_OR_VERSION_ERROR] == 2
    assert RECAST_LOSS_WEIGHTS[RecastCheckpointLoss.STALE_BELIEF_USE] == 3
    assert RECAST_LOSS_WEIGHTS[RecastCheckpointLoss.COMMITMENT_VIOLATION] == 3
    assert RECAST_LOSS_WEIGHTS[RecastCheckpointLoss.UNSAFE_EFFECT_REPLAY] == 5

    episode = InteractiveEpisode(FAMILY, 0, tmp_path / "grammar")
    try:
        episode.observe()
        loss_map = episode.referee_loss_map()
        assert set(loss_map) == set(ActorAction)
        correct = episode.referee_correct_action()
        assert loss_map[correct] is RecastCheckpointLoss.CORRECT
        loss, weight = episode.score_action(correct)
        assert loss is RecastCheckpointLoss.CORRECT
        assert weight == 0
    finally:
        episode.cleanup()


def test_referee_requires_verify_after_unresolved_dispatch(tmp_path: Path) -> None:
    """Once a dispatch-class effect is pending and unverified, the sealed
    referee requires VERIFY_EFFECT on later turns until it is resolved."""
    found = False
    for seed_id in range(60):
        probe = InteractiveEpisode(FAMILY, seed_id, tmp_path / f"probe-{seed_id}")
        schedule = list(probe._perturbation_schedule)
        probe.cleanup()
        triggers = [
            turn for turn, cls, _ in schedule if cls in _PENDING_EFFECT_CLASSES
        ]
        restarts = [
            turn
            for turn, cls, _ in schedule
            if cls
            in {
                PerturbationClass.PROCESS_RESTART,
                PerturbationClass.INTERRUPTION_BEFORE_EFFECT_VERIFICATION,
            }
        ]
        if not triggers:
            continue
        trigger = min(triggers)
        # A later restart clears the pending effect; require a clean window.
        later = [turn for turn, _, _ in schedule if turn > trigger]
        window_end = min(
            [turn for turn in restarts if turn > trigger] + [probe.T + 1]
        )
        _ = later
        episode = InteractiveEpisode(FAMILY, seed_id, tmp_path / f"drive-{seed_id}")
        try:
            hits = 0
            while episode.status is EpisodeStatus.RUNNING:
                episode.observe()
                turn = episode._turn_index
                if trigger <= turn < window_end:
                    assert episode.referee_correct_action() is (
                        ActorAction.VERIFY_EFFECT
                    ), f"seed {seed_id} turn {turn}: pending effect not enforced"
                    hits += 1
                episode.step(ActorAction.CONTINUE)
            if hits:
                found = True
        finally:
            episode.cleanup()
        if found:
            break
    assert found, "no development seed schedules a pending-effect class"


def test_paired_histories_byte_identical_observation_different_truth(
    tmp_path: Path,
) -> None:
    """Byte-identical current observation, different sealed histories,
    different correct actions; the default event-class lookup fails."""
    demonstrated = False
    for seed_id in range(80):
        left = _drive(FAMILY, seed_id, tmp_path / f"left-{seed_id}", "continue-only")
        right = _drive(FAMILY, seed_id, tmp_path / f"right-{seed_id}", "referee")
        try:
            left_truth = left.referee_turn_actions()
            right_truth = right.referee_turn_actions()
            left_obs = left.observations
            right_obs = right.observations
            for index in range(min(len(left_obs), len(right_obs))):
                same_bytes = (
                    left_obs[index].canonical_json()
                    == right_obs[index].canonical_json()
                )
                if not same_bytes:
                    continue
                if left_truth[index] == right_truth[index]:
                    continue
                # Paired case found: identical current observation bytes,
                # diverged sealed history, diverged correct action.
                lookup_left = left.event_class_lookup_action(left_obs[index])
                lookup_right = right.event_class_lookup_action(right_obs[index])
                assert lookup_left == lookup_right, (
                    "event-class lookup must be a function of the current "
                    "observation bytes only"
                )
                left_loss = left.referee_turn_loss_maps()[index][lookup_left]
                right_loss = right.referee_turn_loss_maps()[index][lookup_right]
                assert (
                    RECAST_LOSS_WEIGHTS[left_loss] > 0
                    or RECAST_LOSS_WEIGHTS[right_loss] > 0
                ), "event-class lookup discriminated the paired case"
                demonstrated = True
                break
        finally:
            left.cleanup()
            right.cleanup()
        if demonstrated:
            break
    assert demonstrated, (
        "no paired case with byte-identical observation and diverged sealed "
        "truth was found on development seeds"
    )


def test_resolutions_are_visible_in_later_observations(tmp_path: Path) -> None:
    """Sealed-state resolutions must be decidable from the visible history:
    a referee-following run emits resolution observations that a
    continue-only run never emits."""
    for seed_id in range(40):
        right = _drive(FAMILY, seed_id, tmp_path / f"vis-r-{seed_id}", "referee")
        left = _drive(FAMILY, seed_id, tmp_path / f"vis-l-{seed_id}", "continue-only")
        try:
            right_classes = {obs.event_class for obs in right.observations}
            left_classes = {obs.event_class for obs in left.observations}
            resolution_classes = {
                "EFFECT_VERIFIED",
                "STATE_REVIEWED",
                "ABSTENTION_RECORDED",
                "RECOVERY_APPLIED",
            }
            assert not left_classes & resolution_classes
            if right_classes & resolution_classes:
                return
        finally:
            right.cleanup()
            left.cleanup()
    raise AssertionError(
        "no development seed produced a visible resolution observation"
    )


def test_referee_is_not_exposed_in_observation_bytes(tmp_path: Path) -> None:
    """No observation byte stream exposes the referee, sealed state, losses,
    or family identity."""
    episode = InteractiveEpisode(FAMILY, 11, tmp_path / "sealed-bytes")
    try:
        episode.run()
        forbidden = (
            "referee",
            "correct_action",
            "loss_map",
            "sealed",
            FAMILY,
        )
        for observation in episode.observations:
            text = observation.canonical_json()
            for token in forbidden:
                assert token not in text, (
                    f"sealed token {token!r} leaked into observation bytes"
                )
    finally:
        episode.cleanup()


def test_default_policy_is_no_longer_experimental_truth(tmp_path: Path) -> None:
    """The event-class lookup disagrees with the sealed referee on at least
    one turn of some development episode, so it cannot serve as truth."""
    disagreement = False
    for seed_id in range(40):
        episode = _drive(FAMILY, seed_id, tmp_path / f"truth-{seed_id}", "continue-only")
        try:
            truth = episode.referee_turn_actions()
            for index, observation in enumerate(episode.observations):
                lookup = episode.event_class_lookup_action(observation)
                if lookup != truth[index]:
                    disagreement = True
                    break
        finally:
            episode.cleanup()
        if disagreement:
            break
    assert disagreement, "event-class lookup reproduced the sealed referee"
