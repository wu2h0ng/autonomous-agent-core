"""Non-stationary / regime-shift simulation environments for governed causal discovery.

These environments extend the live-intervention binding to piecewise causal models.
The discovery loop can observe and intervene in a simulation where the underlying
DAG or coefficients change at known or unknown changepoints.  The environment
remains verify-only: it returns samples, never holds execution authority.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from .live_intervention_env import CausalSimulationEnv


@dataclass
class PiecewiseCausalSimulationEnv:
    """A causal simulation environment with multiple piecewise-stationary regimes.

    Each regime is an independent linear-Gaussian SCM.  The environment switches
    regimes when the internal sample counter crosses a changepoint.  This lets a
    discovery loop test online adaptation: old data may mislead after a shift.

    Args:
        n_nodes: number of nodes in every regime.
        regimes: list of regime descriptors.  Each descriptor is a dict with
            ``edges`` (required), plus optional ``seed``, ``noise_std``,
            ``coef_range``.
        changepoints: sample-count thresholds at which to switch to the next
            regime.  Length must equal ``len(regimes) - 1``.
        base_seed: fallback seed used when a regime descriptor does not specify
            one; the regime index is added to avoid identical regimes.
    """

    n_nodes: int
    regimes: list[dict[str, Any]]
    changepoints: list[int]
    base_seed: int = 42
    _envs: list[CausalSimulationEnv] = field(init=False, repr=False)
    _step: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        if len(self.changepoints) != len(self.regimes) - 1:
            raise ValueError(
                "changepoints length must be len(regimes) - 1; "
                f"got {len(self.changepoints)} changepoints, {len(self.regimes)} regimes"
            )
        if not self.regimes:
            raise ValueError("at least one regime is required")
        self._envs = []
        for idx, reg in enumerate(self.regimes):
            seed = reg.get("seed", self.base_seed + idx)
            self._envs.append(
                CausalSimulationEnv(
                    n_nodes=self.n_nodes,
                    edges=reg["edges"],
                    seed=seed,
                    noise_std=reg.get("noise_std", 0.3),
                    coef_range=reg.get("coef_range", (0.3, 1.0)),
                )
            )
        self._step = 0

    @property
    def current_regime_index(self) -> int:
        """Return the active regime for the next sample."""
        for idx, cp in enumerate(self.changepoints):
            if self._step < cp:
                return idx
        return len(self.changepoints)

    def _current_env(self) -> CausalSimulationEnv:
        return self._envs[self.current_regime_index]

    @property
    def ground_truth_edges(self) -> set[tuple[int, int]]:
        """Ground-truth DAG of the current regime."""
        return self._current_env().ground_truth_edges

    def regime_truth_edges(self, regime_index: int) -> set[tuple[int, int]]:
        """Ground-truth DAG of an arbitrary regime (for evaluation)."""
        return self._envs[regime_index].ground_truth_edges

    def observe(self, n_samples: int) -> list[list[float]]:
        """Return ``n_samples`` observations, switching regimes as needed."""
        out: list[list[float]] = []
        remaining = n_samples
        while remaining > 0:
            regime = self.current_regime_index
            env = self._envs[regime]
            if regime < len(self.changepoints):
                take = min(remaining, self.changepoints[regime] - self._step)
            else:
                take = remaining
            out.extend(env.observe(take))
            self._step += take
            remaining -= take
        return out

    def intervene(self, do_node: int, do_value: float) -> list[float]:
        """Return one sample under do(do_node=do_value) in the current regime."""
        return self._current_env().intervene(do_node, do_value)

    def reset(self) -> None:
        """Reset the internal sample counter and re-create regime envs."""
        self.__post_init__()

    def structural_hamming_distance(
        self, predicted: set[tuple[int, int]], regime_index: int | None = None
    ) -> int:
        """SHD against a regime's ground-truth DAG (default: current regime)."""
        truth = self.regime_truth_edges(
            regime_index if regime_index is not None else self.current_regime_index
        )
        return len((truth - predicted) | (predicted - truth))
