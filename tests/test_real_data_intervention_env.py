"""Tests for the real-data intervention binding protocol.

These tests use an in-memory mock adapter to verify C7 policy enforcement.
No external system is contacted.
"""
from __future__ import annotations

import unittest
from typing import Any

from aac.real_data_intervention_env import (
    GovernedInterventionBinding,
    InterventionOutcome,
    InterventionProposal,
    InterventionError,
    RealDataInterventionEnv,
)


class _MockEnv:
    """In-memory adapter implementing the RealDataInterventionEnv surface."""

    n_nodes = 3
    observed_variables = ["x0", "x1", "x2"]
    allowed_handles = {0, 1}
    safe_value_ranges = {0: (-2.0, 2.0), 1: (-1.0, 1.0)}
    ground_truth_edges = {(0, 1), (1, 2)}

    def __init__(self) -> None:
        self.calls: list[tuple[int, float]] = []

    def observe(self, n_samples: int) -> list[list[float]]:
        return [[float(i), float(i), float(i)] for i in range(n_samples)]

    def intervene(self, do_node: int, do_value: float) -> list[float] | None:
        self.calls.append((do_node, do_value))
        row = [0.0, 0.0, 0.0]
        row[do_node] = do_value
        return row

    def structural_hamming_distance(
        self, predicted: set[tuple[int, int]]
    ) -> int | None:
        truth = self.ground_truth_edges
        return len((truth - predicted) | (predicted - truth))


class GovernedInterventionBindingTest(unittest.TestCase):
    def _make(self, *, dry_run: bool = True, budget: int = 5) -> tuple[GovernedInterventionBinding, _MockEnv, list[InterventionOutcome]]:
        env = _MockEnv()
        audit_log: list[InterventionOutcome] = []
        binding = GovernedInterventionBinding(
            env=env,
            forbidden_nodes={2},
            forbidden_edges=set(),
            dry_run=dry_run,
            budget=budget,
            approval=lambda _p: True,
            audit=lambda o: audit_log.append(o),
        )
        return binding, env, audit_log

    def test_observe_passes_through(self) -> None:
        binding, _, _ = self._make()
        obs = binding.observe(2)
        self.assertEqual(len(obs), 2)

    def test_dry_run_does_not_call_adapter(self) -> None:
        binding, env, log = self._make(dry_run=True)
        sample = binding.intervene(0, 1.0)
        self.assertEqual(sample, [1.0, 0.0, 0.0])
        self.assertEqual(env.calls, [])
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0].status, "dry_run")
        self.assertTrue(log[0].proposal.dry_run)

    def test_forbidden_node_blocked(self) -> None:
        binding, env, log = self._make()
        sample = binding.intervene(2, 1.0)
        self.assertIsNone(sample)
        self.assertEqual(env.calls, [])
        self.assertEqual(log[0].status, "blocked")
        self.assertEqual(log[0].audit_entry["reason"], "C7_forbidden_node")

    def test_disallowed_handle_blocked(self) -> None:
        binding, env, log = self._make()
        # Node 2 is also disallowed by the adapter; already covered by forbidden_node,
        # so test with a node that is neither forbidden nor allowed is impossible
        # with this mock.  Instead shrink allowed_handles and test node 1.
        env.allowed_handles = {0}
        sample = binding.intervene(1, 0.5)
        self.assertIsNone(sample)
        self.assertEqual(log[0].status, "blocked")
        self.assertEqual(log[0].audit_entry["reason"], "not_an_allowed_handle")

    def test_value_out_of_range_blocked(self) -> None:
        binding, env, log = self._make()
        sample = binding.intervene(0, 5.0)
        self.assertIsNone(sample)
        self.assertEqual(env.calls, [])
        self.assertEqual(log[0].status, "blocked")
        self.assertEqual(log[0].audit_entry["reason"], "value_out_of_range")

    def test_live_path_requires_approval(self) -> None:
        env = _MockEnv()
        audit_log: list[InterventionOutcome] = []
        binding = GovernedInterventionBinding(
            env=env,
            dry_run=False,
            budget=5,
            approval=lambda _p: False,
            audit=lambda o: audit_log.append(o),
        )
        sample = binding.intervene(0, 0.5)
        self.assertIsNone(sample)
        self.assertEqual(env.calls, [])
        self.assertEqual(audit_log[0].status, "denied")

    def test_live_path_applies_when_approved(self) -> None:
        env = _MockEnv()
        audit_log: list[InterventionOutcome] = []
        binding = GovernedInterventionBinding(
            env=env,
            dry_run=False,
            budget=5,
            approval=lambda _p: True,
            audit=lambda o: audit_log.append(o),
        )
        sample = binding.intervene(0, 0.5)
        self.assertEqual(sample, [0.5, 0.0, 0.0])
        self.assertEqual(env.calls, [(0, 0.5)])
        self.assertEqual(audit_log[0].status, "applied")
        self.assertEqual(binding.interventions_spent, 1)

    def test_budget_exhausted_blocks(self) -> None:
        binding, env, log = self._make(budget=1)
        binding.intervene(0, 0.1)
        sample = binding.intervene(0, 0.2)
        self.assertIsNone(sample)
        self.assertEqual(log[-1].status, "budget_exhausted")
        self.assertEqual(env.calls, [])

    def test_readback_missing_logged(self) -> None:
        env = _MockEnv()
        env.intervene = lambda _n, _v: None  # type: ignore[method-assign]
        audit_log: list[InterventionOutcome] = []
        binding = GovernedInterventionBinding(
            env=env,
            dry_run=False,
            budget=5,
            approval=lambda _p: True,
            audit=lambda o: audit_log.append(o),
        )
        sample = binding.intervene(0, 0.5)
        self.assertIsNone(sample)
        self.assertEqual(audit_log[0].status, "readback_missing")

    def test_shd_passes_through(self) -> None:
        binding, _, _ = self._make()
        # Truth = {(0,1),(1,2)}; predicted {(0,2)} differs by 3 edges total.
        self.assertEqual(binding.structural_hamming_distance({(0, 2)}), 3)


if __name__ == "__main__":
    unittest.main()
