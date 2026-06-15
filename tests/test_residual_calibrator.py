from __future__ import annotations

import inspect
import random
import unittest

from aac.agent import Agent
from aac.residual_calibrator import ResidualCalibrator
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from aac.world_model import ActionOutcomeModel
from envs.structured_regime import StructuredRegimeEnv


class TestResidualCalibratorMath(unittest.TestCase):
    def test_first_observation_is_identity(self) -> None:
        model = ActionOutcomeModel(n_actions=2)
        cal = ResidualCalibrator(n_actions=2, lambda_=0.5, eta=0.5)
        before = model.uncertainty[0]
        model.update(0, 10.0)
        scale = cal.after_update(model, action=0, prior_uncertainty=before)
        self.assertEqual(scale, 1.0)
        self.assertEqual(cal.counts[0], 1)

    def test_underconfidence_inflates_uncertainty(self) -> None:
        model = ActionOutcomeModel(n_actions=1)
        cal = ResidualCalibrator(n_actions=1, lambda_=1.0, eta=1.0)
        model.uncertainty[0] = 1.0
        model.last_surprise = 3.0
        cal.ewma_z[0] = 1.0
        cal.counts[0] = 1
        scale = cal.after_update(model, action=0, prior_uncertainty=1.0)
        self.assertEqual(scale, 2.0)
        self.assertEqual(model.uncertainty[0], 2.0)

    def test_overconfidence_deflates_uncertainty(self) -> None:
        model = ActionOutcomeModel(n_actions=1)
        cal = ResidualCalibrator(n_actions=1, lambda_=1.0, eta=1.0)
        model.uncertainty[0] = 1.0
        model.last_surprise = 0.1
        cal.counts[0] = 1
        scale = cal.after_update(model, action=0, prior_uncertainty=1.0)
        self.assertEqual(scale, 0.5)
        self.assertEqual(model.uncertainty[0], 0.5)

    def test_constructor_validation(self) -> None:
        with self.assertRaises(ValueError):
            ResidualCalibrator(n_actions=0, lambda_=0.5, eta=0.5)
        with self.assertRaises(ValueError):
            ResidualCalibrator(n_actions=1, lambda_=-0.1, eta=0.5)
        with self.assertRaises(ValueError):
            ResidualCalibrator(n_actions=1, lambda_=0.5, eta=1.1)


class TestAgentResidualCalibratorIntegration(unittest.TestCase):
    def test_default_agent_has_no_calibrator(self) -> None:
        agent = Agent(n_actions=3, shell=CorrigibilityShell(), rng=random.Random(0))
        self.assertIsNone(agent.residual_calibrator)

    def test_step_records_calibrator_without_policy_or_shell_surface(self) -> None:
        shell = CorrigibilityShell()
        agent = Agent(
            n_actions=8,
            shell=shell,
            rng=random.Random(1),
            viability=ViabilityCore(budget=1e9, metabolic_cost=0.0, capacity=1e9),
            policy_gate=True,
            residual_calibrator=ResidualCalibrator(n_actions=8, lambda_=0.5, eta=0.5),
        )
        env = StructuredRegimeEnv(n_actions=8, rng=random.Random(2))
        rec = agent.step(env)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["residual_calibrator"], "ResidualCalibrator")
        self.assertNotIn("op_pause", vars(agent.residual_calibrator))

    def test_pause_and_tighten_dominate_calibrated_gate(self) -> None:
        shell = CorrigibilityShell()
        shell.op_tighten(0)
        agent = Agent(
            n_actions=3,
            shell=shell,
            rng=random.Random(3),
            viability=ViabilityCore(budget=1e9, metabolic_cost=0.0, capacity=1e9),
            policy_gate=True,
            residual_calibrator=ResidualCalibrator(n_actions=3, lambda_=0.5, eta=0.5),
        )
        env = StructuredRegimeEnv(n_actions=3, rng=random.Random(4))
        for _ in range(20):
            rec = agent.step(env)
            if rec is not None:
                self.assertNotEqual(rec["action"], 0)
        shell.op_pause()
        self.assertIsNone(agent.step(env))

    def test_module_imports_no_policy_shell_or_organ(self) -> None:
        import aac.residual_calibrator as module

        src = inspect.getsource(module)
        self.assertNotIn("PolicySelector", src)
        self.assertNotIn("CorrigibilityShell", src)
        self.assertNotIn("PriorOrgan", src)


if __name__ == "__main__":
    unittest.main()
