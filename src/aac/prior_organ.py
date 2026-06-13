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
    """Advisory belief delta; never an action or shell command.

    Two belief channels (T-P4.1.1, ADR-0016): ``belief_delta`` nudges the mu
    (value) estimate; ``uncertainty_delta`` nudges the epistemic (uncertainty)
    estimate. Both stay strictly inside the belief — there is no action,
    policy, or shell surface here.
    """

    belief_delta: Mapping[int, float] = field(default_factory=dict)
    uncertainty: float = 0.0
    counterfactual_hint: Mapping[str, Any] | None = None
    uncertainty_delta: Mapping[int, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.uncertainty <= 1.0:
            raise ValueError("uncertainty must be in [0, 1]")
        object.__setattr__(self, "belief_delta", _validated_delta(self.belief_delta))
        object.__setattr__(
            self, "uncertainty_delta", _validated_delta(self.uncertainty_delta)
        )
        if self.counterfactual_hint is not None:
            object.__setattr__(
                self, "counterfactual_hint", dict(self.counterfactual_hint)
            )


def _validated_delta(raw: Mapping[int, float]) -> dict[int, float]:
    delta: dict[int, float] = {}
    for action, value in raw.items():
        if not isinstance(action, int) or action < 0:
            raise ValueError("delta keys must be non-negative action ids")
        v = float(value)
        if not math.isfinite(v):
            raise ValueError("delta values must be finite")
        delta[action] = v
    return delta


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

    ``uncertainty`` is the organ's self-confidence, used as a bounded weight on
    BOTH channels. ``belief_delta`` adjusts mu; ``uncertainty_delta`` adjusts the
    epistemic uncertainty (clamped at 0). Invalid action ids are rejected
    instead of silently becoming hidden control channels.
    """

    if advice.uncertainty <= 0.0 or (
        not advice.belief_delta and not advice.uncertainty_delta
    ):
        return 0
    applied = 0
    for action, delta in advice.belief_delta.items():
        if action >= model.n_actions:
            raise ValueError(f"belief_delta action out of range: {action}")
        model.mu[action] += advice.uncertainty * delta
        applied += 1
    for action, udelta in advice.uncertainty_delta.items():
        if action >= model.n_actions:
            raise ValueError(f"uncertainty_delta action out of range: {action}")
        model.uncertainty[action] = max(
            0.0, model.uncertainty[action] + advice.uncertainty * udelta
        )
        applied += 1
    return applied
