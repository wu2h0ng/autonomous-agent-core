"""Live intervention environment binding for governed causal discovery.

Provides a controllable simulation environment that the CWM discovery loop can
query for interventional data.  The environment is verify-only: it returns
observations and interventional samples, but it never holds execution authority
or acts on its own.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from .bayesian_dag_posterior import generate_linear_scm_data


@dataclass
class CausalSimulationEnv:
    """A grounded simulation environment for CWM live interventions.

    The environment hides a linear-Gaussian SCM.  The discovery loop can:
      - observe(n) -> n observational samples
      - intervene(node, value) -> one sample where do(node=value)

    Ground-truth DAG and coefficients are exposed for evaluation only.
    """

    n_nodes: int
    edges: set[tuple[int, int]] | frozenset[tuple[int, int]]
    noise_std: float = 0.3
    seed: int = 42
    coef_range: tuple[float, float] = (0.3, 1.0)
    _rng: random.Random = field(init=False, repr=False)
    _coefs: dict[tuple[int, int], float] = field(init=False, repr=False)
    _topological_order: list[int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        # Reuse the existing SCM generator to get stable coefficients.
        _, self._coefs = generate_linear_scm_data(
            self.n_nodes,
            self.edges,
            n_obs=0,
            noise_std=self.noise_std,
            rng=self._rng,
            coef_range=self.coef_range,
        )
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
        # Fallback: append remaining nodes deterministically.
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
                    val += self._coefs[(p, q)] * row[p]
            row[j] = val
        return row

    def observe(self, n_samples: int) -> list[list[float]]:
        """Return n observational samples from the SCM."""
        return [self._sample_row() for _ in range(n_samples)]

    def intervene(self, do_node: int, do_value: float) -> list[float]:
        """Return one sample under do(do_node=do_value).

        This is a verify-only read: the environment simulates the intervention
        and returns the resulting observation.  No external action is executed.
        """
        return self._sample_row(intervention={do_node: do_value})

    def structural_hamming_distance(self, predicted: set[tuple[int, int]]) -> int:
        """SHD against the ground-truth DAG."""
        truth = self.ground_truth_edges
        return len((truth - predicted) | (predicted - truth))


@dataclass
class RandomInterventionEnv:
    """Adapter that makes a CausalSimulationEnv answer random interventions.

    Used as a cheap baseline: the discovery loop still calls the same
    ``intervene(node, value)`` surface, but the node/value are chosen randomly
    instead of by BOED/EIG.
    """

    env: CausalSimulationEnv
    rng: random.Random = field(default_factory=lambda: random.Random(0))

    def observe(self, n_samples: int) -> list[list[float]]:
        return self.env.observe(n_samples)

    def intervene(self, do_node: int, do_value: float) -> list[float]:
        # Ignore the BOED proposal and return a random intervention.
        node = self.rng.randrange(self.env.n_nodes)
        mean = 0.0
        value = self.rng.gauss(mean, 1.0)
        return self.env.intervene(node, value)

    @property
    def ground_truth_edges(self) -> set[tuple[int, int]]:
        return self.env.ground_truth_edges

    def structural_hamming_distance(self, predicted: set[tuple[int, int]]) -> int:
        return self.env.structural_hamming_distance(predicted)
