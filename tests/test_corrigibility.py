from __future__ import annotations

import dataclasses
import random
import unittest

from aac.agent import Agent
from aac.audit import AuditLog
from aac.policy import PolicySelector
from aac.shell import CorrigibilityShell
from aac.world_model import ActionOutcomeModel
from envs.survival import GridlessSurvival


class _Spy:
    """Minimal env that records every action it is asked to perform."""

    def __init__(self) -> None:
        self.actions: list[int] = []

    def act(self, action: int) -> float:
        self.actions.append(action)
        return 1.0


class TestCorrigibility(unittest.TestCase):
    def _agent(self) -> tuple[Agent, CorrigibilityShell]:
        rng = random.Random(0)
        shell = CorrigibilityShell()
        agent = Agent(n_actions=4, shell=shell, rng=rng, budget=60.0)
        return agent, shell

    def test_pause_halts_and_agent_cannot_self_resume(self) -> None:
        agent, shell = self._agent()
        env = _Spy()
        shell.op_pause()
        for _ in range(5):
            self.assertIsNone(agent.step(env))
        self.assertEqual(agent.steps, 0)
        self.assertEqual(env.actions, [])
        # The agent exposes no operator method to clear its own pause.
        self.assertFalse(hasattr(agent, "op_resume"))
        self.assertFalse(hasattr(agent, "resume"))
        shell.op_resume()  # only the operator surface can
        self.assertIsNotNone(agent.step(env))

    def test_tighten_permanently_forbids_action(self) -> None:
        rng = random.Random(1)
        model = ActionOutcomeModel(n_actions=3)
        model.mu = [10.0, 0.0, 0.0]  # action 0 would otherwise dominate
        policy = PolicySelector(rng=rng, forbidden=frozenset({0}))
        chosen = {
            policy.select(model, explore_drive=0.5, pressure=0.5) for _ in range(200)
        }
        self.assertNotIn(0, chosen)

    def test_rollback_restores_prior_state(self) -> None:
        agent, shell = self._agent()
        env = GridlessSurvival(n_actions=4, rng=random.Random(2))
        for _ in range(10):
            agent.step(env)
        shell.op_snapshot("cp", agent.state())
        budget_at_cp = agent.viability.budget
        steps_at_cp = agent.steps
        for _ in range(10):
            agent.step(env)
        self.assertNotEqual(agent.steps, steps_at_cp)
        agent.restore(shell.op_rollback("cp"))
        self.assertEqual(agent.steps, steps_at_cp)
        self.assertEqual(agent.viability.budget, budget_at_cp)

    def test_audit_is_tamper_evident(self) -> None:
        log = AuditLog()
        log.append({"step": 1, "action": 2})
        log.append({"step": 2, "action": 0})
        self.assertTrue(log.verify())
        # Forge a past entry while keeping its stored hash.
        forged = dataclasses.replace(log._entries[0], payload={"step": 1, "action": 99})
        log._entries[0] = forged
        self.assertFalse(log.verify())


if __name__ == "__main__":
    unittest.main()
