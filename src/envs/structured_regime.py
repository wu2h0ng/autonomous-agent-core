"""Structured-regime environment with TRANSFERABLE structure (T-P4.x.1, ADR-0017).

Unlike StalenessEnv (i.i.d. regimes, nothing to transfer), here regimes are
drawn from a small FIXED LIBRARY of K latent reward vectors and RECUR. A cheap
reset organ can only forget and re-learn each recurrence from scratch; a learned
organ that has built a library of regime prototypes can, after a couple of
post-shift observations, RECOGNISE a recurring regime and jump straight to its
known values. This is the structure G6a tests: does learning beat cheap reset
WHEN there is exploitable structure?

The current regime is NOT directly observable; an organ must infer it from
(action, reward) observations, which the env exposes via situation() so a
belief-only adviser can read them (it still only OUTPUTS belief advice — C6).
"""
from __future__ import annotations

import random


class StructuredRegimeEnv:
    def __init__(
        self,
        n_actions: int = 8,
        rng: random.Random | None = None,
        n_regimes: int = 5,
        period: int = 40,
        noise: float = 0.3,
        reward_low: float = -1.0,
        reward_high: float = 4.0,
        severity: float | None = None,
    ) -> None:
        if n_actions <= 0 or n_regimes <= 1 or period <= 0:
            raise ValueError("n_actions>0, n_regimes>1, period>0 required")
        if severity is not None and not 0.0 <= severity <= 1.0:
            raise ValueError("severity must be in [0, 1]")
        self.n_actions = n_actions
        self.rng = rng if rng is not None else random.Random()
        self.n_regimes = n_regimes
        self.period = period
        self.noise = noise
        self.severity = severity
        # Fixed library of recurring latent regimes (generated once, seeded).
        if severity is None:
            self._library = [
                [self.rng.uniform(reward_low, reward_high) for _ in range(n_actions)]
                for _ in range(n_regimes)
            ]
        else:
            non_best = reward_high - severity * (reward_high - reward_low)
            self._library = []
            for _ in range(n_regimes):
                best = self.rng.randrange(n_actions)
                rewards = [non_best] * n_actions
                rewards[best] = reward_high
                self._library.append(rewards)
        self._current = 0
        self.t = 0
        self.regime_index = 0
        self.last_regret = 0.0
        self.just_shifted = False
        self.last_action: int | None = None
        self.last_reward: float | None = None

    @property
    def _regime(self) -> list[float]:
        return self._library[self._current]

    @property
    def best_action(self) -> int:
        return max(range(self.n_actions), key=lambda a: self._regime[a])

    @property
    def expected_random_regret(self) -> float:
        """Scoring/judge use only: max(regime) - mean(regime)."""
        return max(self._regime) - sum(self._regime) / self.n_actions

    def situation(self) -> dict:
        return {
            "last_action": self.last_action,
            "last_reward": self.last_reward,
            "regime_index": self.regime_index,
            "step": self.t,
        }

    def force_regime_change(self) -> None:
        self.regime_index += 1
        # Recur: switch to a DIFFERENT library regime (structure = recurrence).
        choices = [i for i in range(self.n_regimes) if i != self._current]
        self._current = self.rng.choice(choices)

    def act(self, action: int) -> float:
        self.last_regret = max(self._regime) - self._regime[action]
        reward = self._regime[action] + self.rng.gauss(0.0, self.noise)
        self.last_action = action
        self.last_reward = reward
        self.t += 1
        self.just_shifted = False
        if self.t % self.period == 0:
            self.force_regime_change()
            self.just_shifted = True
        return reward
