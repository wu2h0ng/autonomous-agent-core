from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ActionOutcomeModel:
    """Belief over each action's reward: a running estimate plus an uncertainty.

    Uncertainty rises with surprise and relaxes under consistent observation, so
    a regime change (sustained prediction error) re-inflates uncertainty — the
    epistemic hook the relevance field reads. Unvisited actions keep their high
    prior uncertainty and so stay attractive to exploration.
    """

    n_actions: int
    lr: float = 0.3
    mu: list[float] = field(default_factory=list)
    uncertainty: list[float] = field(default_factory=list)
    last_surprise: float = 0.0

    def __post_init__(self) -> None:
        if not self.mu:
            self.mu = [0.0] * self.n_actions
        if not self.uncertainty:
            self.uncertainty = [1.0] * self.n_actions

    def predict(self, action: int) -> float:
        return self.mu[action]

    def update(self, action: int, reward: float) -> float:
        err = reward - self.mu[action]
        surprise = abs(err)
        self.mu[action] += self.lr * err
        self.uncertainty[action] = (
            1 - self.lr
        ) * self.uncertainty[action] + self.lr * surprise
        self.last_surprise = surprise
        return surprise

    def best_action(self) -> int:
        return max(range(self.n_actions), key=lambda a: self.mu[a])

    def total_uncertainty(self) -> float:
        return sum(self.uncertainty) / max(1, self.n_actions)
