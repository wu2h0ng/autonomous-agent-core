"""Arm identity blinding and call-order balancing for R-STATE-CREDIT-1 Phase 2.

For every checkpoint, real arm identities are replaced with neutral labels and
the call order is a uniform random permutation derived from the episode seed.
The reverse mapping is runner-only.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Iterable

from experiments.r_state_credit_1.action_grammar import ActorAction
from experiments.r_state_credit_1.actor_interface import ActorRequest, ActorResponse
from experiments.r_state_credit_1.contracts import ArmId
from experiments.r_state_credit_1.observation import Observation


NEUTRAL_LABELS: tuple[str, ...] = ("arm-a", "arm-b", "arm-c", "arm-d")
_REAL_ARM_IDS: tuple[ArmId, ...] = tuple(ArmId)


@dataclass(frozen=True, slots=True)
class ArmBlinding:
    """Blinding state for one episode.

    Parameters
    ----------
    episode_seed:
        32-byte deterministic episode seed (for example from
        ``InteractiveEpisode._episode_seed``).
    """

    episode_seed: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.episode_seed, bytes) or len(self.episode_seed) != 32:
            raise ValueError("episode_seed must be 32 bytes")

    @property
    def real_arm_ids(self) -> tuple[ArmId, ...]:
        """Real arm identities in canonical order."""
        return _REAL_ARM_IDS

    @property
    def neutral_labels(self) -> tuple[str, ...]:
        """Frozen neutral label set."""
        return NEUTRAL_LABELS

    def call_order(self, checkpoint_ordinal: int) -> tuple[ArmId, ...]:
        """Return the randomized call order for ``checkpoint_ordinal``.

        The order is a uniform random permutation of the four real arm IDs.
        It is deterministic given ``episode_seed`` and ``checkpoint_ordinal``,
        and independent of family, seed, or arm capability by construction.
        """
        if (
            not isinstance(checkpoint_ordinal, int)
            or isinstance(checkpoint_ordinal, bool)
            or checkpoint_ordinal < 0
        ):
            raise ValueError("checkpoint_ordinal must be a non-negative integer")
        seed = hashlib.sha256(
            b"arm-order-v1\x00"
            + self.episode_seed
            + checkpoint_ordinal.to_bytes(4, "big")
        ).digest()
        rng = random.Random(seed)
        order = list(_REAL_ARM_IDS)
        rng.shuffle(order)
        return tuple(order)

    def arm_at_position(self, checkpoint_ordinal: int, position: int) -> ArmId:
        """Return the real arm ID called at ``position``."""
        order = self.call_order(checkpoint_ordinal)
        if not 0 <= position < len(order):
            raise ValueError("position out of range")
        return order[position]

    def label_for_position(self, position: int) -> str:
        """Return the neutral label for ``position``."""
        if not 0 <= position < len(NEUTRAL_LABELS):
            raise ValueError("position out of range")
        return NEUTRAL_LABELS[position]

    def position_for_label(self, label: str) -> int:
        """Return the call position associated with ``label``."""
        try:
            return NEUTRAL_LABELS.index(label)
        except ValueError as exc:
            raise ValueError(f"unknown neutral label: {label}") from exc

    def arm_for_label(self, checkpoint_ordinal: int, label: str) -> ArmId:
        """Runner-only reverse mapping from neutral label to real arm ID."""
        position = self.position_for_label(label)
        return self.arm_at_position(checkpoint_ordinal, position)

    def actor_request(
        self,
        checkpoint_ordinal: int,
        position: int,
        observations: Iterable[Observation],
        valid_actions: Iterable[ActorAction] | None = None,
    ) -> ActorRequest:
        """Build a blinded actor request for the arm at ``position``.

        The returned request contains only a neutral session label; no real
        arm identity, role name, turn index, checkpoint ordinal, or capability
        hint is present.
        """
        return ActorRequest(
            observations=tuple(observations),
            valid_actions=(
                tuple(valid_actions)
                if valid_actions is not None
                else tuple(ActorAction)
            ),
            session_label=self.label_for_position(position),
        )

    def resolve_response(
        self,
        checkpoint_ordinal: int,
        response: ActorResponse,
        session_label: str,
    ) -> tuple[ArmId, ActorResponse]:
        """Map a blinded response back to the real arm ID.

        The runner uses this method; the actor never sees the reverse mapping.
        """
        arm_id = self.arm_for_label(checkpoint_ordinal, session_label)
        return arm_id, response
