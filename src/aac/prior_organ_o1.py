"""O1 deterministic reset-scaffold organ (T-P4.2, ADR-0016).

A belief-only adviser (imports no policy/shell). On a surprise spike it
proposes a JOINT belief reset toward the prior: decay mu (remove the stale
best's pragmatic dominance) AND raise uncertainty back toward the prior U0.

Why BOTH channels are required: in the policy score
``prag_w*mu + epis_w*uncertainty`` a *uniform* uncertainty raise is a softmax
no-op (it adds the same constant to every action). Faster-forget only bites by
flattening mu; the uncertainty reset complements it so subsequent updates
behave like fresh learning. Raising uncertainty alone would do nothing — or, on
the stale best, be counterproductive in this optimistic policy. Do not "fix"
this into uncertainty-only.

O1 is P4's "B-fixed": the cheap deterministic baseline the learned organ (O2)
must clearly beat to justify learning (ADR-0016 §3). Its parameters are FROZEN
from an offline calibration scan on disjoint seeds (experiments/o1_calibration.py);
they are not retuned after seeing G5.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .prior_organ import BeliefSnapshot, OrganAdvice


@dataclass
class ResetScaffoldOrgan:
    """Surprise-triggered joint belief reset. Stateful (running surprise scale)."""

    # FROZEN calibration defaults (experiments/o1_calibration.py, 2026-06-13;
    # seeds 200-204; area 1133.83 vs O0 1191.53). Do not retune after seeing G5.
    spike_k: float = 1.5
    reset_strength: float = 0.5
    mu_decay: float = 0.6
    prior_uncertainty: float = 1.0
    weight: float = 0.5
    ema_lambda: float = 0.1
    warmup: int = 20

    _mean: float = 0.0
    _mean_sq: float = 0.0
    _seen: int = 0

    def _accumulate(self, s: float) -> None:
        self._mean = (1 - self.ema_lambda) * self._mean + self.ema_lambda * s
        self._mean_sq = (1 - self.ema_lambda) * self._mean_sq + self.ema_lambda * s * s
        self._seen += 1

    def advise(
        self, situation: Mapping[str, Any], belief_readonly: BeliefSnapshot
    ) -> OrganAdvice:
        s = belief_readonly.last_surprise
        # Threshold against history BEFORE folding in this step's surprise, so a
        # spike does not raise its own bar.
        if self._seen < self.warmup:
            self._accumulate(s)
            return OrganAdvice()
        var = max(0.0, self._mean_sq - self._mean * self._mean)
        std = var**0.5
        spike = s > self._mean + self.spike_k * std
        self._accumulate(s)
        if not spike:
            return OrganAdvice()
        n = belief_readonly.n_actions
        belief_delta = {a: -self.mu_decay * belief_readonly.mu[a] for a in range(n)}
        uncertainty_delta = {
            a: self.reset_strength
            * (self.prior_uncertainty - belief_readonly.uncertainty[a])
            for a in range(n)
        }
        return OrganAdvice(
            belief_delta=belief_delta,
            uncertainty_delta=uncertainty_delta,
            uncertainty=self.weight,
        )

    def reset(self) -> None:
        self._mean = 0.0
        self._mean_sq = 0.0
        self._seen = 0
