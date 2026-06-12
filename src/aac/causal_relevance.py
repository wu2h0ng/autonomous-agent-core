from __future__ import annotations

import math
import random
from itertools import combinations
from typing import Mapping

from aac.factorized_contextual import Candidate


class CausalRelevanceField:
    """Posterior over candidate relevant cue sets.

    ADR-0011 moves claim-2's mechanism from marginal cue information power to
    latent-set explanation.  A candidate set gains posterior mass when the
    action model keyed by that set predicts reward better than alternatives.
    Attention is then allocated to observe high-value candidate sets.
    """

    def __init__(
        self,
        K: int = 12,
        k_rel: int = 2,
        m: int = 3,
        lr: float = 0.25,
        score_lr: float = 0.35,
        confidence_threshold: float = 0.06,
        surprise_threshold: float = 1.8,
        reset_decay: float = 0.35,
        ablate_posterior: bool = False,
    ) -> None:
        if k_rel <= 0 or k_rel > K:
            raise ValueError("k_rel must be in 1..K")
        if m <= 0 or m > K:
            raise ValueError("m must be in 1..K")
        self.K = K
        self.k_rel = k_rel
        self.m = m
        self.lr = lr
        self.score_lr = score_lr
        self.confidence_threshold = confidence_threshold
        self.surprise_threshold = surprise_threshold
        self.reset_decay = reset_decay
        self.ablate_posterior = ablate_posterior
        self.candidates: list[Candidate] = [
            tuple(c) for c in combinations(range(K), k_rel)
        ]
        self._log_weights: dict[Candidate, float] = {c: 0.0 for c in self.candidates}
        self._error_ema: dict[Candidate, float] = {c: surprise_threshold for c in self.candidates}
        self._cue_counts: list[int] = [0] * K
        self._reframing_steps = 0

    # -- posterior --------------------------------------------------------

    def _weights(self) -> dict[Candidate, float]:
        if self.ablate_posterior:
            p = 1.0 / len(self.candidates)
            return {c: p for c in self.candidates}
        max_log = max(self._log_weights.values())
        raw = {c: math.exp(v - max_log) for c, v in self._log_weights.items()}
        z = sum(raw.values())
        return {c: v / z for c, v in raw.items()}

    def entropy(self) -> float:
        weights = self._weights()
        return -sum(p * math.log(p) for p in weights.values() if p > 0.0)

    def confidence(self) -> float:
        return max(self._weights().values())

    def best_hypothesis(self) -> Candidate | None:
        weights = self._weights()
        best = max(weights, key=weights.get)
        if weights[best] < self.confidence_threshold:
            return None
        return best

    # -- attention --------------------------------------------------------

    def select_attention(self, pressure: float = 0.0, rng: random.Random | None = None) -> list[int]:
        if rng is None:
            rng = random.Random()
        effective_m = max(self.k_rel, int(self.m * (1.0 - pressure)))
        effective_m = min(self.m, self.K, effective_m)

        if self.ablate_posterior:
            chosen = tuple(rng.sample(range(self.K), self.k_rel))
        else:
            chosen = self._sample_candidate(rng)

        selected = list(chosen)
        while len(selected) < effective_m:
            selected.append(self._next_filler(selected, rng))
        for i in selected:
            self._cue_counts[i] += 1
        return sorted(selected)

    def _sample_candidate(self, rng: random.Random) -> Candidate:
        weights = self._weights()
        if self._reframing_steps > 0 or self.confidence() < self.confidence_threshold:
            total = sum(weights.values())
            mark = rng.random() * total
            acc = 0.0
            for candidate, weight in weights.items():
                acc += weight
                if acc >= mark:
                    return candidate
        best = max(weights, key=weights.get)
        return best

    def _next_filler(self, selected: list[int], rng: random.Random) -> int:
        selected_set = set(selected)
        weights = self._weights()
        best_i: int | None = None
        best_score = float("-inf")
        for i in range(self.K):
            if i in selected_set:
                continue
            inclusion = sum(p for c, p in weights.items() if i in c)
            uncertainty = inclusion * (1.0 - inclusion)
            novelty = 1.0 / (1.0 + self._cue_counts[i])
            score = uncertainty + 0.05 * novelty + rng.random() * 1e-9
            if score > best_score:
                best_i = i
                best_score = score
        if best_i is None:
            raise RuntimeError("no filler cue available")
        return best_i

    # -- learning ---------------------------------------------------------

    def update(
        self,
        cues: tuple[int, ...],
        attended: list[int],
        action: int,
        reward: float,
        prediction_before: Mapping[Candidate, float],
    ) -> None:
        del cues, action  # prediction_before already carries model-conditioned evidence.
        if self.ablate_posterior:
            return
        attended_set = set(attended)
        covered = [c for c in self.candidates if set(c).issubset(attended_set)]
        if not covered:
            return

        errors: dict[Candidate, float] = {}
        for candidate in covered:
            pred = prediction_before.get(candidate, 0.0)
            err = abs(reward - pred)
            errors[candidate] = err
            self._error_ema[candidate] += self.lr * (err - self._error_ema[candidate])

        mean_error = sum(errors.values()) / len(errors)
        for candidate, err in errors.items():
            self._log_weights[candidate] += self.score_lr * (mean_error - err)

        self._center_log_weights()
        if self._reframing_steps > 0:
            self._reframing_steps -= 1

    def on_surprise(self, surprise: float) -> None:
        if self.ablate_posterior:
            return
        if surprise < self.surprise_threshold:
            return
        for candidate in self.candidates:
            self._log_weights[candidate] *= self.reset_decay
        self._reframing_steps = max(self._reframing_steps, self.K // self.m)
        self._center_log_weights()

    def _center_log_weights(self) -> None:
        mean = sum(self._log_weights.values()) / len(self._log_weights)
        for candidate in self.candidates:
            self._log_weights[candidate] -= mean
