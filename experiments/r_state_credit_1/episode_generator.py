"""Deterministic episode generator for R-STATE-CREDIT-1 Phase 1.

A generator is seeded by ``family_id`` + ``seed_id`` and produces an
:mod:`experiments.r_state_credit_1.interactive_env.InteractiveEpisode` whose
perturbation schedule, checkpoint positions, and alias topology are
seed-dependent and structurally distinct from other seeds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiments.r_state_credit_1.interactive_env import (
    B_A0,
    B_ARM,
    O_MAX,
    InteractiveEpisode,
)


class EpisodeGenerator:
    """Deterministic generator for interactive R-STATE-CREDIT-1 episodes.

    Parameters
    ----------
    family_id:
        Family identifier.  May be any non-empty string; the canonical research
        families live in ``contracts.ScenarioFamily``.
    seed_id:
        Non-negative integer seed.
    """

    def __init__(self, family_id: str, seed_id: int) -> None:
        if not isinstance(family_id, str) or not family_id:
            raise ValueError("family_id must be non-empty text")
        if not isinstance(seed_id, int) or isinstance(seed_id, bool) or seed_id < 0:
            raise ValueError("seed_id must be a non-negative integer")
        self.family_id = family_id
        self.seed_id = seed_id

    def generate(
        self,
        temp_root: Path | None = None,
        *,
        o_max: int = O_MAX,
        b_a0: int = B_A0,
        b_arm: int = B_ARM,
    ) -> InteractiveEpisode:
        """Generate and return a configured interactive episode."""
        return InteractiveEpisode(
            family_id=self.family_id,
            seed_id=self.seed_id,
            temp_root=temp_root,
            o_max=o_max,
            b_a0=b_a0,
            b_arm=b_arm,
        )

    def perturbation_schedule(self) -> list[tuple[int, str, int]]:
        """Return the deterministic perturbation schedule for this seed.

        The schedule is a list of ``(trigger_turn, perturbation_class, terminal_turn)``
        tuples sorted by trigger turn.
        """
        episode = self.generate()
        try:
            return [
                (turn, cls.value, terminal)
                for turn, cls, terminal in episode._perturbation_schedule
            ]
        finally:
            episode.cleanup()

    def checkpoint_turns(self) -> list[int]:
        """Return the deterministic checkpoint turns for this seed."""
        episode = self.generate()
        try:
            return list(episode.checkpoints)
        finally:
            episode.cleanup()

    def structural_signature(self) -> dict[str, Any]:
        """Return a seed-specific structural signature for independence checks."""
        episode = self.generate()
        try:
            return {
                "alias_topology": self._alias_topology(episode),
                "checkpoint_positions": tuple(episode.checkpoints),
                "entity_count": len(episode._state.entities),
                "perturbation_schedule": tuple(
                    (turn, cls.value, terminal)
                    for turn, cls, terminal in episode._perturbation_schedule
                ),
                "T": episode.T,
            }
        finally:
            episode.cleanup()

    def _alias_topology(self, episode: InteractiveEpisode) -> str:
        """Classify the alias graph topology for the signature."""
        aliases = episode._state.aliases
        if not aliases:
            return "disconnected"
        targets = set(aliases.values())
        if len(targets) == 1:
            return "star" if len(aliases) > 1 else "chain"
        return "chain"
