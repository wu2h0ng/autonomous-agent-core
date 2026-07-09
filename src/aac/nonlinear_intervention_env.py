"""Nonlinear simulation environments for governed causal discovery.

Extends the live-intervention binding beyond linear-Gaussian SCMs.  The
environments here are still verify-only: they return observations and
interventional samples, but never hold execution authority.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PolynomialCausalSimulationEnv:
    """A polynomial SCM simulation environment for live CWM interventions.

    Each directed edge contributes a degree-2 polynomial parent effect:

        x_j = sum_{i in pa(j)} (alpha_{ij} * x_i + beta_{ij} * x_i^2) + epsilon_j

    The linear term preserves orientability while the quadratic term makes the
    relationship nonlinear, so a polynomial likelihood should outperform a
    purely linear likelihood.

    Args:
        n_nodes: number of nodes.
        edges: directed edges of the ground-truth DAG.
        noise_std: standard deviation of the zero-mean Gaussian noise.
        seed: RNG seed for reproducibility.
        coef_range: range from which positive linear and quadratic coefficients
            are drawn independently.
    """

    n_nodes: int
    edges: set[tuple[int, int]] | frozenset[tuple[int, int]]
    noise_std: float = 0.3
    seed: int = 42
    coef_range: tuple[float, float] = (0.5, 1.0)
    _rng: random.Random = field(init=False, repr=False)
    _lin_coefs: dict[tuple[int, int], float] = field(init=False, repr=False)
    _quad_coefs: dict[tuple[int, int], float] = field(init=False, repr=False)
    _topological_order: list[int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._lin_coefs = {}
        self._quad_coefs = {}
        for u, v in self.edges:
            self._lin_coefs[(u, v)] = self._rng.uniform(*self.coef_range)
            self._quad_coefs[(u, v)] = self._rng.uniform(*self.coef_range)
        self._topological_order = self._compute_topological_order()

    @property
    def ground_truth_edges(self) -> set[tuple[int, int]]:
        return set(self.edges)

    def _compute_topological_order(self) -> list[int]:
        parents: dict[int, list[int]] = {j: [] for j in range(self.n_nodes)}
        for u, v in self.edges:
            parents[v].append(u)
        indeg = {j: len(parents[j]) for j in range(self.n_nodes)}
        order: list[int] = []
        queue = [j for j in range(self.n_nodes) if indeg[j] == 0]
        while queue:
            j = queue.pop(0)
            order.append(j)
            for u, v in self.edges:
                if u == j:
                    indeg[v] -= 1
                    if indeg[v] == 0:
                        queue.append(v)
        for j in range(self.n_nodes):
            if j not in order:
                order.append(j)
        return order

    def _sample_row(self, intervention: dict[int, float] | None = None) -> list[float]:
        intervention = intervention or {}
        row: list[float] = [0.0] * self.n_nodes
        for j in self._topological_order:
            if j in intervention:
                row[j] = float(intervention[j])
                continue
            val = self._rng.gauss(0.0, self.noise_std)
            for p, q in self.edges:
                if q == j:
                    val += (
                        self._lin_coefs[(p, q)] * row[p]
                        + self._quad_coefs[(p, q)] * (row[p] ** 2)
                    )
            row[j] = val
        return row

    def observe(self, n_samples: int) -> list[list[float]]:
        """Return n observational samples from the polynomial SCM."""
        return [self._sample_row() for _ in range(n_samples)]

    def intervene(self, do_node: int, do_value: float) -> list[float]:
        """Return one sample under do(do_node=do_value).

        Verify-only: the environment simulates the intervention and returns the
        resulting observation; no external action is executed.
        """
        return self._sample_row(intervention={do_node: do_value})

    def structural_hamming_distance(self, predicted: set[tuple[int, int]]) -> int:
        """SHD against the ground-truth DAG."""
        truth = self.ground_truth_edges
        return len((truth - predicted) | (predicted - truth))
