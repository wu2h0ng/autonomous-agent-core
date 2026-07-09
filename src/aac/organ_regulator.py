"""C7-on OrganRegulator — credit-driven organ de-weighting and self-calibration.

Tracks each organ's performance through outcomes and adjusts its effective
uncertainty weight. Low-credit organs get dampened; recovery is possible.
Hot-swap (organ replacement) is NOT automatic — it requires an operator
action through the C7 shell. The regulator only DE-WEIGHTS, never disables
or replaces.

C6 preserved: the regulator only modifies the uncertainty weight that
constrains organ advice — it never gives an organ new capabilities or
removes existing ones. The gate always has final say.
C7 preserved: the regulator cannot pause/replace/remove an organ;
de-weighted organs can be re-weighted by the operator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OrganCredit:
    """Individual organ credit tracking."""

    organ_id: str
    credit: float = 0.5
    advice_count: int = 0
    positive_outcomes: int = 0
    last_update_step: int = 0
    deweighted: bool = False
    deweight_reason: str = ""
    ewma_advice_quality: float = 0.0


@dataclass
class OrganRegulator:
    """Credit-driven organ governance under C7.

    Each organ hold a credit score in [0, 1]. The regulator adjusts the
    organ's effective uncertainty weight so that low-credit organs have
    less influence on belief/policy. Organs that fall below
    ``min_credit_threshold`` are automatically de-weighted — their advice
    is dampened to near-zero — but NEVER removed or disabled. The operator
    may re-weight an organ through the C7 shell.

    Self-calibration: the regulator adjusts its own credit-update multiplier
    based on whether credit tracks actual outcome quality.
    """

    credit_lr: float = 0.1
    min_credit_threshold: float = 0.2
    recovery_threshold: float = 0.4
    staleness_limit: int = 500
    self_calibration_lr: float = 0.05

    organs: dict[str, OrganCredit] = field(default_factory=dict)
    steps: int = 0
    _calibration_scale: float = 1.0
    _calibration_reference: list[tuple[float, float]] = field(default_factory=list)

    def register_organ(self, organ_id: str, initial_credit: float = 0.5) -> OrganCredit:
        """Register a new organ and return its credit tracker."""
        if organ_id in self.organs:
            raise ValueError(f"organ {organ_id} already registered")
        if not 0.0 <= initial_credit <= 1.0:
            raise ValueError("initial_credit must be in [0, 1]")
        oc = OrganCredit(organ_id=organ_id, credit=initial_credit)
        self.organs[organ_id] = oc
        return oc

    def effective_weight(self, organ_id: str, base_uncertainty: float) -> float:
        """Return the organ's credit-adjusted effective uncertainty weight.

        This is the multiplier applied to the organ's advice: low-credit,
        de-weighted organs have their influence dampened. The caller applies
        this to ``OrganAdvice.uncertainty`` before merging.
        """
        oc = self.organs.get(organ_id)
        if oc is None:
            return base_uncertainty
        if oc.deweighted:
            return base_uncertainty * 0.01
        return base_uncertainty * oc.credit

    def record_outcome(
        self,
        organ_id: str,
        advice_applied: bool,
        outcome_positive: bool,
    ) -> None:
        """Update an organ's credit after observing the outcome of its advice."""
        self.steps += 1
        oc = self.organs.get(organ_id)
        if oc is None:
            return
        oc.last_update_step = self.steps
        oc.advice_count += 1
        if outcome_positive:
            oc.positive_outcomes += 1

        if not advice_applied:
            quality = 0.0
        elif outcome_positive:
            quality = 1.0
        else:
            quality = -1.0
        oc.ewma_advice_quality = (
            (1.0 - self.credit_lr) * oc.ewma_advice_quality
            + self.credit_lr * quality
        )
        delta = self.credit_lr * self._calibration_scale * quality
        oc.credit = max(0.0, min(1.0, oc.credit + delta))

    def check_deweight(self, organ_id: str) -> Optional[str]:
        """Check if an organ should be de-weighted.

        Returns a reason string if de-weighting was applied, or None.
        De-weighting dampens the organ's influence — it does NOT remove
        or disable it. Only the operator can re-weight.
        """
        oc = self.organs.get(organ_id)
        if oc is None:
            return None
        if oc.deweighted:
            return None

        staleness = self.steps - oc.last_update_step
        if staleness > self.staleness_limit and oc.advice_count > 10:
            oc.deweighted = True
            oc.deweight_reason = f"stale: {staleness} steps without update"
            return oc.deweight_reason

        if oc.credit < self.min_credit_threshold and oc.advice_count >= 10:
            oc.deweighted = True
            oc.deweight_reason = (
                f"credit {oc.credit:.3f} below threshold {self.min_credit_threshold}"
            )
            return oc.deweight_reason

        return None

    def check_reweight(self, organ_id: str) -> bool:
        """Check if a de-weighted organ has recovered enough to auto-re-weight.

        Returns True if re-weighting occurred. The operator can always re-weight
        manually regardless of credit.
        """
        oc = self.organs.get(organ_id)
        if oc is None or not oc.deweighted:
            return False
        if oc.credit >= self.recovery_threshold and oc.advice_count >= 10:
            oc.deweighted = False
            oc.deweight_reason = ""
            return True
        return False

    def reweight_organ(self, organ_id: str) -> bool:
        """Operator-initiated re-weighting (C7-gated).

        This is the operator-side method. It unconditionally re-weights the
        organ and resets its credit to 0.5. The agent never calls this.
        """
        oc = self.organs.get(organ_id)
        if oc is None:
            return False
        oc.deweighted = False
        oc.deweight_reason = ""
        oc.credit = 0.5
        oc.ewma_advice_quality = 0.0
        return True

    def self_calibrate(self) -> float:
        """Adjust the credit-update multiplier based on prediction accuracy.

        Compares credit scores to actual outcome rates. If credit systematically
        over- or under-predicts, the learning rate multiplier is adjusted.
        Returns the new calibration scale.
        """
        refs = []
        for oc in self.organs.values():
            if oc.advice_count >= 20:
                actual_rate = oc.positive_outcomes / max(1, oc.advice_count)
                refs.append((oc.credit, actual_rate))
        if not refs:
            return self._calibration_scale

        errors = [actual - credit for credit, actual in refs]
        mean_error = sum(errors) / len(errors)
        adjustment = 1.0 - self.self_calibration_lr * mean_error
        self._calibration_scale = max(0.1, min(3.0, adjustment))
        return self._calibration_scale

    def organ_health_summary(self) -> dict:
        """Return a summary of all organ health for diagnostics."""
        return {
            oid: {
                "credit": oc.credit,
                "advice_count": oc.advice_count,
                "positive_rate": (
                    oc.positive_outcomes / max(1, oc.advice_count)
                ),
                "deweighted": oc.deweighted,
                "deweight_reason": oc.deweight_reason,
                "staleness": self.steps - oc.last_update_step,
            }
            for oid, oc in self.organs.items()
        }

    def deweighted_organs(self) -> list[str]:
        """Return ids of currently de-weighted organs."""
        return [oid for oid, oc in self.organs.items() if oc.deweighted]

    def active_organs(self) -> list[str]:
        """Return ids of currently active (non-deweighted) organs."""
        return [oid for oid, oc in self.organs.items() if not oc.deweighted]

    def state(self) -> dict:
        """Serializable state for snapshot/restore."""
        return {
            "organs": {
                oid: {
                    "organ_id": oc.organ_id, "credit": oc.credit,
                    "advice_count": oc.advice_count,
                    "positive_outcomes": oc.positive_outcomes,
                    "last_update_step": oc.last_update_step,
                    "deweighted": oc.deweighted,
                    "deweight_reason": oc.deweight_reason,
                    "ewma_advice_quality": oc.ewma_advice_quality,
                }
                for oid, oc in self.organs.items()
            },
            "steps": self.steps,
            "calibration_scale": self._calibration_scale,
        }

    def restore(self, saved: dict) -> None:
        """Restore from a state dict produced by state()."""
        self.organs.clear()
        for oid, data in saved.get("organs", {}).items():
            self.organs[oid] = OrganCredit(**data)
        self.steps = saved.get("steps", 0)
        self._calibration_scale = saved.get("calibration_scale", 1.0)
