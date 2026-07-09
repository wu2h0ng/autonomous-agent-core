"""Integration tests for WeightMemory decoupling in Agent core loop."""

from __future__ import annotations

import random
import unittest

from aac.agent import Agent
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from aac.weight_memory import WeightMemory


class _StubEnv:
    def __init__(self, rewards=None):
        self.rewards = rewards or [1.0] * 100
        self._idx = 0
        self.idle = False
        self.last_regret = 0.0
        self.just_shifted = False

    def act(self, action):
        r = self.rewards[self._idx % len(self.rewards)]
        self._idx += 1
        return r


class WeightMemoryIntegration(unittest.TestCase):
    def setUp(self):
        self.shell = CorrigibilityShell()
        self.viability = ViabilityCore(budget=1e9, metabolic_cost=0.0, capacity=1e9)

    def test_agent_with_weight_memory_default_none(self):
        agent = Agent(n_actions=4, shell=self.shell, rng=random.Random(42),
                      viability=self.viability)
        self.assertIsNone(agent.weight_memory)
        self.assertEqual(agent.strategy_memory_size, 0)

    def test_agent_with_weight_memory(self):
        memory = WeightMemory()
        agent = Agent(n_actions=4, shell=self.shell, rng=random.Random(42),
                      viability=self.viability, weight_memory=memory)
        self.assertIsNotNone(agent.weight_memory)
        self.assertEqual(agent.strategy_memory_size, 0)

    def test_switch_strategy_snapshots_and_warmstarts(self):
        memory = WeightMemory()
        agent = Agent(n_actions=4, shell=self.shell, rng=random.Random(42),
                      viability=self.viability, weight_memory=memory)

        # Train under first strategy
        env = _StubEnv([3.0, 1.0, 2.0, 0.5])
        for _ in range(10):
            agent.step(env)

        old_mu = list(agent.model.mu)
        old_unc = list(agent.model.uncertainty)
        self.assertEqual(agent.strategy_memory_size, 0)

        # Switch to new strategy
        warm = agent.switch_strategy(
            old_weights=[1/3, 1/3, 1/3],
            new_weights=[0.8, 0.1, 0.1],
        )
        # First switch: no prior -> cold start
        self.assertFalse(warm)
        self.assertEqual(agent.strategy_memory_size, 1)

        # Model should be reset (no prior = kept as-is)
        self.assertEqual(list(agent.model.mu), old_mu)

        # Train under second strategy
        env2 = _StubEnv([5.0, 0.5, 1.0, 2.0])
        for _ in range(10):
            agent.step(env2)
        new_mu = list(agent.model.mu)

        # Switch back to first strategy
        warm2 = agent.switch_strategy(
            old_weights=[0.8, 0.1, 0.1],
            new_weights=[1/3, 1/3, 1/3],
        )
        # Should warm-start from stored priors
        self.assertTrue(warm2)
        self.assertEqual(agent.strategy_memory_size, 2)

        # Model should now have the old priors blended
        self.assertNotEqual(list(agent.model.mu), new_mu)

    def test_switch_strategy_disabled_when_none(self):
        agent = Agent(n_actions=4, shell=self.shell, rng=random.Random(42),
                      viability=self.viability)
        result = agent.switch_strategy([1/3, 1/3, 1/3], [0.8, 0.1, 0.1])
        self.assertFalse(result)

    def test_switch_similar_weights_returns_same_priors(self):
        memory = WeightMemory()
        agent = Agent(n_actions=4, shell=self.shell, rng=random.Random(42),
                      viability=self.viability, weight_memory=memory)

        env = _StubEnv([3.0, 1.0, 2.0, 0.5])
        for _ in range(10):
            agent.step(env)

        agent.switch_strategy([1/3, 1/3, 1/3], [0.8, 0.1, 0.1])
        # Train a bit
        for _ in range(5):
            agent.step(_StubEnv([1.0, 5.0, 3.0, 0.0]))
        agent.switch_strategy([0.8, 0.1, 0.1], [1/3, 1/3, 1/3])

        # Switch to similar weights
        warm = agent.switch_strategy([1/3, 1/3, 1/3], [0.34, 0.33, 0.33])
        self.assertTrue(warm)  # similar enough to match

    def test_state_roundtrip_preserves_memory(self):
        memory = WeightMemory()
        agent = Agent(n_actions=4, shell=self.shell, rng=random.Random(42),
                      viability=self.viability, weight_memory=memory)

        env = _StubEnv([3.0, 1.0, 2.0, 0.5])
        for _ in range(10):
            agent.step(env)
        agent.switch_strategy([1/3, 1/3, 1/3], [0.8, 0.1, 0.1])

        saved = agent.state()
        self.assertIn("weight_memory", saved)
        self.assertEqual(len(saved["weight_memory"]["entries"]), 1)

        # Restore
        memory2 = WeightMemory()
        agent2 = Agent(n_actions=4, shell=self.shell, rng=random.Random(42),
                       viability=self.viability, weight_memory=memory2)
        agent2.restore(saved)
        self.assertEqual(agent2.strategy_memory_size, 1)

        # Warm-start should work from restored state
        warm = agent2.switch_strategy([0.8, 0.1, 0.1], [1/3, 1/3, 1/3])
        self.assertTrue(warm)


if __name__ == "__main__":
    unittest.main()
