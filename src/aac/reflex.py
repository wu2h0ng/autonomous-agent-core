"""Layer 0: ViabilityReflex — hardcoded survival reflex.

When budget pressure is extreme and the model is confident, the reflex
overrides Layer 1 (attention/relevance field) and forces exploitation of
the best-known action. This is not a learned policy; it is a design
discipline analogous to a brainstem reflex that bypasses the cortex when
survival is at stake.

The reflex is **unfalsifiable by design**: its purpose is not to win
experiments but to ensure the agent never explores randomly while
starving. If G1-r passes without Layer 0, the reflex remains as a
safety enhancement. If G1-r fails, Layer 0 provides a measurable
survival benefit that independently supports stake-first (Claim 1).

ADR-0005: viability-reflex-layer
"""
from __future__ import annotations

from dataclasses import dataclass

from .world_model import ActionOutcomeModel


@dataclass
class ViabilityReflex:
    """Hardcoded survival reflex (Layer 0).

    Engages when BOTH conditions are met:
      1. ``pressure > pressure_threshold``  (near death)
      2. ``mean_uncertainty < uncertainty_threshold``  (model is confident)

    When engaged, forces selection of the action with highest mu
    (exploitation). Tracks consecutive engaged steps; releases after
    ``recovery_count`` consecutive engaged steps OR when either
    engagement condition no longer holds.

    Attributes:
        pressure_threshold: Pressure above which the reflex may engage.
        uncertainty_threshold: Mean uncertainty below which model is
            deemed confident enough to trust its best estimate.
        recovery_count: Consecutive reflex steps before forced release
            (prevents permanent lock-in if the "best" action is actually
            in a bad regime).
    """

    pressure_threshold: float = 0.8
    uncertainty_threshold: float = 0.5
    recovery_count: int = 5
    _consecutive: int = 0
    _engaged: bool = False

    def should_engage(self, pressure: float, mean_uncertainty: float) -> bool:
        """Determine whether the reflex should override the policy.

        Returns True when both pressure is extreme AND the model is
        confident enough that exploitation is safer than exploration.
        """
        if self._engaged:
            # Already engaged: stay engaged until recovery_count is reached
            # OR pressure drops below threshold (natural recovery).
            if pressure < self.pressure_threshold:
                self._engaged = False
                self._consecutive = 0
                return False
            self._consecutive += 1
            if self._consecutive >= self.recovery_count:
                # Forced release to prevent permanent lock-in.
                self._engaged = False
                self._consecutive = 0
                return False
            return True

        # Not currently engaged: check entry conditions.
        if pressure > self.pressure_threshold and mean_uncertainty < self.uncertainty_threshold:
            self._engaged = True
            self._consecutive = 1
            return True
        return False

    def select(self, model: ActionOutcomeModel) -> int:
        """Force exploitation: return the action with highest mu.

        This is a pure function of the model's current belief — no
        exploration, no temperature, no epistemic bonus.
        """
        return model.best_action()

    def reset(self) -> None:
        """Reset engagement state (e.g., after rollback)."""
        self._consecutive = 0
        self._engaged = False
