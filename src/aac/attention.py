from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class AttentionField:
    """Attention-allocation replacement for v0 RelevanceField.

    Structural constraints (ADR-0002 §Decision-T2):

    1. Relevance = **attention allocation**: each cue carries an
       *information-power* estimate (EMA of conditional reward gap).
       Attention goes to the top-m cues; unattended cues receive a
       surprise-gated probing budget.
    2. **Exploitation is gated by model confidence, decoupled from
       hunger/pressure.**  A confident model exploits regardless of
       budget level.  (Fixes the v0 structural defect.)
    3. **Pressure only shrinks the attention budget** (high pressure →
       attend fewer, highest-IP cues).  Interoception modulates
       attention, not exploitation directly.

    v1.1 (ADR-0004): Surprise-triggered IP reset breaks the attention
    stickiness trap.  When sustained prediction error signals a regime
    shift, all IP estimates decay toward zero and a brief uniform
    exploration window ensures full cue coverage before IP-based
    selection resumes.

    Every score is derivable to essential variables (stake-first):
    information power = |E[r|c_i=1] − E[r|c_i=0]| (EMA).
    """

    K: int = 12
    m: int = 3
    lr: float = 0.2
    exploit_threshold: float = 0.5
    explore_drive: float = 0.5
    # v1.1 reset parameters (ADR-0004)
    noise_floor: float = 0.3
    reset_sigma: float = 2.5
    surprise_window: int = 20
    min_samples_for_reset: int = 5
    reset_cooldown: int = 15
    ip_decay: float = 0.2
    # Per-cue running estimates (EMA of E[reward | cue=1] and E[reward | cue=0])
    _reward_when_on: list[float] = field(default_factory=list)
    _reward_when_off: list[float] = field(default_factory=list)
    _count_on: list[int] = field(default_factory=list)
    _count_off: list[int] = field(default_factory=list)
    information_power: list[float] = field(default_factory=list)
    # v1.1 internal state
    _surprise_history: list[float] = field(default_factory=list)
    _step: int = 0
    _last_reset_step: int = -1000
    _steps_since_reset: int = 1000  # large = not in uniform window

    def __post_init__(self) -> None:
        if not self._reward_when_on:
            self._reward_when_on = [0.0] * self.K
        if not self._reward_when_off:
            self._reward_when_off = [0.0] * self.K
        if not self._count_on:
            self._count_on = [0] * self.K
        if not self._count_off:
            self._count_off = [0] * self.K
        if not self.information_power:
            self.information_power = [0.0] * self.K

    # -- learning ---------------------------------------------------------

    def update(
        self,
        reward: float,
        cue_values: tuple[int, ...],
        attended: list[int],
    ) -> None:
        """Update information-power estimates from an observation.

        Only attended cues are updated (unattended cues are invisible).
        """
        for i in attended:
            if cue_values[i] == 1:
                self._count_on[i] += 1
                self._reward_when_on[i] += self.lr * (
                    reward - self._reward_when_on[i]
                )
            else:
                self._count_off[i] += 1
                self._reward_when_off[i] += self.lr * (
                    reward - self._reward_when_off[i]
                )
            # Recompute IP for this cue
            if self._count_on[i] > 0 and self._count_off[i] > 0:
                self.information_power[i] = abs(
                    self._reward_when_on[i] - self._reward_when_off[i]
                )

    # -- surprise-triggered reset (ADR-0004 v1.1) -------------------------

    def on_surprise(self, surprise: float) -> None:
        """Feed a surprise signal from the world model.

        If surprise exceeds the dynamic threshold (sliding-window
        mean + reset_sigma * max(stdev, noise_floor)), all IP estimates
        decay toward zero and counts are cleared.  A cooldown prevents
        rapid successive resets.
        """
        self._surprise_history.append(surprise)
        if len(self._surprise_history) > self.surprise_window:
            self._surprise_history.pop(0)
        self._step += 1

        if len(self._surprise_history) < self.min_samples_for_reset:
            return
        if self._step - self._last_reset_step < self.reset_cooldown:
            return

        # Dynamic threshold
        n = len(self._surprise_history)
        mu = sum(self._surprise_history) / n
        var = sum((s - mu) ** 2 for s in self._surprise_history) / n
        sigma = math.sqrt(var)
        threshold = mu + self.reset_sigma * max(sigma, self.noise_floor)

        if surprise > threshold:
            self._do_reset()

    def _do_reset(self) -> None:
        """Decay IP estimates, clear counts, start uniform window."""
        for i in range(self.K):
            self.information_power[i] *= self.ip_decay
            self._reward_when_on[i] = 0.0
            self._reward_when_off[i] = 0.0
            self._count_on[i] = 0
            self._count_off[i] = 0
        self._last_reset_step = self._step
        self._steps_since_reset = 0

    @property
    def _uniform_window_steps(self) -> int:
        """Number of uniform-rotation steps after a reset (K / m)."""
        return max(1, self.K // max(1, self.m))

    # -- attention selection ----------------------------------------------

    def select_attention(self, pressure: float = 0.0) -> list[int]:
        """Return cue indices to attend.

        v1.1: Within the post-reset uniform window, returns a rotating
        slice that covers all K cues in K/m steps.  Outside the window,
        returns top-m by IP (pressure-shrunk as before).
        """
        # Post-reset uniform exploration window (ADR-0004)
        if self._steps_since_reset < self._uniform_window_steps:
            offset = (self._steps_since_reset * self.m) % self.K
            indices = [(offset + j) % self.K for j in range(min(self.m, self.K))]
            return indices

        effective_m = max(1, int(self.m * (1.0 - pressure)))
        effective_m = min(effective_m, self.m, self.K)
        ranked = sorted(
            range(self.K), key=lambda i: self.information_power[i], reverse=True
        )
        return ranked[:effective_m]

    # -- exploitation gate (decoupled from pressure) -----------------------

    def should_exploit(self, mean_uncertainty: float) -> bool:
        """True when the world model is confident enough to exploit.

        This is the structural fix for v0: exploitation is gated by
        *model confidence*, not by hunger/pressure.
        """
        return mean_uncertainty < self.exploit_threshold

    # -- backward compatibility with GridlessSurvival ----------------------

    def sync_explore_drive(self, mean_uncertainty: float) -> float:
        """Set explore_drive from the exploit gate for non-cue environments.

        When the model is uncertain → explore (high drive).
        When confident → exploit (low drive).
        This lets the Agent use AttentionField with GridlessSurvival
        as a drop-in replacement for RelevanceField.
        """
        if self.should_exploit(mean_uncertainty):
            self.explore_drive = 0.2  # low drive → exploit
        else:
            self.explore_drive = 0.8  # high drive → explore
        return self.explore_drive
