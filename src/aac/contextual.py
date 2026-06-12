from __future__ import annotations

from typing import Any


class ContextualActionModel:
    """Action values conditioned on the *attended cue pattern* (ADR-0010 D1).

    The missing organ that converts "attending to the right cues" into
    "choosing the right action". Context key = the sorted (index, value) pairs
    of the attended cues. If the attended set covers the relevant set S, the
    key separates regimes and the per-action estimates sharpen; if it misses S,
    the key is uninformative and estimates blur — so attention quality flows
    straight through to action quality.

    Re-framing is driven by the reward signal: an EMA with rate ``lr`` lets a
    stale best action's value decay within a few visits after a regime shift,
    which collapses the spread, which flips the agent from exploit to explore
    until a new winner emerges. No special regime-shift detector is needed.
    """

    def __init__(self, n_actions: int, lr: float = 0.4, margin: float = 0.75) -> None:
        self.n_actions = n_actions
        self.lr = lr
        self.margin = margin
        self._q: dict[tuple[tuple[int, int], ...], list[float]] = {}

    @staticmethod
    def _key(attended_values: dict[int, int]) -> tuple[tuple[int, int], ...]:
        return tuple(sorted(attended_values.items()))

    def _q_for(self, key: tuple[tuple[int, int], ...]) -> list[float]:
        q = self._q.get(key)
        if q is None:
            q = [0.0] * self.n_actions
            self._q[key] = q
        return q

    def best_action(self, attended_values: dict[int, int]) -> int:
        q = self._q_for(self._key(attended_values))
        return max(range(self.n_actions), key=lambda a: q[a])

    def confident(self, attended_values: dict[int, int]) -> bool:
        """Exploit only when one action is clearly best for this context.

        Spread (top minus runner-up) >= margin AND the leader is net positive.
        After a shift the leader's value decays, spread shrinks, confidence
        drops -> the agent explores and re-frames.
        """
        q = sorted(self._q_for(self._key(attended_values)))
        return (q[-1] - q[-2]) >= self.margin and q[-1] > 0.0

    def update(self, attended_values: dict[int, int], action: int, reward: float) -> None:
        q = self._q_for(self._key(attended_values))
        q[action] += self.lr * (reward - q[action])

    def state(self) -> dict[str, Any]:
        return {"q": {k: list(v) for k, v in self._q.items()}}
