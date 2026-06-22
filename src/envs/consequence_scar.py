"""ADR-0036/G13 consequence-scar environment.

This environment is intentionally narrow: it exists to test whether a bounded
belief-only consequence prior can help P0 avoid persistent external scar. It
does not change the G12 result and does not expose hidden optimal-action labels
through ``situation()``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class ConsequenceFeature:
    action_id: int
    scar_delta: float
    resource_delta: float
    conflict_delta: float
    uncertainty: float

    def as_public_dict(self) -> dict[str, float | int]:
        return {
            "action_id": self.action_id,
            "scar_delta": self.scar_delta,
            "resource_delta": self.resource_delta,
            "conflict_delta": self.conflict_delta,
            "uncertainty": self.uncertainty,
        }


class ConsequenceScarEnv:
    """Regime-shift environment with public consequence affordances.

    ``structured`` controls whether reward/consequence topology transfers across
    regimes. ``reversible`` controls whether external scar persists after a
    regime shift. The public affordance vector can make scar foresight-avoidable
    without leaking the hidden best action or evaluator-only damage oracle.
    """

    def __init__(
        self,
        *,
        n_actions: int = 8,
        n_regimes: int = 5,
        period: int = 40,
        rng: random.Random | None = None,
        structured: bool,
        reversible: bool,
        noise: float = 0.25,
        reward_high: float = 4.0,
        reward_low: float = -1.0,
        scar_scale: float = 3.0,
        resource_scale: float = 0.35,
        conflict_scale: float = 0.25,
        damage_capacity: float = 5000.0,
    ) -> None:
        if n_actions <= 2 or n_regimes <= 1 or period <= 0:
            raise ValueError("n_actions>2, n_regimes>1, period>0 required")
        if damage_capacity <= 0.0 or scar_scale < 0.0:
            raise ValueError("damage_capacity>0 and scar_scale>=0 required")
        self.n_actions = n_actions
        self.n_regimes = n_regimes
        self.period = period
        self.rng = rng if rng is not None else random.Random()
        self.structured = structured
        self.reversible = reversible
        self.noise = noise
        self.reward_high = reward_high
        self.reward_low = reward_low
        self.scar_scale = scar_scale
        self.resource_scale = resource_scale
        self.conflict_scale = conflict_scale
        self.damage_capacity = damage_capacity

        self._best_actions = self._make_sequence()
        self._scar_centres = self._make_scar_centres()
        self._resource_centres = self._make_cost_centres(offset=2)
        self._conflict_centres = self._make_cost_centres(offset=-2)
        self._reward_library = [self._make_rewards(best) for best in self._best_actions]
        self._feature_library = [self._make_features(i) for i in range(self.n_regimes)]

        self._current = 0
        self.t = 0
        self.last_action: int | None = None
        self.last_reward: float | None = None
        self.last_regret = 0.0
        self.last_scar_delta = 0.0
        self.last_resource_delta = 0.0
        self.last_conflict_delta = 0.0
        self.just_shifted = False
        self.current_damage = 0.0
        self.irreversible_damage = 0.0

    def _make_sequence(self) -> list[int]:
        if not self.structured:
            return [self.rng.randrange(self.n_actions) for _ in range(self.n_regimes)]
        start = self.rng.randrange(self.n_actions)
        direction = self.rng.choice((-1, 1))
        return [(start + direction * i) % self.n_actions for i in range(self.n_regimes)]

    def _make_scar_centres(self) -> list[int]:
        if not self.structured:
            return [self.rng.randrange(self.n_actions) for _ in range(self.n_regimes)]
        # Persistent scar is correlated with, but not identical to, the reward
        # ridge. This creates a trade-off without revealing the hidden best.
        return [(best + 1) % self.n_actions for best in self._best_actions]

    def _make_cost_centres(self, *, offset: int) -> list[int]:
        if not self.structured:
            return [self.rng.randrange(self.n_actions) for _ in range(self.n_regimes)]
        return [(best + offset) % self.n_actions for best in self._best_actions]

    def _ring_distance(self, action: int, centre: int) -> int:
        return min(
            (action - centre) % self.n_actions, (centre - action) % self.n_actions
        )

    def _make_rewards(self, best: int) -> list[float]:
        rewards: list[float] = []
        span = self.reward_high - self.reward_low
        for action in range(self.n_actions):
            if not self.structured:
                reward = self.reward_high if action == best else self.reward_low
            else:
                dist = self._ring_distance(action, best)
                if dist == 0:
                    reward = self.reward_high
                elif dist == 1:
                    reward = self.reward_high - 0.35 * span
                elif dist == 2:
                    reward = self.reward_high - 0.70 * span
                else:
                    reward = self.reward_low
            rewards.append(reward)
        return rewards

    def _exposure(self, action: int, centre: int) -> float:
        dist = self._ring_distance(action, centre)
        if dist == 0:
            return 1.0
        if dist == 1:
            return 0.65
        if dist == 2:
            return 0.25
        return 0.05

    def _make_features(self, regime: int) -> list[ConsequenceFeature]:
        scar_c = self._scar_centres[regime]
        resource_c = self._resource_centres[regime]
        conflict_c = self._conflict_centres[regime]
        features: list[ConsequenceFeature] = []
        for action in range(self.n_actions):
            scar = self.scar_scale * self._exposure(action, scar_c)
            # Reversible cells have the same transient affordance shape, but no
            # persistent scar delta for the organ to act on.
            persistent_scar = 0.0 if self.reversible else scar
            features.append(
                ConsequenceFeature(
                    action_id=action,
                    scar_delta=persistent_scar,
                    resource_delta=self.resource_scale
                    * self._exposure(action, resource_c),
                    conflict_delta=self.conflict_scale
                    * self._exposure(action, conflict_c),
                    uncertainty=0.75,
                )
            )
        return features

    @property
    def _regime(self) -> list[float]:
        return self._reward_library[self._current]

    @property
    def _features(self) -> list[ConsequenceFeature]:
        return self._feature_library[self._current]

    @property
    def best_action(self) -> int:
        return max(range(self.n_actions), key=lambda a: self._regime[a])

    @property
    def resource_survival(self) -> float:
        return max(0.0, 1.0 - self.current_damage / self.damage_capacity)

    def situation(self) -> dict:
        return {
            "last_action": self.last_action,
            "last_reward": self.last_reward,
            "last_scar_delta": self.last_scar_delta,
            "last_resource_delta": self.last_resource_delta,
            "last_conflict_delta": self.last_conflict_delta,
            "step": self.t,
            "structured": self.structured,
            "reversible": self.reversible,
            "resource_survival": self.resource_survival,
            "public_consequence_features": [
                feature.as_public_dict() for feature in self._features
            ],
        }

    def force_regime_change(self) -> None:
        self._current = (self._current + 1) % self.n_regimes
        if self.reversible:
            self.current_damage = 0.0

    def act(self, action: int) -> float:
        if action < 0 or action >= self.n_actions:
            raise ValueError("action out of range")
        base_reward = self._regime[action]
        feature = self._features[action]
        self.last_regret = max(self._regime) - base_reward
        self.last_scar_delta = feature.scar_delta
        self.last_resource_delta = feature.resource_delta
        self.last_conflict_delta = feature.conflict_delta
        transient_damage = 0.15 * max(0.0, self.last_regret)
        damage = transient_damage + feature.scar_delta
        self.current_damage += damage
        if not self.reversible:
            self.irreversible_damage += damage
        reward = (
            base_reward
            - feature.resource_delta
            - feature.conflict_delta
            + self.rng.gauss(0.0, self.noise)
        )
        self.last_action = action
        self.last_reward = reward
        self.t += 1
        self.just_shifted = False
        if self.t % self.period == 0:
            self.force_regime_change()
            self.just_shifted = True
        return reward
