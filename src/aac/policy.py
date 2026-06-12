from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .world_model import ActionOutcomeModel


@dataclass
class PolicySelector:
    """Expected-free-energy-flavoured action choice.

    ``score(a) = pragmatic_weight * mu[a] + epistemic_weight * uncertainty[a]``

    Pragmatic weight rises with budget pressure (feed urgency); epistemic weight
    is the relevance field's explore_drive; selection temperature also softens
    with explore_drive. Forbidden actions (the shell's 'tighten') get weight 0.
    """

    rng: random.Random
    base_temperature: float = 0.3
    forbidden: frozenset[int] = frozenset()

    def select(
        self,
        model: ActionOutcomeModel,
        explore_drive: float,
        pressure: float,
    ) -> int:
        prag_w = 0.5 + pressure
        epis_w = explore_drive
        scores: list[float] = []
        for a in range(model.n_actions):
            if a in self.forbidden:
                scores.append(float("-inf"))
            else:
                scores.append(prag_w * model.mu[a] + epis_w * model.uncertainty[a])
        temperature = self.base_temperature + explore_drive
        return self._sample(scores, temperature)

    def _sample(self, scores: list[float], temperature: float) -> int:
        finite = [s for s in scores if s != float("-inf")]
        if not finite:
            raise ValueError("all actions forbidden")
        m = max(finite)
        weights: list[float] = []
        for s in scores:
            if s == float("-inf"):
                weights.append(0.0)
            else:
                weights.append(math.exp((s - m) / max(1e-6, temperature)))
        total = sum(weights)
        r = self.rng.random() * total
        upto = 0.0
        for a, w in enumerate(weights):
            upto += w
            if upto >= r:
                return a
        return len(weights) - 1
