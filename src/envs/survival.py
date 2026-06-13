from __future__ import annotations

import random


class GridlessSurvival:
    """A domain-agnostic micro-world.

    Each action yields a reward drawn around a hidden per-action mean (the
    'regime'). The regime is re-randomised every ``regime_period`` steps — the
    rule change the agent must re-frame to keep surviving. No business semantics:
    only actions, rewards, and a shifting world.
    """

    def __init__(
        self,
        n_actions: int,
        rng: random.Random,
        regime_period: int = 40,
        noise: float = 0.3,
        reward_low: float = -1.0,
        reward_high: float = 4.0,
    ) -> None:
        self.n_actions = n_actions
        self.rng = rng
        self.regime_period = regime_period
        self.noise = noise
        self.reward_low = reward_low
        self.reward_high = reward_high
        self.t = 0
        self.regime_index = 0
        self.last_regret = 0.0
        self._regime: list[float] = []
        self._new_regime()

    def _new_regime(self) -> None:
        self._regime = [
            self.rng.uniform(self.reward_low, self.reward_high)
            for _ in range(self.n_actions)
        ]

    @property
    def best_action(self) -> int:
        return max(range(self.n_actions), key=lambda a: self._regime[a])

    @property
    def expected_random_regret(self) -> float:
        """Expected regret of a uniform-random action under the current regime.

        Scoring/judge use only (like :attr:`best_action`): equals
        ``max(regime) - mean(regime)``. Deciders (RAP nodes, B-central) must
        not read this — it would leak the regime.
        """
        return max(self._regime) - sum(self._regime) / self.n_actions

    def force_regime_change(self) -> None:
        self.regime_index += 1
        self._new_regime()

    def act(self, action: int) -> float:
        # Regret of this choice under the CURRENT regime (before any switch):
        # the noise-free reward gap between the best action and the chosen one.
        self.last_regret = max(self._regime) - self._regime[action]
        reward = self._regime[action] + self.rng.gauss(0.0, self.noise)
        self.t += 1
        if self.t % self.regime_period == 0:
            self.force_regime_change()
        return reward
