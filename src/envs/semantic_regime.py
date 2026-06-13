"""Semantic-structure environment (G6b prerequisite, ADR-0019 §2).

The structure here is SEMANTIC, not merely statistical: each regime is a category
(bird / vehicle / ...), actions carry word LABELS, and the best action is the one
whose label is a MEMBER of the current category. Crucially, the label-to-position
assignment is RE-RANDOMISED on every shift, so a numeric/positional learner
(O0/O1/O2) cannot exploit position or recurrence — it can only re-learn each
regime by trial. An agent that understands word meaning (e.g. knows 'sparrow' is
a bird) recognises the best action ZERO-SHOT from the labels, every shift.

This is exactly where an LLM's pretrained knowledge can pay off and a numeric
learner cannot. The env is pure-stdlib and deterministic; the "understanding" is
what the organ brings. TAXONOMY is the ground truth; a real LLM brings its own
(imperfect) knowledge — the offline oracle backend simulates perfect knowledge to
prove the env is semantic-exploitable before any paid run.
"""
from __future__ import annotations

import random

TAXONOMY: dict[str, tuple[str, ...]] = {
    "bird": ("sparrow", "eagle", "owl", "robin"),
    "vehicle": ("car", "truck", "boat", "plane"),
    "fruit": ("apple", "banana", "cherry", "grape"),
    "tool": ("hammer", "wrench", "drill", "saw"),
    "fish": ("trout", "salmon", "tuna", "bass"),
}


class SemanticRegimeEnv:
    def __init__(
        self,
        n_actions: int = 6,
        rng: random.Random | None = None,
        period: int = 40,
        noise: float = 0.3,
        reward_low: float = 0.0,
        reward_high: float = 4.0,
    ) -> None:
        if n_actions < 2 or period <= 0:
            raise ValueError("n_actions>=2, period>0 required")
        self.n_actions = n_actions
        self.rng = rng if rng is not None else random.Random()
        self.period = period
        self.noise = noise
        self.reward_low = reward_low
        self.reward_high = reward_high
        self._categories = list(TAXONOMY)
        self.t = 0
        self.regime_index = 0
        self.last_regret = 0.0
        self.just_shifted = False
        self.last_action: int | None = None
        self.last_reward: float | None = None
        self._category = ""
        self._labels: list[str] = []
        self._best = 0
        self._new_regime()

    def _new_regime(self) -> None:
        # Pick a category (different from current for variety) and re-randomise
        # the label->position assignment, so position/recurrence carry no signal.
        choices = [c for c in self._categories if c != self._category] or self._categories
        self._category = self.rng.choice(choices)
        members = TAXONOMY[self._category]
        others = [w for c, ws in TAXONOMY.items() if c != self._category for w in ws]
        self._best = self.rng.randrange(self.n_actions)
        labels = [self.rng.choice(others) for _ in range(self.n_actions)]
        labels[self._best] = self.rng.choice(members)
        self._labels = labels

    @property
    def best_action(self) -> int:
        return self._best

    @property
    def expected_random_regret(self) -> float:
        # One best action at reward_high, the rest at reward_low.
        mean = (self.reward_high + (self.n_actions - 1) * self.reward_low) / self.n_actions
        return self.reward_high - mean

    def situation(self) -> dict:
        return {
            "category_cue": self._category,       # semantic; numeric organs ignore it
            "action_labels": list(self._labels),  # semantic; numeric organs ignore it
            "last_action": self.last_action,
            "last_reward": self.last_reward,
            "regime_index": self.regime_index,
            "step": self.t,
        }

    def force_regime_change(self) -> None:
        self.regime_index += 1
        self._new_regime()

    def act(self, action: int) -> float:
        value = self.reward_high if action == self._best else self.reward_low
        self.last_regret = self.reward_high - value
        reward = value + self.rng.gauss(0.0, self.noise)
        self.last_action = action
        self.last_reward = reward
        self.t += 1
        self.just_shifted = False
        if self.t % self.period == 0:
            self.force_regime_change()
            self.just_shifted = True
        return reward
