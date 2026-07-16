"""P1-3 closure tests: real A0-A3 representation arms with per-arm budgets.

The four recast arms must produce distinct representation bytes from the same
released observation prefix, hold their own budget ledgers with fail-closed
overflow/ABSTAIN semantics, and remain free of arm identity or directive
hints.  Arm-specific overflow must never force any other arm.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.r_state_credit_1.action_grammar import ActorAction
from experiments.r_state_credit_1.actor_interface import StubActor
from experiments.r_state_credit_1.arm_blinding import ArmBlinding
from experiments.r_state_credit_1.contracts import ArmId
from experiments.r_state_credit_1.interactive_env import (
    EpisodeStatus,
    InteractiveEpisode,
)
from experiments.r_state_credit_1.recast_arms import (
    FORCED_OVERFLOW_REASON,
    ArmRoster,
)


FAMILY = "TEST_FAMILY"

_FORBIDDEN_SUBSTRINGS = (
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
_DIRECTIVE_HINTS = (
    "recovery_directive",
    "action_hint",
    "recommended_action",
    "policy",
)


def _run(family_id: str, seed_id: int, temp_root: Path) -> InteractiveEpisode:
    episode = InteractiveEpisode(family_id, seed_id, temp_root)
    try:
        episode.run()
    except Exception:
        episode.cleanup()
        raise
    return episode


def test_four_arms_render_distinct_parseable_representations(
    tmp_path: Path,
) -> None:
    """At every checkpoint the four arms produce pairwise distinct JSON
    representations that all carry the same latest observation."""
    episode = _run(FAMILY, 42, tmp_path / "distinct")
    try:
        roster = ArmRoster()
        for turn in episode.checkpoints:
            prefix = tuple(episode.observations[:turn])
            outcomes = {
                arm_id: roster.representation(arm_id, prefix)
                for arm_id in ArmId
            }
            payloads = [outcome.representation for outcome in outcomes.values()]
            assert len(set(payloads)) == 4, (
                f"arm representations are not pairwise distinct at turn {turn}"
            )
            latest = json.loads(prefix[-1].canonical_json())
            for arm_id, outcome in outcomes.items():
                assert outcome.forced_action is None
                data = json.loads(outcome.representation)
                assert data["latest"] == latest, (
                    f"{arm_id.value} does not carry the latest observation"
                )
                assert "context" in data
    finally:
        episode.cleanup()


def test_a0_is_full_bounded_raw_log(tmp_path: Path) -> None:
    """A0 contains every released observation, in order, untruncated."""
    episode = _run(FAMILY, 7, tmp_path / "a0")
    try:
        roster = ArmRoster()
        turn = episode.checkpoints[-1]
        prefix = tuple(episode.observations[:turn])
        outcome = roster.representation(ArmId.A0_FULL_LOG, prefix)
        data = json.loads(outcome.representation)
        entries = data["context"]["entries"]
        assert len(entries) == len(prefix)
        expected = [json.loads(obs.canonical_json()) for obs in prefix]
        assert entries == expected
    finally:
        episode.cleanup()


def test_a1_rolling_summary_is_deterministic_and_lossy(tmp_path: Path) -> None:
    """A1 compacts old events (payload content lost) but keeps counts,
    deterministically."""
    episode = _run(FAMILY, 9, tmp_path / "a1")
    try:
        turn = episode.checkpoints[-1]
        prefix = tuple(episode.observations[:turn])
        first = ArmRoster().representation(ArmId.A1_ROLLING_SUMMARY, prefix)
        second = ArmRoster().representation(ArmId.A1_ROLLING_SUMMARY, prefix)
        assert first.representation == second.representation

        data = json.loads(first.representation)
        context = data["context"]
        assert context["compacted"]["count"] > 0, "summary never compacts"
        total = sum(context["class_counts"].values())
        assert total == len(prefix)

        # Lossy: an early observation's payload bytes are present in A0 but
        # absent from the compacted summary.
        early = prefix[0].canonical_json()
        a0 = ArmRoster().representation(ArmId.A0_FULL_LOG, prefix)
        assert json.loads(early) in json.loads(a0.representation)["context"][
            "entries"
        ]
        assert early not in first.representation
        assert len(first.representation) < len(a0.representation)
    finally:
        episode.cleanup()


def test_a2_bounded_retrieval_applies_frozen_relevance_rule(
    tmp_path: Path,
) -> None:
    """A2 selects only decision-relevant (non-routine) observations, most
    recent first, within its frozen bound, and reports omissions."""
    episode = _run(FAMILY, 11, tmp_path / "a2")
    try:
        roster = ArmRoster()
        turn = episode.checkpoints[-1]
        prefix = tuple(episode.observations[:turn])
        outcome = roster.representation(ArmId.A2_FROZEN_RETRIEVAL, prefix)
        data = json.loads(outcome.representation)
        context = data["context"]
        assert context["rule"] == "nonroutine-recency-v1"
        relevant = [
            json.loads(obs.canonical_json())
            for obs in prefix
            if obs.event_class != "ENTITY_OBSERVED"
        ]
        expected = relevant[-12:]
        assert context["selected"] == expected
        assert context["omitted"] == len(prefix) - len(expected)
        assert context["omitted"] > 0
    finally:
        episode.cleanup()


def test_a3_typed_state_tracks_commitments_conflicts_and_resolutions(
    tmp_path: Path,
) -> None:
    """A3 compiles typed state from the visible feed: it must expose an
    unverified effect after a dispatch-class event and flip it to verified
    after the visible EFFECT_VERIFIED resolution."""
    verified_case = False
    for seed_id in range(60):
        episode = InteractiveEpisode(FAMILY, seed_id, tmp_path / f"a3-{seed_id}")
        try:
            while episode.status is EpisodeStatus.RUNNING:
                episode.observe()
                episode.step(episode.referee_correct_action())
            observations = episode.observations
            classes = [obs.event_class for obs in observations]
            if "EFFECT_VERIFIED" not in classes:
                continue
            dispatch_index = next(
                index
                for index, name in enumerate(classes)
                if name
                in {
                    "ACTION_DISPATCH",
                    "RECEIPT_LOSS",
                    "INTERRUPTION_BEFORE_EFFECT_VERIFICATION",
                }
            )
            verified_index = classes.index("EFFECT_VERIFIED")
            roster = ArmRoster()
            before = json.loads(
                roster.representation(
                    ArmId.A3_TYPED_STATE,
                    tuple(observations[: dispatch_index + 1]),
                ).representation
            )["context"]
            after = json.loads(
                ArmRoster()
                .representation(
                    ArmId.A3_TYPED_STATE,
                    tuple(observations[: verified_index + 1]),
                )
                .representation
            )["context"]
            unverified_before = [
                effect
                for effect in before["effects"]
                if effect["status"] != "verified"
            ]
            assert unverified_before, "dispatch did not appear in typed state"
            verified_after = [
                effect
                for effect in after["effects"]
                if effect["status"] == "verified"
            ]
            assert verified_after, "resolution did not flip effect status"
            verified_case = True
        finally:
            episode.cleanup()
        if verified_case:
            break
    assert verified_case, "no development seed exercised the effect cycle"


def test_per_arm_ledgers_are_independent(tmp_path: Path) -> None:
    """Each arm holds its own budget ledger; no shared A0 byte count."""
    episode = _run(FAMILY, 13, tmp_path / "ledger")
    try:
        roster = ArmRoster()
        for turn in episode.checkpoints:
            prefix = tuple(episode.observations[:turn])
            for arm_id in ArmId:
                roster.representation(arm_id, prefix)
        ledgers = {arm_id: roster.ledger(arm_id) for arm_id in ArmId}
        charged = {arm_id: ledgers[arm_id].charged_bytes for arm_id in ArmId}
        assert len(set(charged.values())) >= 3, (
            "arm ledgers do not account independently"
        )
        assert all(ledger.requests == 4 for ledger in ledgers.values())
        assert not any(ledger.overflowed for ledger in ledgers.values())
    finally:
        episode.cleanup()


def test_arm_specific_overflow_cannot_force_other_arms(tmp_path: Path) -> None:
    """A0 overflow forces only A0; a non-A0 overflow forces only that arm."""
    episode = _run(FAMILY, 7, tmp_path / "overflow")
    try:
        turn = episode.checkpoints[0]
        prefix = tuple(episode.observations[:turn])

        a0_only = ArmRoster(b_a0=64, b_arm=1_000_000)
        outcomes = {
            arm_id: a0_only.representation(arm_id, prefix) for arm_id in ArmId
        }
        assert outcomes[ArmId.A0_FULL_LOG].forced_action is ActorAction.ABSTAIN
        assert outcomes[ArmId.A0_FULL_LOG].forced_reason == (
            FORCED_OVERFLOW_REASON
        )
        for arm_id in (
            ArmId.A1_ROLLING_SUMMARY,
            ArmId.A2_FROZEN_RETRIEVAL,
            ArmId.A3_TYPED_STATE,
        ):
            assert outcomes[arm_id].forced_action is None, (
                f"A0 overflow forced {arm_id.value}"
            )

        a1_only = ArmRoster(b_a0=1_000_000, b_arm=64)
        outcomes = {
            arm_id: a1_only.representation(arm_id, prefix) for arm_id in ArmId
        }
        assert outcomes[ArmId.A0_FULL_LOG].forced_action is None
        for arm_id in (
            ArmId.A1_ROLLING_SUMMARY,
            ArmId.A2_FROZEN_RETRIEVAL,
            ArmId.A3_TYPED_STATE,
        ):
            assert outcomes[arm_id].forced_action is ActorAction.ABSTAIN
            assert outcomes[arm_id].forced_reason == FORCED_OVERFLOW_REASON
    finally:
        episode.cleanup()


def test_overflow_is_sticky_for_remaining_checkpoints(tmp_path: Path) -> None:
    """Once an arm overflows it stays forced to ABSTAIN afterward."""
    episode = _run(FAMILY, 7, tmp_path / "sticky")
    try:
        roster = ArmRoster(b_a0=64, b_arm=1_000_000)
        for turn in episode.checkpoints:
            prefix = tuple(episode.observations[:turn])
            outcome = roster.representation(ArmId.A0_FULL_LOG, prefix)
            assert outcome.forced_action is ActorAction.ABSTAIN
            assert outcome.forced_reason == FORCED_OVERFLOW_REASON
        assert roster.ledger(ArmId.A0_FULL_LOG).overflowed
    finally:
        episode.cleanup()


def test_blinded_calls_deliver_arm_specific_bytes_with_custody(
    tmp_path: Path,
) -> None:
    """Blinded calls carry neutral labels only, deliver the arm-specific
    representation at each position, and the reverse map stays runner-only."""
    episode = _run(FAMILY, 21, tmp_path / "custody")
    try:
        blinding = ArmBlinding(episode._episode_seed)
        roster = ArmRoster()
        actor = StubActor()
        for checkpoint_ordinal, turn in enumerate(episode.checkpoints):
            prefix = tuple(episode.observations[:turn])
            calls = blinding.blinded_calls(
                checkpoint_ordinal=checkpoint_ordinal,
                observations=prefix,
                roster=roster,
                valid_actions=tuple(ActorAction),
            )
            assert len(calls) == 4
            order = blinding.call_order(checkpoint_ordinal)
            for position, call in enumerate(calls):
                assert call.request is not None
                assert call.forced_action is None
                assert call.request.session_label == (
                    blinding.label_for_position(position)
                )
                expected_arm = order[position]
                expected = roster.peek_representation(expected_arm, prefix)
                assert call.request.representation == expected
                response = actor.act(call.request)
                resolved, _ = blinding.resolve_response(
                    checkpoint_ordinal, response, call.request.session_label
                )
                assert resolved == expected_arm
                text = call.request.to_canonical_json()
                for token in _FORBIDDEN_SUBSTRINGS:
                    assert token not in text, (
                        f"forbidden substring {token!r} in blinded request"
                    )
                for hint in _DIRECTIVE_HINTS:
                    assert hint not in text, (
                        f"directive hint {hint!r} in blinded request"
                    )
    finally:
        episode.cleanup()


def test_stub_actor_is_event_class_lookup_over_any_arm_bytes(
    tmp_path: Path,
) -> None:
    """The qualification StubActor answers from the shared latest event
    class, so all four distinct representations get the same lookup answer;
    the arms are distinct inputs, not distinct policies."""
    episode = _run(FAMILY, 5, tmp_path / "stub")
    try:
        roster = ArmRoster()
        blinding = ArmBlinding(episode._episode_seed)
        actor = StubActor()
        for checkpoint_ordinal, turn in enumerate(episode.checkpoints):
            prefix = tuple(episode.observations[:turn])
            calls = blinding.blinded_calls(
                checkpoint_ordinal=checkpoint_ordinal,
                observations=prefix,
                roster=roster,
            )
            actions = set()
            payloads = set()
            for call in calls:
                assert call.request is not None
                payloads.add(call.request.representation)
                actions.add(actor.act(call.request).action)
            assert len(payloads) == 4
            assert len(actions) == 1, (
                "event-class lookup must not depend on the arm identity"
            )
            lookup = episode.event_class_lookup_action(prefix[-1])
            assert actions == {lookup}
    finally:
        episode.cleanup()
