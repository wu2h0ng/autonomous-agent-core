from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ViabilityCore:
    """Essential variables + metabolic budget. Source of intrinsic normativity.

    There is no task reward here. 'Good' and 'bad' are defined only by whether
    the budget stays above the death threshold. :attr:`pressure` (proximity to
    death) is the interoceptive signal the relevance field and policy consume.
    """

    budget: float
    metabolic_cost: float = 1.0
    death_threshold: float = 0.0
    safe_budget: float = 50.0
    capacity: float = 100.0

    @property
    def alive(self) -> bool:
        return self.budget > self.death_threshold

    @property
    def pressure(self) -> float:
        """0.0 at/above the safe budget, rising toward 1.0 as death nears."""
        span = self.safe_budget - self.death_threshold
        if span <= 0:
            return 0.0
        p = (self.safe_budget - self.budget) / span
        return max(0.0, min(1.0, p))

    def metabolize(self) -> None:
        self.budget -= self.metabolic_cost

    def ingest(self, amount: float) -> None:
        # amount may be negative (a costly action); budget is capped above.
        self.budget = min(self.capacity, self.budget + amount)
