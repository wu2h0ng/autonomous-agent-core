"""ADR-0040 phi_S reopening falsifier environment.

The environment is deliberately small and fully observable: every optimal
action is a deterministic readout of the public 8x8 observation buffer. Actions
do not affect the observation stream, so the experiment isolates acquisition of
the frozen readout rather than control-induced state changes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable


OBS_DIM = 8
BUFFER_M = 8
ARCHIVE = ("A1", "A2", "A3", "A4")
PHI_STAR = "A1"
MISALIGNED_READOUT = "A2"
REWARD_MAGNITUDE = 1.0

Observation = tuple[int, ...]
Buffer = tuple[Observation, ...]


def _as_pm1(value: int | float) -> int:
    return 1 if value >= 0 else -1


def _require_pm1_vector(obs: Iterable[int]) -> Observation:
    out = tuple(int(v) for v in obs)
    if len(out) != OBS_DIM or any(v not in (-1, 1) for v in out):
        raise ValueError("observation must be a length-8 +/-1 vector")
    return out


def _require_buffer(buffer: Iterable[Iterable[int]]) -> Buffer:
    out = tuple(_require_pm1_vector(obs) for obs in buffer)
    if len(out) != BUFFER_M:
        raise ValueError("buffer must contain exactly 8 observations")
    return out


def bool_and(a: int, b: int) -> int:
    return 1 if a == 1 and b == 1 else -1


def bool_or(a: int, b: int) -> int:
    return 1 if a == 1 or b == 1 else -1


def sign_pm1(value: int | float) -> int:
    return 1 if value >= 0 else -1


def lag_from_observation(obs: Observation) -> int:
    """Return the observable lag selector k in {1, 2, 3}.

    The freeze requires a length-8 +/-1 channel and an observable ternary lag.
    A single +/-1 cell cannot encode three values alone, so the selector is read
    from the public selector bit at index 6 plus the public slow bit at index 7.
    The slow bit remains directly observable at o_t[7].
    """

    if obs[6] == -1:
        return 1
    if obs[7] == -1:
        return 2
    return 3


def flatten_buffer(buffer: Iterable[Iterable[int]]) -> tuple[int, ...]:
    checked = _require_buffer(buffer)
    return tuple(v for obs in checked for v in obs)


def archive_readout(name: str, buffer: Iterable[Iterable[int]]) -> int:
    """Evaluate a frozen archive readout on an 8x8 public buffer."""

    checked = _require_buffer(buffer)
    if name not in ARCHIVE:
        raise ValueError(f"unknown archive readout: {name}")

    current = checked[-1]
    if name == "A1":
        return current[0] * current[2] * current[4]
    if name == "A2":
        k = lag_from_observation(current)
        lagged = checked[-1 - k]
        # XOR in +/-1 coding: +1 iff the two Boolean bits differ.
        return -current[0] * lagged[0]
    if name == "A3":
        return sign_pm1(current[0] * current[1] + current[2])
    if name == "A4":
        return bool_or(bool_and(current[0], current[1]), current[3])
    raise AssertionError("unreachable")


def different_archive_readout(name: str) -> str:
    if name not in ARCHIVE:
        raise ValueError(f"unknown archive readout: {name}")
    idx = ARCHIVE.index(name)
    return ARCHIVE[(idx + 1) % len(ARCHIVE)]


@dataclass(frozen=True)
class PhiSStep:
    observation: Observation
    optimal_action: int
    action: int
    reward: float
    regret: float


class PhiSReopeningEnv:
    """Fully observable ADR-0040 readout ecology.

    `condition="ALIGNED"` makes the environment optimum equal to the fixed
    ORGAN phi*. `condition="MISALIGNED"` keeps ORGAN fixed but uses a different
    archive member as the environment optimum.
    """

    def __init__(
        self,
        *,
        seed: int,
        condition: str = "ALIGNED",
        phi_star: str = PHI_STAR,
        misaligned_readout: str | None = None,
        reward_magnitude: float = REWARD_MAGNITUDE,
        slow_period: int = 11,
    ) -> None:
        if phi_star not in ARCHIVE:
            raise ValueError("phi_star must be in the frozen archive")
        if condition not in ("ALIGNED", "MISALIGNED"):
            raise ValueError("condition must be ALIGNED or MISALIGNED")
        if reward_magnitude <= 0.0:
            raise ValueError("reward_magnitude must be positive")
        if slow_period <= 0:
            raise ValueError("slow_period must be positive")

        self.seed = seed
        self.condition = condition
        self.phi_star = phi_star
        self.readout_name = (
            phi_star
            if condition == "ALIGNED"
            else (misaligned_readout or different_archive_readout(phi_star))
        )
        if self.readout_name == phi_star and condition == "MISALIGNED":
            raise ValueError("MISALIGNED readout must differ from phi_star")
        if self.readout_name not in ARCHIVE:
            raise ValueError("environment readout must be in the frozen archive")

        self.reward_magnitude = reward_magnitude
        self.slow_period = slow_period
        self.rng = random.Random(seed)
        self.t = 0
        self.last_reward = 0.0
        self.last_regret = 0.0
        self.last_action: int | None = None
        self._buffer: list[Observation] = []
        for i in range(BUFFER_M):
            self._buffer.append(self._draw_observation(i - BUFFER_M + 1))

    @property
    def buffer(self) -> Buffer:
        return tuple(self._buffer)

    def observation(self) -> Observation:
        return self._buffer[-1]

    def features64(self) -> tuple[int, ...]:
        return flatten_buffer(self._buffer)

    def optimal_action(self) -> int:
        return archive_readout(self.readout_name, self._buffer)

    def phi_star_action(self) -> int:
        return archive_readout(self.phi_star, self._buffer)

    def oracle_return_per_step(self) -> float:
        return self.reward_magnitude

    def _draw_observation(self, index: int) -> Observation:
        slow = 1 if (index // self.slow_period) % 2 == 0 else -1
        selector = -1 if index % 3 == 0 else 1
        # Bits 0..5 are stochastic; bits 6..7 expose selector and slow regime.
        bits = [self.rng.choice((-1, 1)) for _ in range(6)]
        bits.append(selector)
        bits.append(slow)
        return tuple(bits)

    def advance_without_action(self) -> None:
        self.t += 1
        self._buffer.append(self._draw_observation(self.t))
        self._buffer = self._buffer[-BUFFER_M:]

    def act(self, action: int) -> float:
        if action not in (-1, 1):
            raise ValueError("action must be -1 or +1")
        optimal = self.optimal_action()
        reward = self.reward_magnitude if action == optimal else -self.reward_magnitude
        self.last_reward = reward
        self.last_regret = 0.0 if action == optimal else 2.0 * self.reward_magnitude
        self.last_action = action
        self.advance_without_action()
        return reward

    def step_record(self, action: int) -> PhiSStep:
        obs = self.observation()
        optimal = self.optimal_action()
        reward = self.act(action)
        return PhiSStep(
            observation=obs,
            optimal_action=optimal,
            action=action,
            reward=reward,
            regret=self.last_regret,
        )
