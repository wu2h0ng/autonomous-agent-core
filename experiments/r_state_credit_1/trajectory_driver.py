"""Deterministic candidate trajectory driver for R-STATE-CREDIT-1 recast.

This module exercises the interactive environment and all four representations
with a local deterministic stub.  It has no provider transport, freeze, run
authority, scorer, verdict, or result writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from experiments.r_state_credit_1.action_grammar import ALL_ACTIONS, ActorAction
from experiments.r_state_credit_1.actor_interface import ActorRequest, ActorResponse, StubActor
from experiments.r_state_credit_1.arm_blinding import ArmBlinding
from experiments.r_state_credit_1.contracts import ArmId
from experiments.r_state_credit_1.episode_generator import EpisodeGenerator
from experiments.r_state_credit_1.interactive_env import EpisodeStatus, InteractiveEpisode
from experiments.r_state_credit_1.recast_arms import ArmRoster


class TrajectoryAuthority(str, Enum):
    """Claim ceiling for the local shared trajectory driver."""

    SHARED_QUALIFICATION_TRAJECTORY_ONLY = "SHARED_QUALIFICATION_TRAJECTORY_ONLY"


class CheckpointRecord:
    """Runner-internal truth record with no generic persistence protocol.

    This is intentionally not a dataclass and has no ``__dict__``.  Truth,
    actor responses, and resolved arm identities can only be consumed inside
    qualification code.  Persistence must cross the explicit projection
    boundary below.
    """

    __slots__ = (
        "checkpoint_ordinal",
        "turn_index",
        "correct_action",
        "authority",
        "requests",
        "responses",
        "resolved_actions",
    )

    def __init__(
        self,
        *,
        checkpoint_ordinal: int,
        turn_index: int,
        correct_action: ActorAction,
    ) -> None:
        self.checkpoint_ordinal = checkpoint_ordinal
        self.turn_index = turn_index
        self.correct_action = correct_action
        self.authority = TrajectoryAuthority.SHARED_QUALIFICATION_TRAJECTORY_ONLY
        self.requests: dict[str, ActorRequest] = {}
        self.responses: dict[str, ActorResponse] = {}
        self.resolved_actions: dict[ArmId, ActorAction] = {}

    @property
    def arm_ids(self) -> tuple[ArmId, ...]:
        return tuple(ArmId)

    def to_mapping(self) -> dict[str, object]:
        return QualificationCheckpointProjection.from_truth(self).to_mapping()


@dataclass(frozen=True, slots=True)
class QualificationCheckpointProjection:
    """Closed persistable projection; contains no referee or actor outputs."""

    authority: str
    checkpoint_ordinal: int
    turn_index: int
    request_count: int
    response_count: int

    @classmethod
    def from_truth(
        cls, record: CheckpointRecord
    ) -> QualificationCheckpointProjection:
        if type(record) is not CheckpointRecord:
            raise TypeError("record must be an exact CheckpointRecord")
        return cls(
            authority=record.authority.value,
            checkpoint_ordinal=record.checkpoint_ordinal,
            turn_index=record.turn_index,
            request_count=len(record.requests),
            response_count=len(record.responses),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "authority": self.authority,
            "checkpoint_ordinal": self.checkpoint_ordinal,
            "turn_index": self.turn_index,
            "request_count": self.request_count,
            "response_count": self.response_count,
        }


def run_checkpointed_episode(
    family_id: str,
    seed_id: int,
    temp_root: Path,
) -> tuple[InteractiveEpisode, list[CheckpointRecord]]:
    """Drive one deterministic development episode through all checkpoints."""

    episode = EpisodeGenerator(family_id, seed_id).generate(temp_root=temp_root)
    blinding = ArmBlinding(episode._episode_seed)
    roster = ArmRoster()
    actor = StubActor()
    records: list[CheckpointRecord] = []
    try:
        while episode.status is EpisodeStatus.RUNNING:
            observation = episode.observe()
            if episode._turn_index in episode.checkpoints:
                checkpoint_ordinal = episode.checkpoints.index(episode._turn_index)
                record = CheckpointRecord(
                    checkpoint_ordinal=checkpoint_ordinal,
                    turn_index=episode._turn_index,
                    correct_action=episode.referee_correct_action(),
                )
                calls = blinding.blinded_calls(
                    checkpoint_ordinal=checkpoint_ordinal,
                    observations=episode.observations[: episode._turn_index],
                    roster=roster,
                    valid_actions=ALL_ACTIONS,
                )
                for call in calls:
                    if call.request is None:
                        raise RuntimeError(
                            "development candidate budget unexpectedly forced an arm"
                        )
                    response = actor.act(call.request)
                    arm_id, _ = blinding.resolve_response(
                        checkpoint_ordinal, response, call.session_label
                    )
                    record.requests[call.session_label] = call.request
                    record.responses[call.session_label] = response
                    record.resolved_actions[arm_id] = response.action
                records.append(record)
            episode.step(episode._default_policy(observation, episode))
    except Exception:
        episode.cleanup()
        raise
    return episode, records
