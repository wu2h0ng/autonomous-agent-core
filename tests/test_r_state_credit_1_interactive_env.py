"""Tests for the interactive R-STATE-CREDIT-1 Phase 1 environment."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from experiments.r_state_credit_1.contracts import ProbeAction
from experiments.r_state_credit_1.episode_generator import EpisodeGenerator
from experiments.r_state_credit_1.interactive_env import (
    B_A0,
    B_ARM,
    O_MAX,
    InteractiveEpisode,
    PerturbationClass,
)


FAMILY = "TEST_FAMILY"


def _run_episode(family_id: str, seed_id: int, temp_root: Path | None = None) -> InteractiveEpisode:
    """Helper: create, run, and return an episode."""
    episode = InteractiveEpisode(family_id, seed_id, temp_root)
    try:
        episode.run()
    except Exception:
        episode.cleanup()
        raise
    return episode


def _event_signature(episode: InteractiveEpisode) -> tuple[tuple[str, int], ...]:
    """Canonical event-class sequence for reversibility checks."""
    return tuple((event.event_class, event.turn_index) for event in episode.events)


def test_reversibility(tmp_path: Path) -> None:
    """Same seed must produce an identical event sequence."""
    first = _run_episode(FAMILY, 42, tmp_path / "first")
    second = _run_episode(FAMILY, 42, tmp_path / "second")
    try:
        assert first.T == second.T
        assert first.checkpoints == second.checkpoints
        assert _event_signature(first) == _event_signature(second)
        assert first._state_digest() == second._state_digest()
    finally:
        first.cleanup()
        second.cleanup()


def test_distinct_seeds(tmp_path: Path) -> None:
    """Twenty seeds of the same family must be structurally distinct."""
    event_signatures: set[tuple[tuple[str, int], ...]] = set()
    structural_signatures: set[tuple[Any, ...]] = set()
    topologies: set[str] = set()
    episodes: list[InteractiveEpisode] = []
    try:
        for seed_id in range(20):
            episode = _run_episode(FAMILY, seed_id, tmp_path / f"seed-{seed_id}")
            episodes.append(episode)
            event_signatures.add(_event_signature(episode))
            signature = EpisodeGenerator(FAMILY, seed_id).structural_signature()
            topologies.add(str(signature["alias_topology"]))
            structural_signatures.add(
                (
                    signature["perturbation_schedule"],
                    signature["checkpoint_positions"],
                    signature["T"],
                    signature["entity_count"],
                    signature["alias_topology"],
                )
            )
        assert len(event_signatures) == 20, "event sequences clustered across seeds"
        assert len(structural_signatures) == 20, "structural signatures clustered"
        assert len(topologies) >= 2, "alias topology did not vary"
    finally:
        for episode in episodes:
            episode.cleanup()


def test_no_overflow_on_development_seeds(tmp_path: Path) -> None:
    """One thousand generated episodes must stay within frozen budgets."""
    for seed_id in range(1000):
        episode = InteractiveEpisode(FAMILY, seed_id, tmp_path / f"dev-{seed_id}")
        try:
            episode.run()
            assert not episode.a0_overflow
            assert not episode.arm_overflow
            assert episode.status.value in {"TERMINAL", "ABSTAINED"}
            for observation in episode.observations:
                assert observation.serialized_bytes() <= O_MAX
            assert episode._cumulative_a0_bytes() <= B_A0
            assert episode._cumulative_a0_bytes() <= B_ARM
        finally:
            episode.cleanup()


def test_budget_overflow_fail_closed(tmp_path: Path) -> None:
    """Artificially small budgets force ABSTAIN / overflow semantics."""
    episode = InteractiveEpisode(
        FAMILY,
        7,
        tmp_path / "overflow",
        b_a0=256,
        b_arm=128,
    )
    try:
        _observations, events = episode.run()
        assert episode.a0_overflow or episode.arm_overflow
        # Once overflow occurs the actor is forced to ABSTAIN.
        assert any(
            event.payload.get("action") == ProbeAction.ABSTAIN.value
            for event in events
        )
    finally:
        episode.cleanup()


def test_four_checkpoints(tmp_path: Path) -> None:
    """Every episode has exactly four checkpoints with minimum spacing."""
    for seed_id in range(50):
        episode = InteractiveEpisode(FAMILY, seed_id, tmp_path / f"ckpt-{seed_id}")
        try:
            assert len(episode.checkpoints) == 4
            positions = episode.checkpoints
            for turn in positions:
                assert 5 <= turn <= episode.T - 2
            for left, right in zip(positions, positions[1:]):
                assert right - left >= 3
        finally:
            episode.cleanup()


def test_checkpoint_algorithm_matches_amendment(tmp_path: Path) -> None:
    """``_select_checkpoint_turns`` matches the amended pseudo-algorithm."""
    import hashlib
    import itertools

    def _reference_checkpoints(
        episode_seed: bytes, eligible_terminal_turns: list[int], t: int
    ) -> list[int]:
        eligible = sorted(
            {turn for turn in eligible_terminal_turns if 5 <= turn <= t - 2}
        )
        if len(eligible) < 4:
            raise RuntimeError("insufficient terminal phases")
        valid = [
            combo
            for combo in itertools.combinations(eligible, 4)
            if all(right - left >= 3 for left, right in zip(combo, combo[1:]))
        ]
        if not valid:
            raise RuntimeError("cannot space four checkpoints")
        digest = hashlib.sha256(b"checkpoint-v1\x00" + episode_seed).digest()
        rng = random.Random(digest)
        return list(valid[rng.randrange(len(valid))])

    for seed_id in range(50):
        episode = InteractiveEpisode(FAMILY, seed_id, tmp_path / f"algo-{seed_id}")
        try:
            eligible = sorted(
                {terminal for _, _, terminal in episode._perturbation_schedule}
            )
            expected = _reference_checkpoints(
                episode._episode_seed, eligible, episode.T
            )
            assert episode.checkpoints == expected
        finally:
            episode.cleanup()


def test_temporary_directory_isolation(tmp_path: Path) -> None:
    """Episode materializes in temp dir and leaves no residual files."""
    provided = tmp_path / "provided-root"
    provided.mkdir()
    episode = InteractiveEpisode(FAMILY, 99, provided)
    try:
        episode.run()
        assert provided.exists()
        assert any(provided.rglob("*"))
    finally:
        episode.cleanup()
    assert not provided.exists()

    # Context manager path: episode creates and removes its own temp dir.
    with InteractiveEpisode(FAMILY, 99) as episode:
        episode.run()
        root = episode.temp_root
        assert root.exists()
    assert not root.exists()


def test_generator_interface() -> None:
    """EpisodeGenerator exposes deterministic schedules and signatures."""
    gen = EpisodeGenerator(FAMILY, 5)
    schedule = gen.perturbation_schedule()
    assert len(schedule) >= 6
    assert all(isinstance(turn, int) for turn, _, _ in schedule)
    assert all(isinstance(cls, str) and cls for _, cls, _ in schedule)
    checkpoints = gen.checkpoint_turns()
    assert len(checkpoints) == 4
    sig = gen.structural_signature()
    assert sig["entity_count"] >= 2
    assert sig["T"] >= 20 and sig["T"] <= 60


def test_observation_budget_envelope_per_turn(tmp_path: Path) -> None:
    """Every released observation is within the per-turn byte cap."""
    episode = InteractiveEpisode(FAMILY, 123, tmp_path / "envelope")
    try:
        episode.run()
        for observation in episode.observations:
            assert observation.serialized_bytes() <= O_MAX
    finally:
        episode.cleanup()


def test_a0_overflow_does_not_force_other_arms(tmp_path: Path) -> None:
    """A0 budget overflow forces only A0 to ABSTAIN; the episode continues."""
    episode = InteractiveEpisode(
        FAMILY,
        7,
        tmp_path / "a0-only-overflow",
        b_a0=256,
        b_arm=999_999,
    )
    try:
        observations, events = episode.run()
        assert episode.a0_overflow
        assert not episode.arm_overflow
        # The episode reached a normal terminal rather than stopping on ABSTAIN.
        assert episode.status.value == "TERMINAL"
        # No overflow-forced ABSTAIN was applied to the shared step action.
        assert not any(
            event.payload.get("action") == ProbeAction.ABSTAIN.value
            and event.payload.get("action_reason") == "REPRESENTATION_BUDGET_OVERFLOW"
            for event in events
        )
        # Other arms would have continued to see checkpoints.
        assert len(episode.checkpoints) == 4
        assert len(observations) == episode.T
    finally:
        episode.cleanup()


def test_temp_tree_contains_no_family_seed_metadata(tmp_path: Path) -> None:
    """The materialized temp directory contains no family or seed identifiers."""
    episode = InteractiveEpisode(FAMILY, 7, tmp_path / "metadata-audit")
    try:
        episode.run()
        for path in episode.temp_root.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                assert episode.family_id not in text, (
                    f"family_id leaked into {path.relative_to(episode.temp_root)}"
                )
                assert str(episode.seed_id) not in text, (
                    f"seed_id leaked into {path.relative_to(episode.temp_root)}"
                )
    finally:
        episode.cleanup()


def test_all_frozen_perturbation_classes_observable(tmp_path: Path) -> None:
    """Every frozen perturbation class is schedulable and observable."""
    scheduled_union: set[PerturbationClass] = set()
    for seed_id in range(120):
        episode = InteractiveEpisode(FAMILY, seed_id, tmp_path / f"allcls-{seed_id}")
        try:
            observations, _events = episode.run()
            scheduled_union.update(
                cls for _, cls, _ in episode._perturbation_schedule
            )
            observed_classes = {obs.event_class for obs in observations}
            last_turn = observations[-1].turn_index
            for trigger, cls, _terminal in episode._perturbation_schedule:
                if trigger <= last_turn:
                    assert cls.value in observed_classes, (
                        f"seed {seed_id}: {cls.value} scheduled at turn "
                        f"{trigger} was not observed"
                    )
        finally:
            episode.cleanup()
    missing = sorted(cls.value for cls in set(PerturbationClass) - scheduled_union)
    assert scheduled_union == set(PerturbationClass), (
        f"perturbation classes never scheduled across 120 seeds: {missing}"
    )
