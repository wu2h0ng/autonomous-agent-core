from __future__ import annotations

from itertools import combinations
from typing import Any, Iterable


Candidate = tuple[int, ...]


def candidate_sets_from_attended(attended: Iterable[int], k_rel: int) -> list[Candidate]:
    """Return sorted candidate relevant sets fully visible in attended cues."""

    return [tuple(c) for c in combinations(sorted(attended), k_rel)]


class FactorizedContextualActionModel:
    """Action values keyed by a hypothesized relevant set and its cue values.

    ADR-0010's exact attended-pattern key fragmented learning across attention
    supersets.  This model only keys on the hypothesized relevant subset:

        key = (hypothesis_S, values_of_S)

    If two different attention supersets imply the same S values, they share
    action-value learning.  That is the minimum organ needed for G2's causal
    relevance search to turn "this set explains reward" into action.
    """

    def __init__(self, n_actions: int, lr: float = 0.4, margin: float = 0.75) -> None:
        self.n_actions = n_actions
        self.lr = lr
        self.margin = margin
        self._q: dict[tuple[Candidate, tuple[int, ...]], list[float]] = {}
        self._counts: dict[tuple[Candidate, tuple[int, ...]], list[int]] = {}

    @staticmethod
    def _key(cues: tuple[int, ...], hypothesis: Candidate) -> tuple[Candidate, tuple[int, ...]]:
        hyp = tuple(sorted(hypothesis))
        return hyp, tuple(cues[i] for i in hyp)

    def _q_for(self, cues: tuple[int, ...], hypothesis: Candidate) -> list[float]:
        key = self._key(cues, hypothesis)
        q = self._q.get(key)
        if q is None:
            q = [0.0] * self.n_actions
            self._q[key] = q
            self._counts[key] = [0] * self.n_actions
        return q

    def _counts_for(self, cues: tuple[int, ...], hypothesis: Candidate) -> list[int]:
        self._q_for(cues, hypothesis)
        return self._counts[self._key(cues, hypothesis)]

    def value(self, cues: tuple[int, ...], hypothesis: Candidate, action: int) -> float:
        return self._q_for(cues, hypothesis)[action]

    def best_action(self, cues: tuple[int, ...], hypothesis: Candidate) -> int:
        q = self._q_for(cues, hypothesis)
        return max(range(self.n_actions), key=lambda a: q[a])

    def confidence_margin(self, cues: tuple[int, ...], hypothesis: Candidate) -> float:
        q = sorted(self._q_for(cues, hypothesis))
        return q[-1] - q[-2]

    def confident(self, cues: tuple[int, ...], hypothesis: Candidate) -> bool:
        q = self._q_for(cues, hypothesis)
        counts = self._counts_for(cues, hypothesis)
        top = max(range(self.n_actions), key=lambda a: q[a])
        ranked = sorted(q)
        return counts[top] > 0 and ranked[-1] > 0.0 and (ranked[-1] - ranked[-2]) >= self.margin

    def best_hypothesis(
        self, cues: tuple[int, ...], candidates: Iterable[Candidate]
    ) -> Candidate | None:
        best: Candidate | None = None
        best_score = float("-inf")
        for candidate in candidates:
            q = self._q_for(cues, candidate)
            score = max(q) + self.confidence_margin(cues, candidate)
            if score > best_score:
                best = tuple(sorted(candidate))
                best_score = score
        return best

    def update(self, cues: tuple[int, ...], hypothesis: Candidate, action: int, reward: float) -> None:
        q = self._q_for(cues, hypothesis)
        counts = self._counts_for(cues, hypothesis)
        counts[action] += 1
        q[action] += self.lr * (reward - q[action])

    def state(self) -> dict[str, Any]:
        return {
            "q": {repr(k): list(v) for k, v in self._q.items()},
            "counts": {repr(k): list(v) for k, v in self._counts.items()},
        }
