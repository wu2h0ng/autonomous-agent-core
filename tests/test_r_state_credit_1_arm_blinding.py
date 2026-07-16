"""Qualification tests for R-STATE-CREDIT-1 Phase 2 arm blinding and balancing."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from experiments.r_state_credit_1.action_grammar import ActorAction
from experiments.r_state_credit_1.actor_interface import StubActor
from experiments.r_state_credit_1.arm_blinding import ArmBlinding, NEUTRAL_LABELS
from experiments.r_state_credit_1.contracts import ArmId, ScenarioFamily
from experiments.r_state_credit_1.interactive_env import InteractiveEpisode
from experiments.r_state_credit_1.recast_arms import ArmRoster


FAMILY = "TEST_FAMILY"
FORBIDDEN_SUBSTRINGS = (
    "A0",
    "A1",
    "A2",
    "A3",
    "full-log",
    "compressed",
    "typed-state",
    "full log",
    "rolling summary",
    "retrieval",
    "typed state",
)

# Chi-square critical values at p = 0.01.
_CHISQ_3_DF = 11.3449
_CHISQ_18_DF = 34.805


def _run_episode(
    family_id: str, seed_id: int, temp_root: Path
) -> InteractiveEpisode:
    """Helper: create, run, and return an episode."""
    episode = InteractiveEpisode(family_id, seed_id, temp_root)
    try:
        episode.run()
    except Exception:
        episode.cleanup()
        raise
    return episode


def _actor_request_bytes(
    episode: InteractiveEpisode, blinding: ArmBlinding
) -> bytes:
    """Serialize every blinded ActorRequest for the first checkpoint."""
    checkpoint_ordinal = 0
    turn_index = episode.checkpoints[checkpoint_ordinal]
    observations = episode.observations[:turn_index]
    calls = blinding.blinded_calls(
        checkpoint_ordinal=checkpoint_ordinal,
        observations=observations,
        roster=ArmRoster(),
        valid_actions=tuple(ActorAction),
    )
    rendered = "\n".join(
        call.request.to_canonical_json()
        for call in calls
        if call.request is not None
    )
    return rendered.encode("utf-8")


def test_byte_level_no_arm_identity(tmp_path: Path) -> None:
    """Serialized ActorRequest bytes contain no real arm identity or role hints."""
    episode = _run_episode(FAMILY, 42, tmp_path / "byte-level")
    try:
        blinding = ArmBlinding(episode._episode_seed)
        payload = _actor_request_bytes(episode, blinding)
        text = payload.decode("utf-8")
        for substring in FORBIDDEN_SUBSTRINGS:
            assert substring not in text, (
                f"forbidden substring {substring!r} found in actor request bytes"
            )
    finally:
        episode.cleanup()


def test_byte_level_no_turn_index_metadata(tmp_path: Path) -> None:
    """Serialized ActorRequest bytes contain no turn-index leakage."""
    episode = _run_episode(FAMILY, 42, tmp_path / "no-turn-index")
    try:
        blinding = ArmBlinding(episode._episode_seed)
        payload = _actor_request_bytes(episode, blinding)
        text = payload.decode("utf-8")
        assert "turn_index" not in text, "turn_index leaked into actor request bytes"
        assert "observed_at_turn" not in text, (
            "observed_at_turn leaked into actor request bytes"
        )
    finally:
        episode.cleanup()


def test_call_order_chi_square_uniform(tmp_path: Path) -> None:
    """Arm call order per position is uniform across 400 episodes."""
    counts_per_position: list[Counter[str]] = [Counter() for _ in range(4)]
    for seed_id in range(400):
        episode = InteractiveEpisode(
            FAMILY, seed_id, tmp_path / f"chi-{seed_id}"
        )
        try:
            blinding = ArmBlinding(episode._episode_seed)
            order = blinding.call_order(checkpoint_ordinal=0)
            for position, arm_id in enumerate(order):
                counts_per_position[position][arm_id.value] += 1
        finally:
            episode.cleanup()

    expected = 100  # 400 episodes / 4 arms
    for position, counts in enumerate(counts_per_position):
        chi_sq = sum(
            (counts.get(arm_id.value, 0) - expected) ** 2 / expected
            for arm_id in ArmId
        )
        assert chi_sq <= _CHISQ_3_DF, (
            f"position {position} call order non-uniform: chi²={chi_sq:.4f}"
        )


def test_call_order_independent_of_family_seed(tmp_path: Path) -> None:
    """Family/seed cannot predict which arm is called first."""
    families = list(ScenarioFamily)
    first_arm_counts: dict[str, Counter[str]] = {
        family.value: Counter() for family in families
    }
    total_per_family = 400 // len(families)

    for family_index, family in enumerate(families):
        for seed_offset in range(total_per_family):
            seed_id = family_index * 1000 + seed_offset
            episode = InteractiveEpisode(
                family.value,
                seed_id,
                tmp_path / f"ind-{family.value}-{seed_id}",
            )
            try:
                blinding = ArmBlinding(episode._episode_seed)
                first_arm = blinding.call_order(checkpoint_ordinal=0)[0]
                first_arm_counts[family.value][first_arm.value] += 1
            finally:
                episode.cleanup()

    # Chi-square test of independence on family × first_arm table.
    rows = list(first_arm_counts.values())
    row_totals = [sum(row.values()) for row in rows]
    col_totals: Counter[str] = Counter()
    for row in rows:
        col_totals.update(row)
    grand_total = sum(row_totals)

    chi_sq = 0.0
    for row, row_total in zip(rows, row_totals):
        for arm_id in ArmId:
            observed = row.get(arm_id.value, 0)
            expected = row_total * col_totals[arm_id.value] / grand_total
            if expected > 0:
                chi_sq += (observed - expected) ** 2 / expected

    assert chi_sq <= _CHISQ_18_DF, (
        f"family/seed predicts first arm: chi²={chi_sq:.4f}"
    )


def test_neutral_labels_only(tmp_path: Path) -> None:
    """Every ActorRequest uses only neutral labels from the frozen set."""
    for seed_id in range(20):
        episode = InteractiveEpisode(
            FAMILY, seed_id, tmp_path / f"labels-{seed_id}"
        )
        try:
            episode.run()
            blinding = ArmBlinding(episode._episode_seed)
            roster = ArmRoster()
            for checkpoint_ordinal in range(len(episode.checkpoints)):
                turn_index = episode.checkpoints[checkpoint_ordinal]
                observations = episode.observations[:turn_index]
                calls = blinding.blinded_calls(
                    checkpoint_ordinal=checkpoint_ordinal,
                    observations=observations,
                    roster=roster,
                    valid_actions=tuple(ActorAction),
                )
                for call in calls:
                    assert call.session_label in NEUTRAL_LABELS, (
                        f"non-neutral label {call.session_label!r}"
                    )
                    assert call.request is not None
                    assert call.request.session_label == call.session_label
        finally:
            episode.cleanup()


def test_reverse_mapping_runner_only(tmp_path: Path) -> None:
    """Actor responses are mapped back to real arm_id only by the runner."""
    episode = _run_episode(FAMILY, 99, tmp_path / "reverse")
    try:
        blinding = ArmBlinding(episode._episode_seed)
        roster = ArmRoster()
        actor = StubActor()
        for checkpoint_ordinal in range(len(episode.checkpoints)):
            turn_index = episode.checkpoints[checkpoint_ordinal]
            observations = episode.observations[:turn_index]
            order = blinding.call_order(checkpoint_ordinal)
            calls = blinding.blinded_calls(
                checkpoint_ordinal=checkpoint_ordinal,
                observations=observations,
                roster=roster,
                valid_actions=tuple(ActorAction),
            )
            for position, expected_arm in enumerate(order):
                call = calls[position]
                assert call.request is not None
                response = actor.act(call.request)
                resolved_arm, _ = blinding.resolve_response(
                    checkpoint_ordinal, response, call.session_label
                )
                assert resolved_arm == expected_arm, (
                    f"checkpoint {checkpoint_ordinal} position {position}: "
                    f"expected {expected_arm.value}, got {resolved_arm.value}"
                )
    finally:
        episode.cleanup()
