from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class RelevanceField:
    """Opponent-process control of the explore/exploit balance.

    Two opposing pulls:
      - surprise (recent prediction error) + residual uncertainty -> EXPLORE
        (re-frame what is relevant);
      - budget pressure, tempered by model confidence -> EXPLOIT (feed now).

    The output :attr:`explore_drive` (0..1) modulates the policy's epistemic
    weight and selection temperature. When the world's rules change, surprise
    spikes and the field swings to explore — this is the re-framing mechanism.
    """

    explore_drive: float = 0.5
    inertia: float = 0.5
    surprise_gain: float = 2.0

    def update(
        self, surprise: float, pressure: float, mean_uncertainty: float
    ) -> float:
        explore_pull = self.surprise_gain * surprise + mean_uncertainty
        exploit_pull = pressure * (1.0 - min(1.0, mean_uncertainty))
        raw = max(-30.0, min(30.0, explore_pull - exploit_pull))
        target = 1.0 / (1.0 + math.exp(-raw))
        self.explore_drive = (
            self.inertia * self.explore_drive + (1 - self.inertia) * target
        )
        return self.explore_drive
