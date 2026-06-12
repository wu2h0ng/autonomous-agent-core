from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aac.viability import ViabilityCore


class LethalCueForaging:
    """LatentCueForaging where *re-framing speed determines survival* (ADR-0010 D2).

    Same structure as LatentCueForaging (a hidden relevant set S and mapping
    g: {0,1}^|S| -> action drift every ``regime_period`` steps), but the
    economics are lethal:

    - ``reward_miss`` is strongly negative, so acting on a stale S/g after a
      shift drains budget fast.
    - the budget is tight, so an agent that does not re-identify S and g quickly
      after a shift dies.

    Design note (falsification honesty): the post-shift mapping is resampled
    *at random*, NOT adversarially aligned against the agent's current policy.
    A random resample already makes the old policy ~(n-1)/n wrong, which —
    combined with lethal misses — makes re-framing the survival variable for
    EVERY variant equally. Adversarial remapping was rejected to avoid rigging
    the environment toward any one mechanism (see ADR-0010 D2 final form).
    """

    def __init__(
        self,
        K: int = 12,
        k_rel: int = 2,
        m: int = 3,
        n_actions: int = 4,
        regime_period: int = 80,
        reward_hit: float = 2.0,
        reward_miss: float = -1.5,
        noise: float = 0.3,
        attention_cost: float = 0.1,
        rng: random.Random | None = None,
    ) -> None:
        self.rng = rng if rng is not None else random.Random()
        self.K = K
        self.k_rel = k_rel
        self.m = m
        self.n_actions = n_actions
        self.regime_period = regime_period
        self.reward_hit = reward_hit
        self.reward_miss = reward_miss
        self.noise = noise
        self.attention_cost = attention_cost
        self.t = 0
        self.regime_index = 0
        self.last_regret = 0.0
        self._relevant_set: list[int] = []
        self._mapping: dict[tuple[int, ...], int] = {}
        self._cue_vector: tuple[int, ...] = ()
        self._new_regime()
        self._sample_cues()

    def _new_regime(self) -> None:
        self._relevant_set = sorted(self.rng.sample(range(self.K), self.k_rel))
        self._mapping = {}
        for bits in range(1 << self.k_rel):
            sub = tuple((bits >> i) & 1 for i in range(self.k_rel))
            self._mapping[sub] = self.rng.randrange(self.n_actions)

    def force_regime_change(self) -> None:
        self.regime_index += 1
        self._new_regime()

    def _sample_cues(self) -> None:
        self._cue_vector = tuple(self.rng.randint(0, 1) for _ in range(self.K))

    def get_cue_vector(self) -> tuple[int, ...]:
        return self._cue_vector

    def observe(self, attended_indices: list[int]) -> dict[int, int]:
        return {i: self._cue_vector[i] for i in attended_indices}

    def pay_attention(self, n_cues: int, viability: ViabilityCore) -> None:
        if n_cues < 0 or n_cues > self.K:
            raise ValueError(f"Cannot attend {n_cues} cues: only K={self.K} exist")
        viability.ingest(-self.attention_cost * n_cues)

    def best_action_for(self, cues: tuple[int, ...]) -> int:
        sub = tuple(cues[i] for i in self._relevant_set)
        return self._mapping[sub]

    def act(self, action: int, attended_indices: list[int]) -> float:
        best = self.best_action_for(self._cue_vector)
        noise_free = self.reward_hit if action == best else self.reward_miss
        self.last_regret = self.reward_hit - noise_free
        reward = noise_free + self.rng.gauss(0.0, self.noise)
        self.t += 1
        if self.t % self.regime_period == 0:
            self.force_regime_change()
        self._sample_cues()
        return reward
