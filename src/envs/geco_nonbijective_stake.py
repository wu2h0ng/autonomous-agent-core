"""G-ECO-REOPEN-1 non-bijective stake-channel environment.

The environment is deliberately small and deterministic. At the initial
observation two latent basins can expose the same visible stake/stress channel
while requiring different future-preserving commitments. The only public way to
disambiguate the basin is the ``probe`` action.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

BASINS = ("ridge", "valley")
ACTIONS = ("probe", "commit_ridge", "commit_valley", "stabilize")


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(slots=True)
class NBSCState:
    latent_basin: str
    viability: float
    stress: float
    revealed_signal: str | None = None
    step: int = 0
    irreversible_damage: float = 0.0


@dataclass(frozen=True, slots=True)
class NBSCObservation:
    visible_stake: float | None
    stress: float
    revealed_signal: str | None
    remaining_steps: int
    actions: tuple[str, ...] = ACTIONS

    @property
    def ambiguous(self) -> bool:
        return self.visible_stake is not None and self.revealed_signal is None


@dataclass(frozen=True, slots=True)
class NBSCOutcome:
    action: str
    before_viability: float
    after_viability: float
    damage_delta: float
    revealed_signal: str | None


class NonBijectiveStakeEnv:
    """Hidden-basin viability environment with a public probe action."""

    actions = ACTIONS

    def __init__(
        self,
        *,
        state: NBSCState,
        horizon: int = 2,
        visible_stake: float = 0.50,
    ) -> None:
        if state.latent_basin not in BASINS:
            raise ValueError(f"latent_basin must be one of {BASINS!r}")
        if horizon <= 0:
            raise ValueError("horizon must be positive")
        self.state = state
        self.horizon = horizon
        self.visible_stake = visible_stake

    @classmethod
    def from_seed(
        cls,
        seed: int,
        *,
        forced_basin: str | None = None,
        horizon: int = 2,
    ) -> "NonBijectiveStakeEnv":
        rng = random.Random(seed)
        stress = round(0.35 + rng.random() * 0.20, 6)
        base_viability = round(0.63 - stress * 0.05, 6)
        if forced_basin is not None:
            if forced_basin not in BASINS:
                raise ValueError(f"forced_basin must be one of {BASINS!r}")
            basin = forced_basin
        else:
            basin = rng.choice(BASINS)
        return cls(
            state=NBSCState(
                latent_basin=basin,
                viability=base_viability,
                stress=stress,
            ),
            horizon=horizon,
        )

    def observation(self, *, mask_stake: bool = False) -> NBSCObservation:
        remaining = max(0, self.horizon - self.state.step)
        return NBSCObservation(
            visible_stake=None if mask_stake else self.visible_stake,
            stress=self.state.stress,
            revealed_signal=None if mask_stake else self.state.revealed_signal,
            remaining_steps=remaining,
            actions=self.actions,
        )

    @property
    def done(self) -> bool:
        return self.state.step >= self.horizon

    @property
    def future_viability_loss(self) -> float:
        return 1.0 - self.state.viability

    def act(self, action: str) -> NBSCOutcome:
        if action not in self.actions:
            raise ValueError(f"unsupported NBSC action: {action!r}")
        if self.done:
            raise RuntimeError("episode is already complete")

        before = self.state.viability
        damage_delta = 0.0

        if action == "probe":
            cost = 0.035 + self.state.stress * 0.010
            self.state.viability = _clip01(self.state.viability - cost)
            self.state.revealed_signal = self.state.latent_basin
        elif action == "stabilize":
            gain = 0.045 - self.state.stress * 0.015
            self.state.viability = _clip01(self.state.viability + gain)
        else:
            target = "ridge" if action == "commit_ridge" else "valley"
            if target == self.state.latent_basin:
                gain = 0.300 - self.state.stress * 0.030
                self.state.viability = _clip01(self.state.viability + gain)
            else:
                damage_delta = 0.330 + self.state.stress * 0.080
                self.state.viability = _clip01(self.state.viability - damage_delta)
                self.state.irreversible_damage += damage_delta

        self.state.step += 1
        return NBSCOutcome(
            action=action,
            before_viability=before,
            after_viability=self.state.viability,
            damage_delta=damage_delta,
            revealed_signal=self.state.revealed_signal,
        )
