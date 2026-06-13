"""O4 Bayesian latent-regime posterior tracker (G7, ADR-0020).

Belief-only adviser with posterior tracking and information-directed epistemic
shaping. Imports no policy or shell surfaces.

Mechanism (what O1/O2 cannot do):
  - Maintain a log posterior over learned regime prototypes using Gaussian
    observation likelihoods, continuously updated each step.
  - On detected shift, finalise the just-ended regime into a prototype library
    and reset the posterior with a transition prior that down-weights the
    departed prototype (exploiting learnable recurrence structure).
  - Emit confidence-weighted belief deltas every post-shift step (continuous
    injection, not one-shot like O2).
  - While confidence is low, emit information-directed uncertainty deltas
    proportional to posterior-weighted prototype disagreement, raising epistemic
    salience on actions that best disambiguate plausible regimes.

Must not read regime_index from situation(), even though StructuredRegimeEnv
exposes it for scoring/debug.

Params marked FROZEN are set via experiments/latent_regime_g7.py calibrate on
disjoint seeds 200..219. Do not retune after seeing G7 r-final.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from .prior_organ import BeliefSnapshot, OrganAdvice


def _log_sum_exp(xs: list[float]) -> float:
    m = max(xs)
    if m == float("-inf"):
        return float("-inf")
    return m + math.log(sum(math.exp(x - m) for x in xs))


def _softmax_weights(log_posts: list[float]) -> list[float]:
    lse = _log_sum_exp(log_posts)
    return [math.exp(lp - lse) for lp in log_posts]


@dataclass
class LatentRegimeOrgan:
    # Surprise detection (same EMA shape as O1/O2; no privileged detector)
    ema_lambda: float = 0.1
    warmup: int = 20
    spike_k: float = 1.5

    # Gaussian likelihood
    # FROZEN via experiments/latent_regime_g7.py calibrate (2026-06-13, seeds 200-219).
    sigma: float = 0.3
    unknown_sigma: float = 2.0

    # Injection
    inject_weight: float = 0.85
    max_belief_delta: float = 5.0

    # Information-directed shaping
    info_weight: float = 0.3
    probe_confidence: float = 0.5

    # Prototype library
    merge_threshold: float = 1.0
    min_finalise_obs: int = 3

    # Posterior
    departed_penalty: float = 1.0
    min_posterior_obs: int = 2

    # Ablation control flags (P1-T2). Default True = full O4 behaviour.
    continuous_inject: bool = True
    bayesian_update: bool = True

    # -- internal state --
    _mean: float = 0.0
    _mean_sq: float = 0.0
    _seen: int = 0

    _prototypes: list[list[float]] = field(default_factory=list)
    _proto_counts: list[int] = field(default_factory=list)

    _obs_sum: dict[int, float] = field(default_factory=dict)
    _obs_cnt: dict[int, int] = field(default_factory=dict)
    _since_shift: int = 10_000

    _log_post: list[float] = field(default_factory=list)

    _last_best_proto: int = -1
    _last_confidence: float = 0.0
    _posterior_active: bool = False
    _ablation_injected: bool = False

    # -- helpers ---------------------------------------------------------------

    def _accumulate(self, s: float) -> None:
        self._mean = (1 - self.ema_lambda) * self._mean + self.ema_lambda * s
        self._mean_sq = (
            (1 - self.ema_lambda) * self._mean_sq + self.ema_lambda * s * s
        )
        self._seen += 1

    def _current_vector(self) -> dict[int, float]:
        return {a: self._obs_sum[a] / self._obs_cnt[a]
                for a in self._obs_cnt if self._obs_cnt[a] > 0}

    def _append_prototype(self, vec: dict[int, float], n_actions: int) -> None:
        mean_r = sum(vec.values()) / max(1, len(vec))
        full = [vec.get(a, mean_r) for a in range(n_actions)]
        self._prototypes.append(full)
        self._proto_counts.append(1)

    def _reset_posterior(self, departed_index: int | None) -> None:
        n = len(self._prototypes)
        if n == 0:
            self._log_post = []
            self._posterior_active = False
            return
        self._log_post = [0.0] * n
        if departed_index is not None and 0 <= departed_index < n:
            self._log_post[departed_index] -= self.departed_penalty
        self._normalise_posterior()
        self._posterior_active = True

    def _normalise_posterior(self) -> None:
        if not self._log_post:
            return
        lse = _log_sum_exp(self._log_post)
        self._log_post = [lp - lse for lp in self._log_post]

    def _update_likelihood(self, action: int, reward: float) -> None:
        if not self._log_post:
            return
        inv = 1.0 / (self.sigma ** 2)
        for k, proto in enumerate(self._prototypes):
            diff = reward - proto[action]
            self._log_post[k] += -0.5 * diff * diff * inv
        self._normalise_posterior()

    def _posterior_mean_reward(self, n_actions: int) -> list[float]:
        if not self._prototypes:
            return [0.0] * n_actions
        w = _softmax_weights(self._log_post)
        return [
            sum(w[k] * self._prototypes[k][a]
                for k in range(len(self._prototypes)))
            for a in range(n_actions)
        ]

    def _confidence(self) -> float:
        if len(self._log_post) < 2:
            return 1.0 if self._log_post else 0.0
        sorted_lp = sorted(self._log_post, reverse=True)
        return min(1.0, max(0.0, sorted_lp[0] - sorted_lp[1]))

    def _disagreement(self, n_actions: int) -> list[float]:
        if not self._prototypes:
            return [0.0] * n_actions
        w = _softmax_weights(self._log_post)
        result = []
        for a in range(n_actions):
            mean = sum(w[k] * self._prototypes[k][a]
                       for k in range(len(self._prototypes)))
            var = sum(w[k] * (self._prototypes[k][a] - mean) ** 2
                      for k in range(len(self._prototypes)))
            result.append(var ** 0.5)
        return result

    def _finalise_and_match(self, n_actions: int) -> int:
        """Finalise the just-ended regime; return its prototype index or -1."""
        vec = self._current_vector()
        if not vec or len(vec) < self.min_finalise_obs:
            return -1
        best_i, best_d = -1, float("inf")
        for i, proto in enumerate(self._prototypes):
            overlap = sum(1 for a in vec)
            if overlap < 1:
                continue
            d = sum((proto[a] - vec[a]) ** 2 for a in vec) / len(vec)
            if d < best_d:
                best_i, best_d = i, d
        if best_i >= 0 and best_d < self.merge_threshold:
            c = self._proto_counts[best_i]
            proto = self._prototypes[best_i]
            for a in vec:
                proto[a] = (proto[a] * c + vec[a]) / (c + 1)
            self._proto_counts[best_i] = c + 1
            return best_i
        self._append_prototype(vec, n_actions)
        return len(self._prototypes) - 1

    # -- main -----------------------------------------------------------------

    def advise(
        self,
        situation: Mapping[str, Any],
        belief_readonly: BeliefSnapshot,
    ) -> OrganAdvice:
        la = situation.get("last_action")
        lr = situation.get("last_reward")
        if isinstance(la, int) and lr is not None:
            self._obs_sum[la] = self._obs_sum.get(la, 0.0) + float(lr)
            self._obs_cnt[la] = self._obs_cnt.get(la, 0) + 1

        s = belief_readonly.last_surprise
        n = belief_readonly.n_actions

        if self._seen < self.warmup:
            self._accumulate(s)
            self._since_shift += 1
            return OrganAdvice()

        var = max(0.0, self._mean_sq - self._mean * self._mean)
        spike = s > self._mean + self.spike_k * var ** 0.5
        self._accumulate(s)
        self._since_shift += 1

        if spike:
            departed = self._finalise_and_match(n)
            self._obs_sum, self._obs_cnt = {}, {}
            self._since_shift = 0
            self._ablation_injected = False
            self._reset_posterior(departed_index=departed)
            belief_delta = {
                a: -belief_readonly.mu[a] for a in range(n)
            }
            uncertainty_delta = {
                a: 1.0 - belief_readonly.uncertainty[a] for a in range(n)
            }
            return OrganAdvice(
                belief_delta=belief_delta,
                uncertainty_delta=uncertainty_delta,
                uncertainty=0.5,
            )

        if self.bayesian_update and isinstance(la, int) and lr is not None and self._log_post:
            self._update_likelihood(la, float(lr))

        if not self.continuous_inject:
            if self._ablation_injected:
                return OrganAdvice()
            self._ablation_injected = True

        if not self._prototypes or not self._log_post:
            return OrganAdvice()

        if (not self._posterior_active
                and len(self._obs_cnt) < self.min_posterior_obs):
            return OrganAdvice()

        self._last_confidence = self._confidence()
        pmr = self._posterior_mean_reward(n)

        best_k = max(range(len(self._log_post)), key=lambda k: self._log_post[k])
        self._last_best_proto = best_k

        belief_delta: dict[int, float] = {}
        for a in range(n):
            raw = pmr[a] - belief_readonly.mu[a]
            clamped = max(-self.max_belief_delta, min(self.max_belief_delta, raw))
            belief_delta[a] = clamped

        uncertainty_delta: dict[int, float] = {}
        if self._last_confidence < self.probe_confidence and self.info_weight > 0:
            dis = self._disagreement(n)
            max_d = max(dis) if dis else 0.0
            if max_d > 0:
                for a in range(n):
                    uncertainty_delta[a] = self.info_weight * dis[a] / max_d

        # Merge weight: non-zero if either channel has content.
        has_belief = self.inject_weight > 0 and self._last_confidence > 0
        has_info = bool(uncertainty_delta) and self.info_weight > 0
        if has_belief and has_info:
            uncertainty = min(
                1.0,
                max(
                    self.inject_weight * self._last_confidence,
                    self.info_weight,
                ),
            )
        elif has_belief:
            uncertainty = min(1.0, self.inject_weight * self._last_confidence)
        elif has_info:
            uncertainty = min(1.0, self.info_weight)
        else:
            uncertainty = 0.0

        return OrganAdvice(
            belief_delta=belief_delta,
            uncertainty_delta=uncertainty_delta,
            uncertainty=uncertainty,
        )

    def reset(self) -> None:
        self._mean = self._mean_sq = 0.0
        self._seen = 0
        self._prototypes, self._proto_counts = [], []
        self._obs_sum, self._obs_cnt = {}, {}
        self._since_shift = 10_000
        self._log_post = []
        self._last_best_proto = -1
        self._last_confidence = 0.0
        self._posterior_active = False
        self._ablation_injected = False
