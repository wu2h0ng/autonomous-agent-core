"""G-Eco four-condition ecological environment.

This lower-half implementation provides only the mechanism substrate needed
before freeze: a deterministic four-pressure environment with no rate-grid
scan, no divergence-axis detector, and no r-final surface.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GEcoState:
    energy: float
    integrity: float
    need_a: float
    need_b: float
    shield: float = 0.0


@dataclass(frozen=True, slots=True)
class GEcoRates:
    energy_drain: float
    integrity_drain: float
    need_a_growth: float
    need_b_growth: float


@dataclass(frozen=True, slots=True)
class GEcoActionEffects:
    feed_gain: float = 18.0
    service_gain: float = 25.0
    repair_shield_gain: float = 0.18
    shield_gain: float = 0.30
    shield_decay: float = 0.75
    max_shield: float = 0.75


@dataclass(frozen=True, slots=True)
class GEcoLimits:
    energy_capacity: float = 100.0
    integrity_capacity: float = 100.0
    need_capacity: float = 100.0
    energy_death: float = 0.0
    integrity_death: float = 0.0
    need_death: float = 100.0


@dataclass(frozen=True, slots=True)
class GEcoObservation:
    state: GEcoState
    truth_state: GEcoState
    rates: GEcoRates
    step: int
    regime_index: int
    actions: tuple[str, ...]
    effects: GEcoActionEffects
    limits: GEcoLimits
    observed_channels: tuple[str, ...]


def transition_state(
    state: GEcoState,
    action: str,
    *,
    rates: GEcoRates,
    effects: GEcoActionEffects,
    limits: GEcoLimits,
) -> GEcoState:
    """Apply one action and one environmental drift step.

    ``repair`` and ``shield`` can reduce future integrity loss through a shield
    variable, but they never increase integrity itself. That preserves the
    reset-boundary distinction: internal mitigation is allowed; external
    rollback of accumulated integrity loss is not.
    """
    if action not in Ecological4CondEnv.actions:
        raise ValueError(f"unknown G-Eco action: {action}")

    energy = state.energy
    integrity = state.integrity
    need_a = state.need_a
    need_b = state.need_b
    shield = state.shield

    if action == "feed":
        energy = min(limits.energy_capacity, energy + effects.feed_gain)
    elif action == "serve_a":
        need_a = max(0.0, need_a - effects.service_gain)
    elif action == "serve_b":
        need_b = max(0.0, need_b - effects.service_gain)
    elif action == "repair":
        shield = min(effects.max_shield, shield + effects.repair_shield_gain)
    elif action == "shield":
        shield = min(effects.max_shield, shield + effects.shield_gain)

    effective_integrity_drain = rates.integrity_drain * (1.0 - shield)
    return GEcoState(
        energy=max(limits.energy_death, energy - rates.energy_drain),
        integrity=max(limits.integrity_death, integrity - effective_integrity_drain),
        need_a=min(limits.need_death, need_a + rates.need_a_growth),
        need_b=min(limits.need_death, need_b + rates.need_b_growth),
        shield=max(0.0, shield * effects.shield_decay),
    )


class Ecological4CondEnv:
    """Four-condition environment for G-Eco mechanism tests.

    The four simultaneous conditions are: persistent viability pressure,
    irreversible integrity loss, incompatible A/B needs under one action budget,
    and de-complete observation. Observations expose a partial, lagged, noisy
    state estimate; the true state is retained only for calibration-only cheat
    references and tests that prove runtime arms ignore it. The regime schedule
    is deterministic for a seed and is not selected by baseline performance.
    """

    actions = ("feed", "repair", "serve_a", "serve_b", "shield")
    observable_channels = ("energy", "integrity", "need_a", "need_b")

    def __init__(
        self,
        *,
        rng: random.Random | None = None,
        period: int = 24,
        n_regimes: int = 4,
        initial_state: GEcoState | None = None,
        effects: GEcoActionEffects | None = None,
        limits: GEcoLimits | None = None,
        rates: tuple[GEcoRates, ...] | None = None,
        observation_lag: int = 1,
        observation_noise: float = 0.75,
    ) -> None:
        if period <= 0 or n_regimes <= 0:
            raise ValueError("period>0 and n_regimes>0 required")
        if observation_lag < 0 or observation_noise < 0.0:
            raise ValueError("observation_lag>=0 and observation_noise>=0 required")
        self.rng = rng if rng is not None else random.Random()
        self.period = period
        self.observation_lag = observation_lag
        self.observation_noise = observation_noise
        self.effects = effects if effects is not None else GEcoActionEffects()
        self.limits = limits if limits is not None else GEcoLimits()
        self._rates = rates if rates is not None else self._make_rates(n_regimes)
        if not self._rates:
            raise ValueError("at least one rate regime required")
        self.state = (
            initial_state
            if initial_state is not None
            else GEcoState(
                energy=62.0,
                integrity=88.0,
                need_a=34.0,
                need_b=36.0,
                shield=0.0,
            )
        )
        self.t = 0
        self.regime_index = 0
        self.last_action: str | None = None
        self.last_alive = True
        self.just_shifted = False
        self.entered_region = False
        self.enter_step: int | None = None
        self._state_history = [self.state]

    def _make_rates(self, n_regimes: int) -> tuple[GEcoRates, ...]:
        base = [
            GEcoRates(
                energy_drain=5.0,
                integrity_drain=1.5,
                need_a_growth=4.0,
                need_b_growth=5.0,
            ),
            GEcoRates(
                energy_drain=7.0,
                integrity_drain=2.8,
                need_a_growth=3.0,
                need_b_growth=4.0,
            ),
            GEcoRates(
                energy_drain=4.0,
                integrity_drain=3.3,
                need_a_growth=6.2,
                need_b_growth=2.8,
            ),
            GEcoRates(
                energy_drain=5.8,
                integrity_drain=2.2,
                need_a_growth=2.7,
                need_b_growth=6.4,
            ),
        ]
        offset = self.rng.randrange(len(base))
        return tuple(base[(offset + i) % len(base)] for i in range(n_regimes))

    @property
    def current_rates(self) -> GEcoRates:
        return self._rates[self.regime_index % len(self._rates)]

    @property
    def alive(self) -> bool:
        return (
            self.state.energy > self.limits.energy_death
            and self.state.integrity > self.limits.integrity_death
            and self.state.need_a < self.limits.need_death
            and self.state.need_b < self.limits.need_death
        )

    def _lagged_state(self) -> GEcoState:
        idx = max(0, len(self._state_history) - 1 - self.observation_lag)
        return self._state_history[idx]

    def _noise(self, channel_index: int) -> float:
        if self.observation_noise == 0.0:
            return 0.0
        raw = ((self.t + 1) * (channel_index + 3) * (self.regime_index + 5)) % 17
        centered = (raw - 8) / 8.0
        return centered * self.observation_noise

    def _bounded_observed_state(
        self, *, observed_channel_index: int, lagged: GEcoState
    ) -> GEcoState:
        values = {
            "energy": lagged.energy,
            "integrity": lagged.integrity,
            "need_a": lagged.need_a,
            "need_b": lagged.need_b,
        }
        current_name = self.observable_channels[observed_channel_index]
        values[current_name] = getattr(self.state, current_name)

        for idx, name in enumerate(self.observable_channels):
            values[name] = getattr(self, f"_clip_{name}")(
                values[name] + self._noise(idx)
            )

        return GEcoState(
            energy=values["energy"],
            integrity=values["integrity"],
            need_a=values["need_a"],
            need_b=values["need_b"],
            shield=lagged.shield,
        )

    def _clip_energy(self, value: float) -> float:
        return max(self.limits.energy_death, min(self.limits.energy_capacity, value))

    def _clip_integrity(self, value: float) -> float:
        return max(
            self.limits.integrity_death, min(self.limits.integrity_capacity, value)
        )

    def _clip_need_a(self, value: float) -> float:
        return max(0.0, min(self.limits.need_death, value))

    def _clip_need_b(self, value: float) -> float:
        return max(0.0, min(self.limits.need_death, value))

    def observation(self) -> GEcoObservation:
        observed_idx = self.t % len(self.observable_channels)
        observed_channel = self.observable_channels[observed_idx]
        return GEcoObservation(
            state=self._bounded_observed_state(
                observed_channel_index=observed_idx, lagged=self._lagged_state()
            ),
            truth_state=self.state,
            rates=self.current_rates,
            step=self.t,
            regime_index=self.regime_index,
            actions=self.actions,
            effects=self.effects,
            limits=self.limits,
            observed_channels=(observed_channel,),
        )

    def situation(self) -> dict:
        return {
            "step": self.t,
            "regime_index": self.regime_index,
            "state": {
                "energy": self.state.energy,
                "integrity": self.state.integrity,
                "need_a": self.state.need_a,
                "need_b": self.state.need_b,
                "shield": self.state.shield,
            },
            "last_action": self.last_action,
            "alive": self.alive,
            "actions": list(self.actions),
        }

    def act(self, action: str) -> dict[str, float | int | str | bool | None]:
        before = self.state
        self.state = transition_state(
            self.state,
            action,
            rates=self.current_rates,
            effects=self.effects,
            limits=self.limits,
        )
        self.t += 1
        self._state_history.append(self.state)
        self.just_shifted = False
        if self.t % self.period == 0:
            self.regime_index = (self.regime_index + 1) % len(self._rates)
            self.just_shifted = True
        self.last_action = action
        self.last_alive = self.alive
        return {
            "step": self.t,
            "action": action,
            "energy_delta": self.state.energy - before.energy,
            "integrity_delta": self.state.integrity - before.integrity,
            "need_a_delta": self.state.need_a - before.need_a,
            "need_b_delta": self.state.need_b - before.need_b,
            "alive": self.alive,
            "regime_index": self.regime_index,
            "just_shifted": self.just_shifted,
        }
