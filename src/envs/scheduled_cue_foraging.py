from __future__ import annotations

import random
from itertools import combinations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aac.viability import ViabilityCore


RelevantSet = tuple[int, ...]


def max_fixed_subset_coverage(relevant_sets: list[RelevantSet], K: int, m: int) -> int:
    """Largest number of regimes covered by any fixed m-cue subset."""

    best = 0
    for subset in combinations(range(K), m):
        subset_set = set(subset)
        cover = sum(1 for rel in relevant_sets if set(rel).issubset(subset_set))
        best = max(best, cover)
    return best


def generate_balanced_relevant_sets(
    K: int,
    k_rel: int,
    m: int,
    n_regimes: int,
    rng: random.Random,
    max_cover_fraction: float = 0.25,
) -> list[RelevantSet]:
    """Generate a schedule that removes the fixed-attention lottery.

    No fixed m-subset may cover more than max_cover_fraction of regimes.
    The schedule is generated before the experiment and is independent of any
    variant's behavior.
    """

    if k_rel > m:
        raise ValueError("m must be at least k_rel for coverage accounting")
    max_cover = max(1, int(n_regimes * max_cover_fraction))
    all_sets = [tuple(c) for c in combinations(range(K), k_rel)]
    schedule: list[RelevantSet] = []

    attempts = 0
    while len(schedule) < n_regimes:
        attempts += 1
        if attempts > 10_000:
            raise RuntimeError("failed to generate balanced relevant-set schedule")
        candidate = rng.choice(all_sets)
        trial = schedule + [candidate]
        if max_fixed_subset_coverage(trial, K, m) <= max_cover:
            schedule.append(candidate)
    return schedule


class ScheduledLethalCueForaging:
    """Lethal cue foraging with a pre-generated relevant-set schedule."""

    def __init__(
        self,
        relevant_sets: list[RelevantSet],
        K: int = 12,
        k_rel: int = 2,
        m: int = 3,
        n_actions: int = 4,
        regime_period: int = 60,
        reward_hit: float = 2.0,
        reward_miss: float = -1.5,
        noise: float = 0.3,
        attention_cost: float = 0.08,
        rng: random.Random | None = None,
    ) -> None:
        if not relevant_sets:
            raise ValueError("relevant_sets must not be empty")
        self.rng = rng if rng is not None else random.Random()
        self.relevant_sets = [tuple(sorted(s)) for s in relevant_sets]
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
        self._mapping_schedule = [self._random_mapping() for _ in self.relevant_sets]
        self._cue_vector: tuple[int, ...] = ()
        self._sample_cues()

    @property
    def relevant_set(self) -> RelevantSet:
        return self.relevant_sets[self.regime_index % len(self.relevant_sets)]

    @property
    def _mapping(self) -> dict[tuple[int, ...], int]:
        return self._mapping_schedule[self.regime_index % len(self._mapping_schedule)]

    def _random_mapping(self) -> dict[tuple[int, ...], int]:
        mapping = {}
        for bits in range(1 << self.k_rel):
            sub = tuple((bits >> i) & 1 for i in range(self.k_rel))
            mapping[sub] = self.rng.randrange(self.n_actions)
        return mapping

    def force_regime_change(self) -> None:
        self.regime_index += 1

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
        sub = tuple(cues[i] for i in self.relevant_set)
        return self._mapping[sub]

    def act(self, action: int, attended_indices: list[int]) -> float:
        del attended_indices
        best = self.best_action_for(self._cue_vector)
        noise_free = self.reward_hit if action == best else self.reward_miss
        self.last_regret = self.reward_hit - noise_free
        reward = noise_free + self.rng.gauss(0.0, self.noise)
        self.t += 1
        if self.t % self.regime_period == 0:
            self.force_regime_change()
        self._sample_cues()
        return reward
