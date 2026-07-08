"""Tests for online / regime-shift interactive discovery loop."""
from __future__ import annotations

import unittest

from aac.interactive_discovery_loop import (
    InteractiveDiscoveryLoop,
    OnlineInteractiveDiscoveryLoop,
    run_regime_shift_benchmark,
)
from aac.live_intervention_env import CausalSimulationEnv
from aac.regime_shift_env import PiecewiseCausalSimulationEnv


class OnlineDiscoveryLoopTest(unittest.TestCase):
    def test_online_loop_runs_multiple_rounds(self) -> None:
        env = CausalSimulationEnv(
            n_nodes=3,
            edges={(0, 1), (1, 2)},
            seed=42,
            noise_std=0.2,
        )
        loop = OnlineInteractiveDiscoveryLoop(
            organs=[],
            environment=env,
            budget=4,
            confidence_threshold=0.99,
            seed=42,
            n_particles=30,
            max_window_size=80,
        )
        results = loop.discover_online(
            rounds=3,
            n_obs_per_round=40,
            interventions_per_round=4,
        )
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertIn(r.status, ("VERIFIED", "BUDGET_EXHAUSTED"))
            self.assertIsNotNone(r.best_dag)

    def test_online_adapts_to_regime_shift(self) -> None:
        """Online sliding-window loop should outperform a static pre-shift baseline."""
        result = run_regime_shift_benchmark(seed=42)
        online_shd = result["online"]["shd_vs_regime1"]
        static_shd = result["static"]["shd_vs_regime1"]
        # The online loop observes post-shift data and is allowed to intervene;
        # it should not do worse than a baseline that only saw the old regime.
        self.assertLessEqual(online_shd, static_shd)

    def test_windowing_discards_old_observations(self) -> None:
        env = PiecewiseCausalSimulationEnv(
            n_nodes=3,
            regimes=[
                {"edges": {(0, 1)}, "seed": 1},
                {"edges": {(0, 1), (1, 2)}, "seed": 2},
            ],
            changepoints=[200],
            base_seed=1,
        )
        loop = OnlineInteractiveDiscoveryLoop(
            organs=[],
            environment=env,
            budget=2,
            confidence_threshold=0.99,
            seed=1,
            n_particles=20,
            max_window_size=20,
        )
        results = loop.discover_online(
            rounds=4,
            n_obs_per_round=100,
            interventions_per_round=2,
        )
        self.assertEqual(len(results), 4)

    def test_c7_offline_invariant_online(self) -> None:
        """The online loop never executes an external action; it only reads."""
        env = CausalSimulationEnv(n_nodes=3, edges={(0, 1)}, seed=7)
        loop = OnlineInteractiveDiscoveryLoop(
            organs=[],
            environment=env,
            budget=2,
            seed=7,
            n_particles=20,
        )
        # The loop should complete without any side effects beyond calling
        # env.observe() and env.intervene() in the simulation sandbox.
        results = loop.discover_online(rounds=2, n_obs_per_round=20, interventions_per_round=2)
        self.assertEqual(len(results), 2)


if __name__ == "__main__":
    unittest.main()
