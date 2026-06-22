"""Perturbed task mixture for P3 RAP baselines (T-P3.2, ADR-0014)."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .survival import GridlessSurvival


class SegmentKind(str, Enum):
    STABLE = "stable"
    SHIFTING = "shifting"
    NOISY = "noisy"


class DisturbanceKind(str, Enum):
    NONE = "none"
    NODE_DROP = "node_drop"
    NODE_LAG = "node_lag"


@dataclass(frozen=True)
class SegmentSpec:
    kind: SegmentKind
    length: int
    disturbance: DisturbanceKind = DisturbanceKind.NONE
    node_id: str | None = None

    def __post_init__(self) -> None:
        if self.length <= 0:
            raise ValueError("segment length must be positive")
        if self.disturbance is DisturbanceKind.NONE and self.node_id is not None:
            raise ValueError("undisturbed segments must not name a node")
        if self.disturbance is not DisturbanceKind.NONE and not self.node_id:
            raise ValueError("node disturbance must name a node_id")


def generate_segments(
    *,
    rng: random.Random,
    total_steps: int,
    node_ids: tuple[str, ...],
    min_length: int = 40,
    max_length: int = 80,
    disturbance_rate: float = 0.25,
) -> tuple[SegmentSpec, ...]:
    if total_steps <= 0:
        raise ValueError("total_steps must be positive")
    if not node_ids:
        raise ValueError("node_ids must be non-empty")
    if min_length <= 0 or max_length < min_length:
        raise ValueError("invalid segment length bounds")
    if not 0.0 <= disturbance_rate <= 1.0:
        raise ValueError("disturbance_rate must be in [0, 1]")

    kinds = tuple(SegmentKind)
    remaining = total_steps
    segments: list[SegmentSpec] = []
    while remaining > 0:
        length = min(remaining, rng.randint(min_length, max_length))
        kind = rng.choice(kinds)
        disturbance = DisturbanceKind.NONE
        node_id: str | None = None
        if rng.random() < disturbance_rate:
            disturbance = rng.choice(
                (DisturbanceKind.NODE_DROP, DisturbanceKind.NODE_LAG)
            )
            node_id = rng.choice(node_ids)
        segments.append(
            SegmentSpec(
                kind=kind,
                length=length,
                disturbance=disturbance,
                node_id=node_id,
            )
        )
        remaining -= length
    return tuple(segments)


class RAPPerturbationEnv:
    """GridlessSurvival with STABLE/SHIFTING/NOISY segments and node faults."""

    def __init__(
        self,
        *,
        n_actions: int,
        rng: random.Random,
        segments: tuple[SegmentSpec, ...],
        base_regime_period: int = 60,
        base_noise: float = 0.3,
        reward_low: float = -1.0,
        reward_high: float = 4.0,
    ) -> None:
        if not segments:
            raise ValueError("segments must be non-empty")
        if base_regime_period <= 0:
            raise ValueError("base_regime_period must be positive")
        if base_noise < 0:
            raise ValueError("base_noise must be non-negative")
        self.base_regime_period = base_regime_period
        self.base_noise = base_noise
        self._segments = segments
        self._segment_index = 0
        self._segment_elapsed = 0
        self._env = GridlessSurvival(
            n_actions=n_actions,
            rng=rng,
            regime_period=base_regime_period,
            noise=base_noise,
            reward_low=reward_low,
            reward_high=reward_high,
        )
        self._apply_segment(force_regime=True)

    @property
    def segments(self) -> tuple[SegmentSpec, ...]:
        return self._segments

    @property
    def current_segment(self) -> SegmentSpec:
        return self._segments[self._segment_index]

    @property
    def last_regret(self) -> float:
        return self._env.last_regret

    @property
    def best_action(self) -> int:
        return self._env.best_action

    @property
    def expected_random_regret(self) -> float:
        """Judge-side baseline (delegated); deciders must not read it."""
        return self._env.expected_random_regret

    @property
    def n_actions(self) -> int:
        return self._env.n_actions

    @property
    def t(self) -> int:
        return self._env.t

    @property
    def regime_index(self) -> int:
        return self._env.regime_index

    @property
    def noise(self) -> float:
        return self._env.noise

    @property
    def regime_period(self) -> int:
        return self._env.regime_period

    def situation(self) -> dict[str, Any]:
        segment = self.current_segment
        return {
            "segment": segment.kind.value,
            "disturbance": segment.disturbance.value,
            "node_id": segment.node_id,
            "dropped_node": (
                segment.node_id
                if segment.disturbance is DisturbanceKind.NODE_DROP
                else None
            ),
            "lagged_node": (
                segment.node_id
                if segment.disturbance is DisturbanceKind.NODE_LAG
                else None
            ),
            "step": self.t,
            "segment_elapsed": self._segment_elapsed,
            "regime_index": self.regime_index,
        }

    def node_available(self, node_id: str) -> bool:
        segment = self.current_segment
        return not (
            segment.disturbance is DisturbanceKind.NODE_DROP
            and segment.node_id == node_id
        )

    def node_lagged(self, node_id: str) -> bool:
        segment = self.current_segment
        return (
            segment.disturbance is DisturbanceKind.NODE_LAG
            and segment.node_id == node_id
        )

    def garbage_action(self) -> int:
        return 0

    def act(self, action: int) -> float:
        reward = self._env.act(action)
        self._segment_elapsed += 1
        if self._segment_elapsed >= self.current_segment.length:
            self._advance_segment()
        return reward

    def _advance_segment(self) -> None:
        if self._segment_index < len(self._segments) - 1:
            self._segment_index += 1
        self._segment_elapsed = 0
        self._apply_segment(force_regime=True)

    def _apply_segment(self, *, force_regime: bool) -> None:
        segment = self.current_segment
        if segment.kind is SegmentKind.STABLE:
            self._env.regime_period = max(self.base_regime_period, segment.length + 1)
            self._env.noise = self.base_noise
        elif segment.kind is SegmentKind.SHIFTING:
            self._env.regime_period = max(
                5, min(self.base_regime_period, segment.length // 4)
            )
            self._env.noise = self.base_noise
        elif segment.kind is SegmentKind.NOISY:
            self._env.regime_period = max(self.base_regime_period, segment.length + 1)
            self._env.noise = self.base_noise * 3.0
        else:  # pragma: no cover - defensive for future enum extension.
            raise ValueError(f"unknown segment kind: {segment.kind}")
        if force_regime:
            self._env.force_regime_change()
