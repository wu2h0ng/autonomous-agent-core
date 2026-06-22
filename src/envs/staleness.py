"""Staleness-only environment with NON-STATIONARY shift hazard (T-P4.2/G5).

The single bottleneck is post-shift reconvergence: a hidden per-action reward
regime drifts, and the only thing that costs regret is how fast the subject
re-frames after a shift. No cues, no nodes, no attention — this is not the
claim-2 or RAP surface (ADR-0015 A2 experimental hygiene).

Critically (P4 memo §4), the shift hazard is NON-STATIONARY: the run alternates
FAST epochs (shifts every ``period_fast``) and SLOW epochs (every
``period_slow``). A fixed reset (O1) cannot tune to a single period; an adaptive
reset (O2) can in principle exploit the varying hazard. A constant-hazard env
would make G5-2 (O2<O1) a rigged false-negative, so the variation is essential.
"""

from __future__ import annotations

import random


class StalenessEnv:
    def __init__(
        self,
        n_actions: int = 8,
        rng: random.Random | None = None,
        period_fast: int = 20,
        period_slow: int = 120,
        epoch_len: int = 240,
        noise: float = 0.3,
        reward_low: float = -1.0,
        reward_high: float = 4.0,
    ) -> None:
        if n_actions <= 0:
            raise ValueError("n_actions must be positive")
        if period_fast <= 0 or period_slow <= 0:
            raise ValueError("periods must be positive")
        if epoch_len <= 0:
            raise ValueError("epoch_len must be positive")
        self.n_actions = n_actions
        self.rng = rng if rng is not None else random.Random()
        self.period_fast = period_fast
        self.period_slow = period_slow
        self.epoch_len = epoch_len
        self.noise = noise
        self.reward_low = reward_low
        self.reward_high = reward_high
        self.t = 0
        self.regime_index = 0
        self.last_regret = 0.0
        self.just_shifted = False
        self._regime: list[float] = []
        self._new_regime()
        self._next_shift = self._period_at(0)

    def _period_at(self, t: int) -> int:
        """FAST on even epochs, SLOW on odd — non-stationary hazard."""
        return self.period_fast if (t // self.epoch_len) % 2 == 0 else self.period_slow

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
        """Judge/scoring use only (not for deciders): max(regime) - mean(regime)."""
        return max(self._regime) - sum(self._regime) / self.n_actions

    def situation(self) -> dict[str, int]:
        return {"step": self.t, "regime_index": self.regime_index}

    def force_regime_change(self) -> None:
        self.regime_index += 1
        self._new_regime()

    def act(self, action: int) -> float:
        self.last_regret = max(self._regime) - self._regime[action]
        reward = self._regime[action] + self.rng.gauss(0.0, self.noise)
        self.t += 1
        self.just_shifted = False
        if self.t >= self._next_shift:
            self.force_regime_change()
            self._next_shift = self.t + self._period_at(self.t)
            self.just_shifted = True
        return reward
