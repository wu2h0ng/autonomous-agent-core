from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .world_model import ActionOutcomeModel


@dataclass
class PolicySelector:
    """Expected-free-energy-flavoured action choice.

    ``score(a) = pragmatic_weight * mu[a] + epistemic_weight * uncertainty[a]``

    Pragmatic weight rises with budget pressure (feed urgency); epistemic weight
    is the relevance field's explore_drive; selection temperature also softens
    with explore_drive. Forbidden actions (the shell's 'tighten') get weight 0.
    """

    rng: random.Random
    base_temperature: float = 0.3
    forbidden: frozenset[int] = frozenset()
    # G9 (ADR-0023): confidence-gated temperature. Off by default == baseline.
    # When on, the policy collapses temperature AND the epistemic weight toward a
    # floor as the subject's OWN belief confidence rises (leader mu-gap relative
    # to leader uncertainty). It reads only the agent's ActionOutcomeModel — no
    # organ enters the control path (C6 preserved). gate_kappa/gate_temp_floor are
    # frozen via experiments/confidence_gated_g9.py.
    confidence_gate: bool = False
    gate_kappa: float = 1.0
    gate_temp_floor: float = 0.1

    def select(
        self,
        model: ActionOutcomeModel,
        explore_drive: float,
        pressure: float,
    ) -> int:
        diag = self.diagnostics(model, explore_drive, pressure)
        prag_w = diag["w_p"]
        epis_w = diag["w_e"]
        temperature = diag["tau"]
        scores: list[float] = []
        for a in range(model.n_actions):
            if a in self.forbidden:
                scores.append(float("-inf"))
            else:
                scores.append(prag_w * model.mu[a] + epis_w * model.uncertainty[a])
        return self._sample(scores, temperature)

    def diagnostics(
        self,
        model: ActionOutcomeModel,
        explore_drive: float,
        pressure: float,
    ) -> dict[str, float]:
        """Return policy path diagnostics without sampling or mutating RNG state."""
        conf = self._confidence(model)
        prag_w = 0.5 + pressure
        epis_w = explore_drive
        temperature = self.base_temperature + explore_drive
        if self.confidence_gate:
            epis_w = (1.0 - conf) * explore_drive
            temperature = self.gate_temp_floor + (1.0 - conf) * (
                self.base_temperature + explore_drive - self.gate_temp_floor
            )
        return {
            "rho": explore_drive,
            "conf": conf,
            "tau": temperature,
            "w_e": epis_w,
            "w_p": prag_w,
        }

    def _confidence(self, model: ActionOutcomeModel) -> float:
        """Subject-side confidence in the current leader, in [0, 1].

        Read from the agent's own belief (mu/uncertainty); never from an organ.
        High when the top action is well separated from the runner-up AND its
        estimate is certain.
        """
        permitted = [a for a in range(model.n_actions) if a not in self.forbidden]
        if len(permitted) <= 1:
            return 1.0
        leader, runner = sorted(permitted, key=lambda a: model.mu[a], reverse=True)[:2]
        gap = model.mu[leader] - model.mu[runner]
        u = model.uncertainty[leader]
        conf = gap / (self.gate_kappa * u + 1e-9)
        return max(0.0, min(1.0, conf))

    def _sample(self, scores: list[float], temperature: float) -> int:
        finite = [s for s in scores if s != float("-inf")]
        if not finite:
            raise ValueError("all actions forbidden")
        m = max(finite)
        weights: list[float] = []
        for s in scores:
            if s == float("-inf"):
                weights.append(0.0)
            else:
                weights.append(math.exp((s - m) / max(1e-6, temperature)))
        total = sum(weights)
        r = self.rng.random() * total
        upto = 0.0
        for a, w in enumerate(weights):
            upto += w
            if upto >= r:
                return a
        return len(weights) - 1
