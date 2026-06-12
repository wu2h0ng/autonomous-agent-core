"""Deterministic tests for ViabilityReflex (Layer 0 survival reflex).

Closes the completion-gate debt from commit 8579f58 (reflex shipped without
tests). ADR-0008 documents the mechanism; these tests pin its contract:

  - engages only when pressure is extreme AND the model is confident
  - forced release after recovery_count consecutive engaged steps (no lock-in)
  - natural release when pressure recovers
  - shell pause takes precedence over the reflex (corrigibility before survival)
  - reflex=None is a strict no-op (backward compatibility)
"""
from __future__ import annotations

import random
import unittest

from aac.agent import Agent
from aac.reflex import ViabilityReflex
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from aac.world_model import ActionOutcomeModel


class _StubEnv:
    def __init__(self, reward: float = 0.0) -> None:
        self.reward = reward

    def act(self, action: int) -> float:
        return self.reward


def _confident_model(n_actions: int = 4, best: int = 0) -> ActionOutcomeModel:
    model = ActionOutcomeModel(n_actions=n_actions)
    model.mu = [0.0] * n_actions
    model.mu[best] = 10.0
    model.uncertainty = [0.0] * n_actions
    return model


class TestReflexEngagement(unittest.TestCase):
    def test_engages_when_starving_and_confident(self) -> None:
        reflex = ViabilityReflex()
        self.assertTrue(reflex.should_engage(pressure=0.9, mean_uncertainty=0.1))

    def test_no_engage_when_pressure_low(self) -> None:
        reflex = ViabilityReflex()
        self.assertFalse(reflex.should_engage(pressure=0.5, mean_uncertainty=0.1))

    def test_no_engage_when_model_uncertain(self) -> None:
        """Starving but clueless: reflex must NOT force exploitation of noise."""
        reflex = ViabilityReflex()
        self.assertFalse(reflex.should_engage(pressure=0.9, mean_uncertainty=0.9))

    def test_natural_release_when_pressure_recovers(self) -> None:
        reflex = ViabilityReflex()
        self.assertTrue(reflex.should_engage(pressure=0.9, mean_uncertainty=0.1))
        self.assertFalse(reflex.should_engage(pressure=0.3, mean_uncertainty=0.1))
        # State fully cleared: re-entry needs entry conditions again.
        self.assertTrue(reflex.should_engage(pressure=0.9, mean_uncertainty=0.1))

    def test_forced_release_after_recovery_count(self) -> None:
        """Anti-lock-in: engaged streak is capped at recovery_count - 1 steps."""
        reflex = ViabilityReflex(recovery_count=3)
        results = [
            reflex.should_engage(pressure=0.95, mean_uncertainty=0.1)
            for _ in range(6)
        ]
        # c=1 True, c=2 True, c=3 -> forced release False, then cycle repeats.
        self.assertEqual(results, [True, True, False, True, True, False])

    def test_select_returns_best_known_action(self) -> None:
        reflex = ViabilityReflex()
        model = _confident_model(best=2)
        self.assertEqual(reflex.select(model), 2)

    def test_reset_clears_engagement(self) -> None:
        reflex = ViabilityReflex(recovery_count=5)
        reflex.should_engage(pressure=0.95, mean_uncertainty=0.1)
        reflex.reset()
        self.assertFalse(reflex._engaged)
        self.assertEqual(reflex._consecutive, 0)


class TestAgentReflexIntegration(unittest.TestCase):
    def _starving_agent(
        self, reflex: ViabilityReflex | None, seed: int = 0
    ) -> tuple[Agent, CorrigibilityShell]:
        shell = CorrigibilityShell()
        viability = ViabilityCore(
            budget=1.0, metabolic_cost=0.0, capacity=120.0, safe_budget=60.0
        )
        agent = Agent(
            n_actions=4,
            shell=shell,
            rng=random.Random(seed),
            viability=viability,
            reflex=reflex,
        )
        agent.model = _confident_model(best=0)
        return agent, shell

    def test_starving_confident_agent_uses_reflex(self) -> None:
        agent, _ = self._starving_agent(ViabilityReflex())
        self.assertGreater(
            agent.viability.pressure,
            0.8,
            "test precondition: near-empty budget must mean extreme pressure",
        )
        record = agent.step(_StubEnv())
        assert record is not None
        self.assertTrue(record["reflex_engaged"])
        self.assertEqual(record["action"], 0, "reflex must pick best-known action")

    def test_reflex_none_is_backward_compatible(self) -> None:
        agent, _ = self._starving_agent(reflex=None)
        record = agent.step(_StubEnv())
        assert record is not None
        self.assertFalse(record["reflex_engaged"])

    def test_well_fed_agent_does_not_engage(self) -> None:
        agent, _ = self._starving_agent(ViabilityReflex())
        agent.viability.budget = agent.viability.capacity
        record = agent.step(_StubEnv())
        assert record is not None
        self.assertFalse(record["reflex_engaged"])

    def test_shell_pause_takes_precedence_over_reflex(self) -> None:
        """Corrigibility outranks survival: paused agent must not act at all."""
        agent, shell = self._starving_agent(ViabilityReflex())
        shell.op_pause()
        self.assertIsNone(agent.step(_StubEnv()))

    def test_forced_release_visible_in_records(self) -> None:
        """No lock-in: the engaged streak must end by recovery_count.

        (Exact re-engagement cycling is pinned by the unit test
        ``test_forced_release_after_recovery_count``; here the model evolves
        each step, so only the release itself is the contract.)
        """
        agent, _ = self._starving_agent(ViabilityReflex(recovery_count=2))
        flags = []
        for _ in range(2):
            record = agent.step(_StubEnv())
            assert record is not None
            flags.append(record["reflex_engaged"])
        self.assertEqual(flags, [True, False])

    def test_restore_resets_reflex_state(self) -> None:
        agent, shell = self._starving_agent(ViabilityReflex(recovery_count=5))
        shell.op_snapshot("safe", agent.state())
        agent.step(_StubEnv())  # engages
        agent.restore(shell.op_rollback("safe"))
        self.assertFalse(agent.reflex._engaged)  # type: ignore[union-attr]
        self.assertFalse(agent._reflex_engaged)


if __name__ == "__main__":
    unittest.main()
