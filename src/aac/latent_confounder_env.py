"""Partially-observed / latent-confounder simulation environment.

The environment generates data from a full linear-Gaussian SCM but only exposes
a subset of nodes to the discovery loop.  Latent confounders can create
spurious correlations between observed variables.  The loop must recover the
observed-subgraph edges without hallucinating direct edges that are only
confounded.

Like the other live-intervention environments, this is verify-only: it returns
observations and interventional samples, but never holds execution authority.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from .live_intervention_env import CausalSimulationEnv


@dataclass
class PartiallyObservedSCMEnv:
    """A causal simulation environment with latent (unobserved) variables.

    Args:
        n_total: total number of nodes in the underlying SCM.
        observed_indices: indices of the nodes exposed to the discovery loop.
        edges: directed edges of the full SCM (may include latent nodes).
        noise_std: standard deviation of the zero-mean Gaussian noise.
        seed: RNG seed for reproducibility.
        coef_range: range from which coefficients are drawn.
    """

    n_total: int
    observed_indices: list[int]
    edges: set[tuple[int, int]] | frozenset[tuple[int, int]]
    noise_std: float = 0.3
    seed: int = 42
    coef_range: tuple[float, float] = (0.5, 1.0)
    _full_env: CausalSimulationEnv = field(init=False, repr=False)
    _obs_to_total: dict[int, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.observed_indices:
            raise ValueError("at least one observed node is required")
        if any(idx < 0 or idx >= self.n_total for idx in self.observed_indices):
            raise ValueError("observed_indices must be in [0, n_total)")
        if len(set(self.observed_indices)) != len(self.observed_indices):
            raise ValueError("observed_indices must be unique")
        self._full_env = CausalSimulationEnv(
            n_nodes=self.n_total,
            edges=self.edges,
            seed=self.seed,
            noise_std=self.noise_std,
            coef_range=self.coef_range,
        )
        self._obs_to_total = {
            obs_idx: total_idx for obs_idx, total_idx in enumerate(self.observed_indices)
        }

    @property
    def n_observed(self) -> int:
        return len(self.observed_indices)

    @property
    def n_nodes(self) -> int:
        """Alias for ``n_observed`` so the env matches the unified harness API."""
        return self.n_observed

    @property
    def latent_indices(self) -> list[int]:
        all_set = set(range(self.n_total))
        return sorted(all_set - set(self.observed_indices))

    def _mask(self, full_row: list[float]) -> list[float]:
        return [full_row[i] for i in self.observed_indices]

    def observe(self, n_samples: int) -> list[list[float]]:
        """Return n observational samples of the observed nodes only."""
        full = self._full_env.observe(n_samples)
        return [self._mask(row) for row in full]

    def intervene(self, do_node: int, do_value: float) -> list[float]:
        """Return one sample under do(do_node=do_value) on an observed node.

        The intervention is applied to the underlying full SCM; only the
        observed dimensions are returned.
        """
        total_node = self._obs_to_total[do_node]
        full_row = self._full_env.intervene(total_node, do_value)
        return self._mask(full_row)

    @property
    def ground_truth_observed_edges(self) -> set[tuple[int, int]]:
        """Directed edges whose source and target are both observed."""
        obs_set = set(self.observed_indices)
        result: set[tuple[int, int]] = set()
        for u, v in self.edges:
            if u in obs_set and v in obs_set:
                # Remap to observed-node coordinates.
                result.add((self.observed_indices.index(u), self.observed_indices.index(v)))
        return result

    @property
    def ground_truth_edges(self) -> set[tuple[int, int]]:
        """Alias for ``ground_truth_observed_edges`` for the unified harness API."""
        return self.ground_truth_observed_edges

    def structural_hamming_distance(self, predicted: set[tuple[int, int]]) -> int:
        """SHD against the observed-subgraph ground truth."""
        truth = self.ground_truth_observed_edges
        return len((truth - predicted) | (predicted - truth))
