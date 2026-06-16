"""Bounded consequence-prior organ for ADR-0036/G13.

The organ predicts public action consequences and converts them into bounded
belief deltas. It has no action, policy, shell, audit, or gate surface; the
subject's existing policy remains the only action selector.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .prior_organ import BeliefSnapshot, OrganAdvice


def _finite(name: str, value: float) -> float:
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite")
    return v


def _clip(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


@dataclass(frozen=True, slots=True)
class ConsequencePriorRecord:
    """Allowed CP output record.

    ``action_id`` identifies the action being described; it is not an action
    command. The remaining fields are belief-like consequence estimates.
    """

    action_id: int
    predicted_scar_delta: float = 0.0
    predicted_resource_delta: float = 0.0
    predicted_conflict_delta: float = 0.0
    uncertainty: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, int) or self.action_id < 0:
            raise ValueError("action_id must be a non-negative integer")
        for name in (
            "predicted_scar_delta",
            "predicted_resource_delta",
            "predicted_conflict_delta",
        ):
            object.__setattr__(self, name, _finite(name, getattr(self, name)))
        u = _finite("uncertainty", self.uncertainty)
        if not 0.0 <= u <= 1.0:
            raise ValueError("uncertainty must be in [0, 1]")
        object.__setattr__(self, "uncertainty", u)


@dataclass
class BoundedConsequencePriorOrgan:
    """Belief-only scar prior.

    The organ reads only public ``public_consequence_features`` from the
    environment situation. It deliberately ignores hidden/evaluator keys so
    apparatus labels cannot become a control channel.
    """

    scar_weight: float = 1.2
    resource_weight: float = 0.25
    conflict_weight: float = 0.15
    max_abs_delta: float = 2.0
    merge_weight: float = 0.65

    _last_records: tuple[ConsequencePriorRecord, ...] = field(
        default_factory=tuple, init=False
    )

    @property
    def last_records(self) -> tuple[ConsequencePriorRecord, ...]:
        return self._last_records

    def predict(
        self,
        situation: Mapping[str, Any],
        belief_readonly: BeliefSnapshot,
    ) -> tuple[ConsequencePriorRecord, ...]:
        features = situation.get("public_consequence_features")
        if not isinstance(features, (list, tuple)):
            return ()

        records: list[ConsequencePriorRecord] = []
        seen: set[int] = set()
        for raw in features:
            if not isinstance(raw, Mapping):
                continue
            action = raw.get("action_id")
            if not isinstance(action, int):
                continue
            if action < 0 or action >= belief_readonly.n_actions or action in seen:
                continue
            seen.add(action)
            records.append(
                ConsequencePriorRecord(
                    action_id=action,
                    predicted_scar_delta=max(0.0, _finite("scar_delta", raw.get("scar_delta", 0.0))),
                    predicted_resource_delta=max(
                        0.0, _finite("resource_delta", raw.get("resource_delta", 0.0))
                    ),
                    predicted_conflict_delta=max(
                        0.0, _finite("conflict_delta", raw.get("conflict_delta", 0.0))
                    ),
                    uncertainty=max(
                        0.0,
                        min(1.0, _finite("uncertainty", raw.get("uncertainty", 0.5))),
                    ),
                )
            )
        return tuple(records)

    def advise(
        self,
        situation: Mapping[str, Any],
        belief_readonly: BeliefSnapshot,
    ) -> OrganAdvice:
        records = self.predict(situation, belief_readonly)
        self._last_records = records
        if not records:
            return OrganAdvice()

        belief_delta: dict[int, float] = {}
        uncertainty_delta: dict[int, float] = {}
        for record in records:
            penalty = (
                self.scar_weight * record.predicted_scar_delta
                + self.resource_weight * record.predicted_resource_delta
                + self.conflict_weight * record.predicted_conflict_delta
            )
            if penalty > 0.0:
                target = -_clip(penalty, self.max_abs_delta)
                belief_delta[record.action_id] = _clip(
                    target - belief_readonly.mu[record.action_id],
                    self.max_abs_delta,
                )
                # Risky actions become slightly less epistemically attractive.
                uncertainty_delta[record.action_id] = -0.2 * record.uncertainty

        if not belief_delta and not uncertainty_delta:
            return OrganAdvice()

        mean_u = sum(r.uncertainty for r in records) / len(records)
        merge_u = max(0.0, min(1.0, self.merge_weight * mean_u))
        return OrganAdvice(
            belief_delta=belief_delta,
            uncertainty_delta=uncertainty_delta,
            uncertainty=merge_u,
            counterfactual_hint={
                "consequence_records": [asdict(record) for record in records]
            },
        )

    def reset(self) -> None:
        self._last_records = ()


@dataclass
class CautiousScarOrgan:
    """Cheap frozen control: penalise only obviously high public scar exposure."""

    threshold: float = 0.75
    penalty: float = 1.5
    merge_weight: float = 0.7

    def advise(
        self,
        situation: Mapping[str, Any],
        belief_readonly: BeliefSnapshot,
    ) -> OrganAdvice:
        features = situation.get("public_consequence_features")
        if not isinstance(features, (list, tuple)):
            return OrganAdvice()
        belief_delta: dict[int, float] = {}
        for raw in features:
            if not isinstance(raw, Mapping):
                continue
            action = raw.get("action_id")
            if not isinstance(action, int) or action < 0 or action >= belief_readonly.n_actions:
                continue
            scar = max(0.0, _finite("scar_delta", raw.get("scar_delta", 0.0)))
            if scar >= self.threshold:
                belief_delta[action] = _clip(
                    -self.penalty - belief_readonly.mu[action],
                    self.penalty,
                )
        if not belief_delta:
            return OrganAdvice()
        return OrganAdvice(belief_delta=belief_delta, uncertainty=self.merge_weight)
