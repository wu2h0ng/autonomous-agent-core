"""O2 adaptive hazard-estimator organ (T-P4.3, ADR-0016; memo §3).

Same shape as O1 (surprise-spike -> JOINT belief reset: decay mu + reset
uncertainty toward prior), but the reset aggressiveness and the spike threshold
are ADAPTED from an online estimate of the regime-shift hazard, instead of being
fixed. This is the only thing O2 adds over O1 — the "learning" is learning how
fast the world changes and tuning the forgetting accordingly.

Hazard estimate tau_hat = EMA of detected inter-shift intervals:
  - frequent shifts (small tau_hat) -> aggressive reset, sensitive threshold
  - rare shifts   (large tau_hat) -> conservative reset, high threshold
    (don't over-reset on mere noise between rare shifts)

Design property (intentional): at the mid hazard tau_hat ~= k_ref_tau, O2's
reset_strength and spike_k collapse to O1's FROZEN values, so O2 == O1 at
average hazard and differs only by ADAPTING in fast/slow epochs. This isolates
the value of adaptation per se — exactly what G5-2 (O2 < O1) tests.

Belief-only (imports no policy/shell). Constants here are design-set; they must
be FROZEN via a disjoint-seed calibration scan before the G5 r-final (T-P4.4),
mirroring O1 — do not retune after seeing G5.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .prior_organ import BeliefSnapshot, OrganAdvice


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


@dataclass
class AdaptiveHazardOrgan:
    ema_lambda: float = 0.1
    warmup: int = 20
    # hazard estimate
    tau_init: float = 60.0
    tau_lambda: float = 0.3
    # reset_strength = clip(rs_c / tau_hat): at tau_hat=60 -> 0.5 (== O1 frozen)
    rs_c: float = 30.0
    rs_min: float = 0.3
    rs_max: float = 1.5
    # spike_k = clip(k_base * tau_hat / k_ref_tau): at tau_hat=60 -> 1.5 (== O1 frozen)
    k_base: float = 1.5
    k_ref_tau: float = 60.0
    k_min: float = 1.0
    k_max: float = 3.0
    mu_decay: float = 0.6
    prior_uncertainty: float = 1.0
    weight: float = 0.5

    _mean: float = 0.0
    _mean_sq: float = 0.0
    _seen: int = 0
    _step: int = 0
    _last_shift_step: int | None = None
    _tau_hat: float = 0.0
    # observability for tests / audit (last adapted values)
    _last_reset_strength: float = 0.0
    _last_spike_k: float = 0.0

    def __post_init__(self) -> None:
        self._tau_hat = self.tau_init
        self._last_spike_k = self.k_base

    def _accumulate(self, s: float) -> None:
        self._mean = (1 - self.ema_lambda) * self._mean + self.ema_lambda * s
        self._mean_sq = (1 - self.ema_lambda) * self._mean_sq + self.ema_lambda * s * s
        self._seen += 1

    @property
    def tau_hat(self) -> float:
        return self._tau_hat

    def advise(
        self, situation: Mapping[str, Any], belief_readonly: BeliefSnapshot
    ) -> OrganAdvice:
        s = belief_readonly.last_surprise
        self._step += 1
        if self._seen < self.warmup:
            self._accumulate(s)
            return OrganAdvice()
        var = max(0.0, self._mean_sq - self._mean * self._mean)
        std = var**0.5
        # Threshold adapts to hazard: rarer shifts -> higher k (more conservative).
        spike_k = _clip(self.k_base * self._tau_hat / self.k_ref_tau, self.k_min, self.k_max)
        self._last_spike_k = spike_k
        spike = s > self._mean + spike_k * std
        self._accumulate(s)
        if not spike:
            return OrganAdvice()
        # Update the hazard estimate from the observed inter-shift interval.
        if self._last_shift_step is not None:
            interval = self._step - self._last_shift_step
            self._tau_hat = (1 - self.tau_lambda) * self._tau_hat + self.tau_lambda * interval
        self._last_shift_step = self._step
        # Reset aggressiveness adapts to hazard: frequent shifts -> stronger reset.
        reset_strength = _clip(self.rs_c / self._tau_hat, self.rs_min, self.rs_max)
        self._last_reset_strength = reset_strength
        n = belief_readonly.n_actions
        belief_delta = {a: -self.mu_decay * belief_readonly.mu[a] for a in range(n)}
        uncertainty_delta = {
            a: reset_strength * (self.prior_uncertainty - belief_readonly.uncertainty[a])
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
        self._step = 0
        self._last_shift_step = None
        self._tau_hat = self.tau_init
        self._last_reset_strength = 0.0
        self._last_spike_k = self.k_base
