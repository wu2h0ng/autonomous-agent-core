from __future__ import annotations

from dataclasses import dataclass, field

from .world_model import ActionOutcomeModel


@dataclass
class ResidualCalibrator:
    """Subject-side uncertainty recalibration from standardized residuals.

    ADR-0031/PREDICTION 1 tests whether a belief-channel self-calibrator can beat
    the frozen G10 gate by a decisive independent margin. This object writes only
    ``model.uncertainty[action]`` after the subject's native ``model.update`` has
    run. It never sees the shell, policy, organ advice, or action candidates.
    """

    n_actions: int
    lambda_: float
    eta: float
    min_scale: float = 0.5
    max_scale: float = 2.0
    eps: float = 1e-9
    ewma_z: list[float] = field(default_factory=list)
    counts: list[int] = field(default_factory=list)
    last_scale: float = 1.0

    def __post_init__(self) -> None:
        if self.n_actions <= 0:
            raise ValueError("n_actions must be positive")
        if not 0.0 <= self.lambda_ <= 1.0:
            raise ValueError("lambda_ must be in [0, 1]")
        if not 0.0 <= self.eta <= 1.0:
            raise ValueError("eta must be in [0, 1]")
        if not 0.0 < self.min_scale <= 1.0 <= self.max_scale:
            raise ValueError("scale bounds must satisfy 0 < min <= 1 <= max")
        if self.eps <= 0.0:
            raise ValueError("eps must be positive")
        if not self.ewma_z:
            self.ewma_z = [1.0] * self.n_actions
        if not self.counts:
            self.counts = [0] * self.n_actions
        if len(self.ewma_z) != self.n_actions or len(self.counts) != self.n_actions:
            raise ValueError("state length must match n_actions")

    def after_update(
        self,
        model: ActionOutcomeModel,
        *,
        action: int,
        prior_uncertainty: float,
    ) -> float:
        """Recalibrate ``model.uncertainty[action]`` after native model update.

        ``prior_uncertainty`` is the model's claimed uncertainty before observing
        reward. The standardized residual asks whether that claim was calibrated.
        The first observation per action records the empirical z but applies an
        identity scale, preventing a convenient initial uncertainty deflation.
        """
        if action < 0 or action >= self.n_actions:
            raise IndexError("action out of range")
        if model.n_actions != self.n_actions:
            raise ValueError("model.n_actions does not match calibrator")

        z = model.last_surprise / max(self.eps, prior_uncertainty)
        if self.counts[action] == 0:
            self.ewma_z[action] = z
            self.counts[action] = 1
            self.last_scale = 1.0
            return self.last_scale

        self.ewma_z[action] = (1.0 - self.lambda_) * self.ewma_z[action] + self.lambda_ * z
        scale = max(self.min_scale, min(self.max_scale, self.ewma_z[action]))
        adjustment = 1.0 + self.eta * (scale - 1.0)
        model.uncertainty[action] = max(0.0, model.uncertainty[action] * adjustment)
        self.counts[action] += 1
        self.last_scale = scale
        return scale
