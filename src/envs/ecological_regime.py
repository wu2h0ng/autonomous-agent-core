"""G12 ecological environment cells (ADR-0035).

The environment varies two axes only:

- thin vs transferable ecological structure;
- external reversible vs irreversible consequence.

Internal subject reset is not part of this environment. O1 may reset belief in
every cell, but no agent-facing or test-harness API can roll back irreversible
external damage during an episode.
"""

from __future__ import annotations

import random


class EcologicalRegimeEnv:
    def __init__(
        self,
        *,
        n_actions: int = 8,
        n_regimes: int = 5,
        period: int = 40,
        rng: random.Random | None = None,
        structured: bool,
        reversible: bool,
        noise: float = 0.3,
        reward_high: float = 4.0,
        reward_low: float = -1.0,
        damage_scale: float = 1.0,
        damage_capacity: float = 5000.0,
    ) -> None:
        if n_actions <= 2 or n_regimes <= 1 or period <= 0:
            raise ValueError("n_actions>2, n_regimes>1, period>0 required")
        if damage_scale < 0.0 or damage_capacity <= 0.0:
            raise ValueError("damage_scale>=0 and damage_capacity>0 required")
        self.n_actions = n_actions
        self.n_regimes = n_regimes
        self.period = period
        self.rng = rng if rng is not None else random.Random()
        self.structured = structured
        self.reversible = reversible
        self.noise = noise
        self.reward_high = reward_high
        self.reward_low = reward_low
        self.damage_scale = damage_scale
        self.damage_capacity = damage_capacity

        self._best_actions = self._make_best_actions()
        self._library = [self._make_rewards(best) for best in self._best_actions]
        self._current = 0
        self.t = 0
        self.regime_index = 0
        self.last_regret = 0.0
        self.last_action: int | None = None
        self.last_reward: float | None = None
        self.just_shifted = False
        self.current_damage = 0.0
        self.irreversible_damage = 0.0

    def _make_best_actions(self) -> list[int]:
        if not self.structured:
            return [self.rng.randrange(self.n_actions) for _ in range(self.n_regimes)]
        start = self.rng.randrange(self.n_actions)
        direction = self.rng.choice((-1, 1))
        return [(start + direction * i) % self.n_actions for i in range(self.n_regimes)]

    def _make_rewards(self, best: int) -> list[float]:
        if not self.structured:
            rewards = [self.reward_low] * self.n_actions
            rewards[best] = self.reward_high
            return rewards

        # Stable action topology: near actions are near in outcome in every
        # regime. This is the column factor; it is independent of reversibility.
        rewards = []
        span = self.reward_high - self.reward_low
        for action in range(self.n_actions):
            dist = min(
                (action - best) % self.n_actions,
                (best - action) % self.n_actions,
            )
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

    @property
    def _regime(self) -> list[float]:
        return self._library[self._current]

    @property
    def best_action(self) -> int:
        return max(range(self.n_actions), key=lambda a: self._regime[a])

    @property
    def expected_random_regret(self) -> float:
        return max(self._regime) - sum(self._regime) / self.n_actions

    @property
    def resource_survival(self) -> float:
        return max(0.0, 1.0 - self.current_damage / self.damage_capacity)

    def situation(self) -> dict:
        return {
            "last_action": self.last_action,
            "last_reward": self.last_reward,
            "regime_index": self.regime_index,
            "step": self.t,
            "structured": self.structured,
            "reversible": self.reversible,
            "resource_survival": self.resource_survival,
        }

    def force_regime_change(self) -> None:
        self.regime_index += 1
        self._current = self.regime_index % self.n_regimes
        if self.reversible:
            self.current_damage = 0.0

    def act(self, action: int) -> float:
        base_reward = self._regime[action]
        self.last_regret = max(self._regime) - base_reward
        damage = self.damage_scale * max(0.0, self.last_regret)
        self.current_damage += damage
        if not self.reversible:
            self.irreversible_damage += damage
        reward = base_reward + self.rng.gauss(0.0, self.noise)
        self.last_action = action
        self.last_reward = reward
        self.t += 1
        self.just_shifted = False
        if self.t % self.period == 0:
            self.force_regime_change()
            self.just_shifted = True
        return reward
