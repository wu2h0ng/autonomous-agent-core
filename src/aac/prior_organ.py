"""Minimal prior-organ interface and belief merge hook (T-P4.1).

ADR-0016 makes the organ a constrained adviser, not a decision-maker. This
module deliberately imports no policy or shell surfaces: advice can only be
merged into the action-outcome belief held by ``ActionOutcomeModel``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from .world_model import ActionOutcomeModel


@dataclass(frozen=True, slots=True)
class BeliefSnapshot:
    """Read-only view of the current action-outcome belief."""

    mu: tuple[float, ...]
    uncertainty: tuple[float, ...]
    last_surprise: float

    @property
    def n_actions(self) -> int:
        return len(self.mu)

    @property
    def total_uncertainty(self) -> float:
        return sum(self.uncertainty) / max(1, self.n_actions)


@dataclass(frozen=True, slots=True)
class OrganAdvice:
    """Advisory belief delta; never an action or shell command."""

    belief_delta: Mapping[int, float] = field(default_factory=dict)
    uncertainty: float = 0.0
    counterfactual_hint: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.uncertainty <= 1.0:
            raise ValueError("uncertainty must be in [0, 1]")
        delta: dict[int, float] = {}
        for action, value in self.belief_delta.items():
            if not isinstance(action, int) or action < 0:
                raise ValueError("belief_delta keys must be non-negative action ids")
            v = float(value)
            if not math.isfinite(v):
                raise ValueError("belief_delta values must be finite")
            delta[action] = v
        object.__setattr__(self, "belief_delta", delta)
        if self.counterfactual_hint is not None:
            object.__setattr__(
                self, "counterfactual_hint", dict(self.counterfactual_hint)
            )


class PriorOrgan(Protocol):
    """A constrained adviser: read situation + belief, return belief advice."""

    def advise(
        self,
        situation: Mapping[str, Any],
        belief_readonly: BeliefSnapshot,
    ) -> OrganAdvice:
        """Return advisory belief deltas. No action surface is exposed."""


def snapshot_belief(model: ActionOutcomeModel) -> BeliefSnapshot:
    return BeliefSnapshot(
        mu=tuple(model.mu),
        uncertainty=tuple(model.uncertainty),
        last_surprise=float(model.last_surprise),
    )


def merge_organ_advice(model: ActionOutcomeModel, advice: OrganAdvice) -> int:
    """Merge advice into belief and return the number of applied deltas.

    ``uncertainty`` is the organ's self-confidence, used as a bounded weight.
    Invalid action ids are rejected instead of silently becoming hidden control
    channels.
    """

    if advice.uncertainty <= 0.0 or not advice.belief_delta:
        return 0
    applied = 0
    for action, delta in advice.belief_delta.items():
        if action >= model.n_actions:
            raise ValueError(f"belief_delta action out of range: {action}")
        model.mu[action] += advice.uncertainty * delta
        applied += 1
    return applied
