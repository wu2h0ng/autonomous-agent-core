"""WeightMemory — decouples strategy-loop and action-loop belief models.

The core finding from G11: strategy (LLM weight proposals) and action (G10
confidence gate) share the same EMA belief model. When the strategy loop
switches weights, the action model becomes stale → cold-start penalty eats
the strategy gains.

WeightMemory solves this by maintaining a bank of (weight_vector, action_priors)
pairs. When the strategy loop proposes a new weight, the action loop looks up
the closest past weight and initializes with those priors — avoiding cold-start
when revisiting a previously-seen regime. For truly novel weights, starts fresh.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return dot / (na * nb)


@dataclass
class WeightMemory:
    """Priors bank: maps weight vectors to action-value estimates.

    Enables transfer learning across regime recurrences. When the strategy
    loop revisits a previously-seen regime (similar weights), the action
    loop gets warm-started from the stored priors instead of cold-starting.

    Capacity is unbounded in the prototype; for production, an LRU eviction
    or Gaussian Process kernel would replace this list.
    """

    min_similarity: float = 0.95  # cosine threshold for "same regime"
    entries: list[dict] = field(default_factory=list)

    def lookup(self, weights: list[float]) -> dict | None:
        """Return stored priors for similar past weight, or None if novel."""
        best_cos = 0.0
        best_entry: dict | None = None
        for entry in self.entries:
            cos = _cosine_similarity(weights, entry["weights"])
            if cos > best_cos:
                best_cos = cos
                best_entry = entry
        if best_cos >= self.min_similarity and best_entry is not None:
            return {
                "mu": list(best_entry["mu"]),
                "uncertainty": list(best_entry["uncertainty"]),
                "similarity": best_cos,
            }
        return None

    def store(
        self,
        weights: list[float],
        mu: list[float],
        uncertainty: list[float],
        score: float = 0.0,
    ) -> None:
        """Store or update priors for a weight vector.

        If a similar entry exists, updates with EWMA. Otherwise appends new.
        """
        existing_cos = 0.0
        existing_idx = -1
        for i, entry in enumerate(self.entries):
            cos = _cosine_similarity(weights, entry["weights"])
            if cos > existing_cos:
                existing_cos = cos
                existing_idx = i

        if existing_cos >= self.min_similarity and existing_idx >= 0:
            e = self.entries[existing_idx]
            alpha = 0.3
            e["weights"] = [
                (1 - alpha) * w + alpha * w2
                for w, w2 in zip(e["weights"], weights)
            ]
            e["mu"] = [
                (1 - alpha) * m + alpha * m2
                for m, m2 in zip(e["mu"], mu)
            ]
            e["uncertainty"] = [
                max(0.1, (1 - alpha) * u + alpha * u2)
                for u, u2 in zip(e["uncertainty"], uncertainty)
            ]
            e["score"] = score
        else:
            self.entries.append({
                "weights": list(weights),
                "mu": list(mu),
                "uncertainty": list(uncertainty),
                "score": score,
            })

    def warm_start_model(self, model: Any, weights: list[float]) -> bool:
        """Initialize model from stored priors if available. Returns True if warm-started."""
        priors = self.lookup(weights)
        if priors is None:
            return False
        for a in range(model.n_actions):
            model.mu[a] = priors["mu"][a]
            # Blend old uncertainty with moderate uncertainty (avoid overconfidence)
            model.uncertainty[a] = 0.3 * priors["uncertainty"][a] + 0.7 * 0.5
        return True

    def snapshot_model(self, weights: list[float], model: Any) -> None:
        """Save current model state as priors for this weight vector."""
        self.store(weights, list(model.mu), list(model.uncertainty))

    def __len__(self) -> int:
        return len(self.entries)
