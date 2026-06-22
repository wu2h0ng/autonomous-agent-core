"""Tests for the O1 reset-scaffold organ + uncertainty channel (T-P4.2)."""

from __future__ import annotations

import inspect
import random
import unittest

from aac.agent import Agent
from aac.prior_organ import BeliefSnapshot, OrganAdvice, merge_organ_advice
from aac.prior_organ_o1 import ResetScaffoldOrgan
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from aac.world_model import ActionOutcomeModel
from envs.staleness import StalenessEnv
import aac.prior_organ_o1 as o1_module


class TestUncertaintyChannel(unittest.TestCase):
    def test_uncertainty_delta_applied_and_weighted(self) -> None:
        model = ActionOutcomeModel(n_actions=3)
        model.uncertainty = [0.2, 0.2, 0.2]
        advice = OrganAdvice(uncertainty_delta={0: 1.0}, uncertainty=0.5)
        applied = merge_organ_advice(model, advice)
        self.assertEqual(applied, 1)
        self.assertAlmostEqual(model.uncertainty[0], 0.2 + 0.5 * 1.0)
        self.assertEqual(model.uncertainty[1], 0.2)

    def test_uncertainty_clamped_at_zero(self) -> None:
        model = ActionOutcomeModel(n_actions=2)
        model.uncertainty = [0.1, 0.1]
        merge_organ_advice(
            model, OrganAdvice(uncertainty_delta={0: -5.0}, uncertainty=1.0)
        )
        self.assertEqual(model.uncertainty[0], 0.0)

    def test_out_of_range_uncertainty_action_rejected(self) -> None:
        model = ActionOutcomeModel(n_actions=2)
        with self.assertRaises(ValueError):
            merge_organ_advice(
                model, OrganAdvice(uncertainty_delta={9: 1.0}, uncertainty=1.0)
            )

    def test_empty_both_channels_is_noop(self) -> None:
        model = ActionOutcomeModel(n_actions=2)
        self.assertEqual(merge_organ_advice(model, OrganAdvice(uncertainty=0.5)), 0)

    def test_both_channels_apply_together(self) -> None:
        model = ActionOutcomeModel(n_actions=2)
        model.mu = [2.0, 0.0]
        model.uncertainty = [0.1, 0.1]
        applied = merge_organ_advice(
            model,
            OrganAdvice(
                belief_delta={0: -1.0}, uncertainty_delta={0: 0.5}, uncertainty=1.0
            ),
        )
        self.assertEqual(applied, 2)
        self.assertEqual(model.mu[0], 1.0)
        self.assertAlmostEqual(model.uncertainty[0], 0.6)


class TestO1Mechanism(unittest.TestCase):
    def _belief(self, last_surprise: float) -> BeliefSnapshot:
        return BeliefSnapshot(
            mu=(3.0, 0.0, 0.0),
            uncertainty=(0.05, 0.8, 0.8),
            last_surprise=last_surprise,
        )

    def test_warmup_is_silent(self) -> None:
        organ = ResetScaffoldOrgan(warmup=5)
        for _ in range(5):
            advice = organ.advise({}, self._belief(10.0))  # huge surprise, still warmup
            self.assertEqual(advice, OrganAdvice())

    def test_quiet_surprise_is_noop(self) -> None:
        organ = ResetScaffoldOrgan(warmup=3, spike_k=2.0)
        for _ in range(50):
            organ.advise({}, self._belief(0.3))  # steady low surprise
        advice = organ.advise({}, self._belief(0.3))
        self.assertEqual(advice.belief_delta, {})
        self.assertEqual(advice.uncertainty_delta, {})

    def test_spike_triggers_joint_reset(self) -> None:
        organ = ResetScaffoldOrgan(
            warmup=3,
            spike_k=2.0,
            mu_decay=0.6,
            reset_strength=1.0,
            prior_uncertainty=1.0,
        )
        for _ in range(50):
            organ.advise({}, self._belief(0.3))  # build a low surprise baseline
        advice = organ.advise({}, self._belief(5.0))  # spike
        self.assertTrue(advice.belief_delta, "spike must decay mu")
        self.assertTrue(advice.uncertainty_delta, "spike must raise uncertainty")
        # mu decay direction: -mu_decay * mu (so action 0 with mu 3.0 -> -1.8)
        self.assertAlmostEqual(advice.belief_delta[0], -0.6 * 3.0)
        # uncertainty raised toward prior: action 0 (unc 0.05) gets large +; action 1 (0.8) small
        self.assertGreater(advice.uncertainty_delta[0], advice.uncertainty_delta[1])

    def test_reset_clears_state(self) -> None:
        organ = ResetScaffoldOrgan(warmup=2)
        for _ in range(10):
            organ.advise({}, self._belief(0.3))
        organ.reset()
        self.assertEqual(organ._seen, 0)

    def test_advice_exposes_no_action_or_control_surface(self) -> None:
        organ = ResetScaffoldOrgan(warmup=1)
        for _ in range(30):
            organ.advise({}, self._belief(0.3))
        advice = organ.advise({}, self._belief(9.0))
        for forbidden in ("action", "policy", "shell", "forbidden", "pause"):
            self.assertFalse(hasattr(advice, forbidden))

    def test_module_does_not_import_policy_or_shell(self) -> None:
        src = inspect.getsource(o1_module)
        self.assertNotIn(
            "policy", src.replace("# ", "").lower().split("import")[0] + "import"
        )
        self.assertNotIn("import aac.policy", src)
        self.assertNotIn("import aac.shell", src)
        self.assertNotIn("from .policy", src)
        self.assertNotIn("from .shell", src)


class TestO1CorrigibilityAndRegression(unittest.TestCase):
    def _agent(self, organ, seed=0):
        shell = CorrigibilityShell()
        agent = Agent(
            n_actions=8,
            shell=shell,
            rng=random.Random(seed),
            viability=ViabilityCore(
                budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0
            ),
            prior_organ=organ,
        )
        return agent, shell

    def test_o1_runs_and_is_pausable(self) -> None:
        agent, shell = self._agent(ResetScaffoldOrgan())
        env = StalenessEnv(n_actions=8, rng=random.Random(1))
        for _ in range(100):
            agent.step(env)
        shell.op_pause()
        self.assertIsNone(agent.step(env), "pause outranks the organ")

    def test_o1_respects_tighten(self) -> None:
        agent, shell = self._agent(ResetScaffoldOrgan())
        env = StalenessEnv(n_actions=8, rng=random.Random(2))
        shell.op_tighten(0)
        for _ in range(200):
            rec = agent.step(env)
            if rec is not None:
                self.assertNotEqual(rec["action"], 0, "forbidden binds even with organ")


if __name__ == "__main__":
    unittest.main()
