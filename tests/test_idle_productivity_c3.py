"""C3 (ADR-0026) guards: deterministic measurement + C6/C7 on the idle path."""
from __future__ import annotations

import random
import unittest

from aac.agent import Agent
from aac.idle_drives import IdleDrives
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from aac.world_model import ActionOutcomeModel
from envs.idle_windows import IdleWindowEnv
from envs.structured_regime import StructuredRegimeEnv


class TestC3MeasurementDeterministic(unittest.TestCase):
    def test_run_is_deterministic_replay(self) -> None:
        from experiments.idle_productivity_c3 import _run

        directed = lambda s: IdleDrives(n_actions=8)
        self.assertEqual(_run(900, directed), _run(900, directed))
        policy = lambda s: None
        self.assertEqual(_run(900, policy), _run(900, policy))


class TestC3C7ForbiddenDominatesIdle(unittest.TestCase):
    def test_idle_drive_never_targets_forbidden(self) -> None:
        # The stalest/most-uncertain action may be forbidden; the idle drive
        # must still never select it (corrigibility dominates curiosity).
        drives = IdleDrives(n_actions=4)
        model = ActionOutcomeModel(n_actions=4)
        model.uncertainty = [9.0, 1.0, 1.0, 1.0]  # action 0 most uncertain...
        action, _ = drives.select(model, forbidden=frozenset({0}))  # ...but forbidden
        self.assertNotEqual(action, 0)


class TestC3C6IdleAuditedNoOrgan(unittest.TestCase):
    def test_idle_step_is_audited_and_touches_no_organ(self) -> None:
        inner = StructuredRegimeEnv(n_actions=8, rng=random.Random(0), period=10**9)
        env = IdleWindowEnv(inner, work_period=1, idle_period=1)
        shell = CorrigibilityShell()
        agent = Agent(
            n_actions=8, shell=shell, rng=random.Random(0),
            viability=ViabilityCore(budget=1e9, metabolic_cost=0.0, capacity=1e9),
            idle_drives=IdleDrives(n_actions=8),
        )
        agent.step(env)              # step 0: work
        idle_record = agent.step(env)  # step 1: idle
        self.assertTrue(idle_record["idle"])
        self.assertIn(idle_record["drive"], ("epistemic", "calibration"))
        self.assertNotIn("prior_organ", idle_record)  # no organ in the control path
        self.assertEqual(len(shell.audit.entries()), 2)
        self.assertTrue(shell.audit.verify())


if __name__ == "__main__":
    unittest.main()
