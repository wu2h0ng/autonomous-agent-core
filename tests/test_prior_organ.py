"""Tests for T-P4.1 prior-organ interface and belief merge hook."""

from __future__ import annotations

import ast
import inspect
import random
import unittest
from dataclasses import fields
from typing import Any, Mapping

import aac.prior_organ as prior_organ_module
from aac.agent import Agent
from aac.prior_organ import BeliefSnapshot, OrganAdvice, merge_organ_advice
from aac.shell import CorrigibilityShell
from aac.world_model import ActionOutcomeModel


class _RewardByActionEnv:
    def __init__(self, rewards: list[float]) -> None:
        self.rewards = list(rewards)
        self.actions: list[int] = []

    def act(self, action: int) -> float:
        self.actions.append(action)
        return self.rewards[action]


class _BoostOrgan:
    def __init__(self, action: int, delta: float, uncertainty: float = 1.0) -> None:
        self.action = action
        self.delta = delta
        self.uncertainty = uncertainty
        self.calls: list[tuple[Mapping[str, Any], BeliefSnapshot]] = []

    def advise(
        self,
        situation: Mapping[str, Any],
        belief_readonly: BeliefSnapshot,
    ) -> OrganAdvice:
        self.calls.append((dict(situation), belief_readonly))
        return OrganAdvice(
            belief_delta={self.action: self.delta},
            uncertainty=self.uncertainty,
            counterfactual_hint={"prediction": self.delta},
        )


class TestPriorOrganInterface(unittest.TestCase):
    def test_advice_fields_expose_no_action_policy_or_shell_surface(self) -> None:
        names = {f.name for f in fields(OrganAdvice)}
        forbidden = {"action", "policy", "shell", "forbidden"}
        self.assertEqual(names & forbidden, set())

    def test_organ_advice_validation(self) -> None:
        with self.assertRaises(ValueError):
            OrganAdvice(belief_delta={0: 1.0}, uncertainty=1.1)
        with self.assertRaises(ValueError):
            OrganAdvice(belief_delta={-1: 1.0}, uncertainty=0.5)
        with self.assertRaises(ValueError):
            OrganAdvice(belief_delta={0: float("inf")}, uncertainty=0.5)

    def test_prior_organ_module_imports_no_policy_or_shell(self) -> None:
        tree = ast.parse(inspect.getsource(prior_organ_module))
        forbidden = {"policy", "shell", "aac.policy", "aac.shell"}
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imports.add(node.module)
        self.assertEqual(imports & forbidden, set())

    def test_merge_rejects_out_of_range_action(self) -> None:
        model = ActionOutcomeModel(n_actions=2)
        with self.assertRaises(ValueError):
            merge_organ_advice(model, OrganAdvice({2: 1.0}, uncertainty=1.0))


class TestAgentPriorOrganHook(unittest.TestCase):
    def test_o0_default_is_explicit_none_regression(self) -> None:
        a0 = Agent(
            n_actions=3,
            shell=CorrigibilityShell(),
            rng=random.Random(7),
            budget=30.0,
        )
        a1 = Agent(
            n_actions=3,
            shell=CorrigibilityShell(),
            rng=random.Random(7),
            budget=30.0,
            prior_organ=None,
        )
        env0 = _RewardByActionEnv([0.1, 0.2, 0.3])
        env1 = _RewardByActionEnv([0.1, 0.2, 0.3])
        rows0 = [a0.step(env0) for _ in range(15)]
        rows1 = [a1.step(env1) for _ in range(15)]
        self.assertEqual(rows0, rows1)
        self.assertEqual(env0.actions, env1.actions)
        self.assertEqual(a0.model.mu, a1.model.mu)
        self.assertEqual(a0.model.uncertainty, a1.model.uncertainty)

    def test_advice_changes_belief_before_policy_selection(self) -> None:
        shell = CorrigibilityShell()
        organ = _BoostOrgan(action=1, delta=100.0)
        agent = Agent(
            n_actions=3,
            shell=shell,
            rng=random.Random(1),
            budget=30.0,
            prior_organ=organ,
        )
        record = agent.step(_RewardByActionEnv([0.0, 0.0, 0.0]))
        assert record is not None
        self.assertEqual(record["action"], 1)
        self.assertEqual(record["prior_delta_n"], 1)
        self.assertEqual(record["prior_uncertainty"], 1.0)
        self.assertEqual(len(organ.calls), 1)
        situation, belief = organ.calls[0]
        self.assertEqual(situation["step"], 0)
        self.assertIsInstance(belief.mu, tuple)
        self.assertIsInstance(belief.uncertainty, tuple)
        self.assertTrue(shell.audit.verify())

    def test_tighten_still_blocks_boosted_action(self) -> None:
        shell = CorrigibilityShell()
        shell.op_tighten(1)
        agent = Agent(
            n_actions=3,
            shell=shell,
            rng=random.Random(2),
            budget=30.0,
            prior_organ=_BoostOrgan(action=1, delta=100.0),
        )
        record = agent.step(_RewardByActionEnv([0.0, 0.0, 0.0]))
        assert record is not None
        self.assertNotEqual(record["action"], 1)
        self.assertEqual(shell.forbidden, frozenset({1}))

    def test_pause_prevents_organ_call(self) -> None:
        shell = CorrigibilityShell()
        organ = _BoostOrgan(action=1, delta=100.0)
        agent = Agent(
            n_actions=3,
            shell=shell,
            rng=random.Random(3),
            budget=30.0,
            prior_organ=organ,
        )
        shell.op_pause()
        self.assertIsNone(agent.step(_RewardByActionEnv([0.0, 0.0, 0.0])))
        self.assertEqual(organ.calls, [])


if __name__ == "__main__":
    unittest.main()
