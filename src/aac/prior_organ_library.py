"""O2-structured: regime-library organ that exploits recurring structure
(T-P4.x.2, ADR-0017). Belief-only adviser; imports no policy/shell.

Mechanism (the thing a cheap reset CANNOT do):
  - From (action, reward) observations (read off situation()), maintain a running
    per-action estimate of the CURRENT regime.
  - On a surprise spike (shift): finalise the just-ended regime estimate and fold
    it into a learned LIBRARY of prototypes (merge with the nearest prototype if
    close, else add a new one); then re-explore (a small reset).
  - A few observations into the new regime, match the partial estimate to the
    nearest prototype; if confident, RECOGNISE the recurring regime and INJECT
    its known reward vector as a belief_delta — jumping mu toward the recognised
    values instead of re-learning from scratch.

It can only help where regimes recur (structure). On a structure-free env it
degenerates to a reset (no prototype ever matches well). The organ still only
OUTPUTS belief advice (C6) and never touches policy/shell (C7).

Match params are FROZEN via experiments/structured_g6a_calibration.py on
disjoint seeds; do not retune after seeing G6a.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .prior_organ import BeliefSnapshot, OrganAdvice


@dataclass
class RegimeLibraryOrgan:
    ema_lambda: float = 0.1
    warmup: int = 20
    spike_k: float = 1.5
    # reset emitted on a freshly detected shift (re-explore to gather evidence)
    reset_strength: float = 0.5
    mu_decay: float = 0.6
    prior_uncertainty: float = 1.0
    reset_weight: float = 0.5
    # recognition / injection
    min_obs: int = 4          # min distinct actions observed before matching
    # FROZEN via experiments/structured_g6a.py calibrate (2026-06-13, seeds 200-204).
    match_threshold: float = 0.5  # max mean-sq distance (on overlap) to recognise
    inject_weight: float = 0.85   # how hard to jump mu toward the prototype
    merge_threshold: float = 1.0  # distance below which a finalised regime merges

    _mean: float = 0.0
    _mean_sq: float = 0.0
    _seen: int = 0
    _prototypes: list[list[float]] = field(default_factory=list)
    _proto_counts: list[int] = field(default_factory=list)
    _sum: dict[int, float] = field(default_factory=dict)
    _cnt: dict[int, int] = field(default_factory=dict)
    _since_shift: int = 10_000
    _injected: bool = False

    # -- surprise scale -----------------------------------------------------
    def _accumulate(self, s: float) -> None:
        self._mean = (1 - self.ema_lambda) * self._mean + self.ema_lambda * s
        self._mean_sq = (1 - self.ema_lambda) * self._mean_sq + self.ema_lambda * s * s
        self._seen += 1

    def _current_vector(self) -> dict[int, float]:
        return {a: self._sum[a] / self._cnt[a] for a in self._cnt if self._cnt[a] > 0}

    def _distance(self, proto: list[float], vec: dict[int, float]) -> tuple[float, int]:
        if not vec:
            return float("inf"), 0
        d = sum((proto[a] - vec[a]) ** 2 for a in vec) / len(vec)
        return d, len(vec)

    def _nearest(self, vec: dict[int, float]) -> tuple[int, float]:
        best_i, best_d = -1, float("inf")
        for i, proto in enumerate(self._prototypes):
            d, overlap = self._distance(proto, vec)
            if overlap >= 1 and d < best_d:
                best_i, best_d = i, d
        return best_i, best_d

    def _finalise_regime(self, n_actions: int) -> None:
        vec = self._current_vector()
        if not vec:
            return
        i, d = self._nearest(vec)
        if i >= 0 and d < self.merge_threshold:
            proto, c = self._prototypes[i], self._proto_counts[i]
            for a in vec:  # incremental mean toward the observed values
                proto[a] = (proto[a] * c + vec[a]) / (c + 1)
            self._proto_counts[i] = c + 1
        else:
            full = [vec.get(a, 0.0) for a in range(n_actions)]
            self._prototypes.append(full)
            self._proto_counts.append(1)

    # -- main ---------------------------------------------------------------
    def advise(
        self, situation: Mapping[str, Any], belief_readonly: BeliefSnapshot
    ) -> OrganAdvice:
        # Fold in the previous step's observation (read-only; output stays belief).
        la, lr = situation.get("last_action"), situation.get("last_reward")
        if isinstance(la, int) and lr is not None:
            self._sum[la] = self._sum.get(la, 0.0) + float(lr)
            self._cnt[la] = self._cnt.get(la, 0) + 1

        s = belief_readonly.last_surprise
        n = belief_readonly.n_actions
        if self._seen < self.warmup:
            self._accumulate(s)
            self._since_shift += 1
            return OrganAdvice()
        var = max(0.0, self._mean_sq - self._mean * self._mean)
        spike = s > self._mean + self.spike_k * var**0.5
        self._accumulate(s)
        self._since_shift += 1

        if spike:
            self._finalise_regime(n)
            self._sum, self._cnt = {}, {}
            self._since_shift = 0
            self._injected = False
            # re-explore so we can observe the new regime
            return OrganAdvice(
                belief_delta={a: -self.mu_decay * belief_readonly.mu[a] for a in range(n)},
                uncertainty_delta={
                    a: self.reset_strength * (self.prior_uncertainty - belief_readonly.uncertainty[a])
                    for a in range(n)
                },
                uncertainty=self.reset_weight,
            )

        # recognition + injection (once per regime)
        if not self._injected and self._since_shift >= self.min_obs and self._prototypes:
            vec = self._current_vector()
            if len(vec) >= self.min_obs:
                i, d = self._nearest(vec)
                if i >= 0 and d < self.match_threshold:
                    proto = self._prototypes[i]
                    self._injected = True
                    return OrganAdvice(
                        belief_delta={a: proto[a] - belief_readonly.mu[a] for a in range(n)},
                        uncertainty_delta={
                            a: -(belief_readonly.uncertainty[a]) * 0.7 for a in range(n)
                        },
                        uncertainty=self.inject_weight,
                    )
        return OrganAdvice()

    def reset(self) -> None:
        self._mean = self._mean_sq = 0.0
        self._seen = 0
        self._prototypes, self._proto_counts = [], []
        self._sum, self._cnt = {}, {}
        self._since_shift = 10_000
        self._injected = False
