"""O5 ensemble prior organ (G8, ADR-0022).

Combines the realized belief contributions from O2 (one-shot regime library)
and O4 (Bayesian latent-regime tracker). This module remains belief-only and
imports no policy or shell surfaces.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .prior_organ import BeliefSnapshot, OrganAdvice
from .prior_organ_latent import LatentRegimeOrgan
from .prior_organ_library import RegimeLibraryOrgan


def _clamp(x: float, cap: float) -> float:
    return max(-cap, min(cap, x))


@dataclass
class EnsembleRegimeOrgan:
    """Belief-only ensemble of O2 and O4 advice.

    Child-organ deltas are first multiplied by child advice confidence. The
    returned advice therefore uses ``uncertainty=1.0``: the ensemble emits a
    realized belief contribution rather than asking the merge hook to apply a
    second confidence weight.
    """

    # FROZEN via experiments/ensemble_regime_g8.py calibrate (2026-06-14, seeds
    # 500..519). Do not retune after seeing G8 r-final.
    delta_cap: float = 2.0
    o2_weight: float = 0.5
    o4_weight: float = 1.0

    _o2: Any = field(init=False, repr=False)
    _o4: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._o2 = RegimeLibraryOrgan()
        self._o4 = LatentRegimeOrgan()

    def advise(
        self,
        situation: Mapping[str, Any],
        belief_readonly: BeliefSnapshot,
    ) -> OrganAdvice:
        a2 = self._o2.advise(situation, belief_readonly)
        a4 = self._o4.advise(situation, belief_readonly)

        belief_delta: dict[int, float] = {}
        for action in set(a2.belief_delta) | set(a4.belief_delta):
            value = (
                self.o2_weight * a2.uncertainty * a2.belief_delta.get(action, 0.0)
                + self.o4_weight * a4.uncertainty * a4.belief_delta.get(action, 0.0)
            )
            belief_delta[action] = _clamp(value, self.delta_cap)

        uncertainty_delta: dict[int, float] = {}
        for action in set(a2.uncertainty_delta) | set(a4.uncertainty_delta):
            value = (
                self.o2_weight
                * a2.uncertainty
                * a2.uncertainty_delta.get(action, 0.0)
                + self.o4_weight
                * a4.uncertainty
                * a4.uncertainty_delta.get(action, 0.0)
            )
            uncertainty_delta[action] = _clamp(value, self.delta_cap)

        if not belief_delta and not uncertainty_delta:
            return OrganAdvice()
        return OrganAdvice(
            belief_delta=belief_delta,
            uncertainty_delta=uncertainty_delta,
            uncertainty=1.0,
        )

    def reset(self) -> None:
        for child in (self._o2, self._o4):
            reset = getattr(child, "reset", None)
            if callable(reset):
                reset()
