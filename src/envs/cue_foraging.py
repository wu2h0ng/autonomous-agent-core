from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aac.viability import ViabilityCore


class LatentCueForaging:
    """A foraging world where *what is relevant* drifts.

    Each step the world emits *K* binary cues.  A hidden relevant set
    S (|S| = k_rel) and a hidden mapping g: {0,1}^k_rel -> action together
    determine the optimal action.  The agent can only *attend* to m of
    the K cues (m < K) and pays alpha per attended cue through
    :class:`ViabilityCore.ingest`.

    Every ``regime_period`` steps (or on :meth:`force_regime_change`),
    both S and g are resampled -- the *relevant features themselves*
    shift, not just reward magnitudes.
    """

    def __init__(
        self,
        K: int = 12,
        k_rel: int = 2,
        m: int = 3,
        n_actions: int = 4,
        regime_period: int = 60,
        reward_hit: float = 3.0,
        reward_miss: float = -0.5,
        noise: float = 0.3,
        attention_cost: float = 0.2,
        rng: random.Random | None = None,
    ) -> None:
        if rng is None:
            rng = random.Random()
        self.K = K
        self.k_rel = k_rel
        self.m = m
        self.n_actions = n_actions
        self.regime_period = regime_period
        self.reward_hit = reward_hit
        self.reward_miss = reward_miss
        self.noise = noise
        self.attention_cost = attention_cost
        self.rng = rng
        self.t: int = 0
        self.regime_index: int = 0
        self.last_regret: float = 0.0
        self._relevant_set: list[int] = []
        self._mapping: dict[tuple[int, ...], int] = {}
        self._cue_vector: tuple[int, ...] = ()
        self._new_regime()
        self._sample_cues()

    # -- regime management ------------------------------------------------

    def _new_regime(self) -> None:
        """Resample the relevant set S and the cue-to-action mapping g."""
        self._relevant_set = sorted(
            self.rng.sample(range(self.K), self.k_rel)
        )
        # Enumerate all 2^k_rel possible sub-vectors and assign a random action.
        self._mapping = {}
        for bits in range(1 << self.k_rel):
            sub = tuple((bits >> i) & 1 for i in range(self.k_rel))
            self._mapping[sub] = self.rng.randrange(self.n_actions)

    def force_regime_change(self) -> None:
        self.regime_index += 1
        self._new_regime()

    # -- cue generation ---------------------------------------------------

    def _sample_cues(self) -> None:
        self._cue_vector = tuple(self.rng.randint(0, 1) for _ in range(self.K))

    def get_cue_vector(self) -> tuple[int, ...]:
        """Return the full K-dimensional binary cue vector for this step."""
        return self._cue_vector

    # -- attention --------------------------------------------------------

    def observe(self, attended_indices: list[int]) -> dict[int, int]:
        """Return cue values only for the attended indices."""
        return {i: self._cue_vector[i] for i in attended_indices}

    def pay_attention(self, n_cues: int, viability: ViabilityCore) -> None:
        """Deduct the metabolic cost of attending *n_cues* cues.

        Raises :class:`ValueError` if n_cues exceeds the attention
        capacity m or the total number of cues K.
        """
        if n_cues < 0 or n_cues > self.m:
            raise ValueError(
                f"Cannot attend {n_cues} cues: attention capacity m={self.m}"
            )
        if n_cues > self.K:
            raise ValueError(
                f"Cannot attend {n_cues} cues: only K={self.K} cues exist"
            )
        cost = self.attention_cost * n_cues
        viability.ingest(-cost)

    # -- action & reward --------------------------------------------------

    def best_action_for(self, cues: tuple[int, ...]) -> int:
        """Return the optimal action given the full cue vector."""
        sub = tuple(cues[i] for i in self._relevant_set)
        return self._mapping[sub]

    def act(self, action: int, attended_indices: list[int]) -> float:
        """Execute *action*, return noisy reward, advance time.

        ``last_regret`` is set to the noise-free gap between the hit
        reward and the reward the chosen action deserved under the
        current regime (matches :class:`GridlessSurvival` semantics).
        """
        best = self.best_action_for(self._cue_vector)
        if action == best:
            noise_free_reward = self.reward_hit
        else:
            noise_free_reward = self.reward_miss
        # Regret: gap between what the best action earns and what was chosen.
        self.last_regret = self.reward_hit - noise_free_reward
        reward = noise_free_reward + self.rng.gauss(0.0, self.noise)
        self.t += 1
        if self.t % self.regime_period == 0:
            self.force_regime_change()
        # Resample cues for the next step.
        self._sample_cues()
        return reward
