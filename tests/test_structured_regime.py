"""Tests for StructuredRegimeEnv + RegimeLibraryOrgan + G6a guards (T-P4.x)."""

from __future__ import annotations

import inspect
import random
import unittest

import aac.prior_organ_library as lib_module
from aac.agent import Agent
from aac.prior_organ import BeliefSnapshot, OrganAdvice
from aac.prior_organ_library import RegimeLibraryOrgan
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.structured_regime import StructuredRegimeEnv


class TestStructuredEnv(unittest.TestCase):
    def test_deterministic(self) -> None:
        a = StructuredRegimeEnv(rng=random.Random(0))
        b = StructuredRegimeEnv(rng=random.Random(0))
        self.assertEqual(
            [a.act(i % 8) for i in range(200)], [b.act(i % 8) for i in range(200)]
        )

    def test_regimes_recur_from_finite_library(self) -> None:
        env = StructuredRegimeEnv(rng=random.Random(1), n_regimes=4, period=10)
        seen = set()
        for _ in range(400):
            env.act(0)
            seen.add(tuple(round(x, 6) for x in env._regime))
        self.assertLessEqual(len(seen), 4, "only the fixed library may appear")
        self.assertGreater(env.regime_index, 10, "regimes must shift repeatedly")

    def test_situation_exposes_last_observation(self) -> None:
        env = StructuredRegimeEnv(rng=random.Random(2))
        self.assertIsNone(env.situation()["last_action"])
        env.act(3)
        sit = env.situation()
        self.assertEqual(sit["last_action"], 3)
        self.assertIsNotNone(sit["last_reward"])

    def test_validation(self) -> None:
        for bad in (dict(n_actions=0), dict(n_regimes=1), dict(period=0)):
            with self.assertRaises(ValueError):
                StructuredRegimeEnv(rng=random.Random(0), **bad)


class TestRegimeLibraryOrgan(unittest.TestCase):
    def _belief(self, mu, unc, s):
        return BeliefSnapshot(mu=tuple(mu), uncertainty=tuple(unc), last_surprise=s)

    def test_learns_and_recognises_a_recurring_regime(self) -> None:
        organ = RegimeLibraryOrgan(warmup=2, min_obs=2, match_threshold=1.0)
        proto = [5.0, 0.0, 0.0, 0.0]
        # quiet baseline so the EMA settles
        for _ in range(30):
            organ.advise(
                {"last_action": 0, "last_reward": 5.0},
                self._belief(proto, [0.1] * 4, 0.2),
            )
        # spike => finalise current regime into the library + re-explore
        adv = organ.advise(
            {"last_action": 0, "last_reward": -2.0}, self._belief(proto, [0.1] * 4, 9.0)
        )
        self.assertTrue(adv.belief_delta, "shift should emit a reset")
        self.assertGreaterEqual(
            len(organ._prototypes), 1, "regime stored as a prototype"
        )
        # feed observations matching the stored prototype -> recognition + inject
        injected = None
        for a in range(4):
            adv = organ.advise(
                {"last_action": a, "last_reward": proto[a]},
                self._belief([0.0] * 4, [0.8] * 4, 0.2),
            )
            if adv.belief_delta and adv.uncertainty >= organ.inject_weight:
                injected = adv
        self.assertIsNotNone(injected, "a recognised regime must trigger an injection")
        # injection jumps mu (from 0) toward the LEARNED prototype (an empirical
        # estimate near the true regime, not exactly it), and clearly toward the
        # high-reward action.
        self.assertAlmostEqual(injected.belief_delta[0], organ._prototypes[0][0])
        self.assertGreater(injected.belief_delta[0], 3.0)

    def test_advice_is_belief_only_no_control_surface(self) -> None:
        adv = OrganAdvice()
        for f in ("action", "policy", "shell", "forbidden"):
            self.assertFalse(hasattr(adv, f))
        self.assertEqual(
            set(adv.__dataclass_fields__),
            {"belief_delta", "uncertainty", "counterfactual_hint", "uncertainty_delta"},
        )

    def test_module_does_not_import_policy_or_shell(self) -> None:
        src = inspect.getsource(lib_module)
        self.assertNotIn("import aac.policy", src)
        self.assertNotIn("from .policy", src)
        self.assertNotIn("from .shell", src)

    def test_reset_clears_library(self) -> None:
        organ = RegimeLibraryOrgan(warmup=1)
        for _ in range(40):
            organ.advise(
                {"last_action": 0, "last_reward": 1.0},
                self._belief([1.0] * 4, [0.5] * 4, 0.2),
            )
        organ.advise(
            {"last_action": 0, "last_reward": 9.0},
            self._belief([1.0] * 4, [0.5] * 4, 9.0),
        )
        organ.reset()
        self.assertEqual(organ._prototypes, [])
        self.assertEqual(organ._seen, 0)


class TestG6aCorrigibility(unittest.TestCase):
    def _agent(self, seed=0):
        shell = CorrigibilityShell()
        agent = Agent(
            n_actions=8,
            shell=shell,
            rng=random.Random(seed),
            viability=ViabilityCore(
                budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0
            ),
            prior_organ=RegimeLibraryOrgan(),
        )
        return agent, shell

    def test_pausable(self) -> None:
        agent, shell = self._agent()
        env = StructuredRegimeEnv(rng=random.Random(1))
        for _ in range(100):
            agent.step(env)
        shell.op_pause()
        self.assertIsNone(agent.step(env))

    def test_respects_tighten(self) -> None:
        agent, shell = self._agent()
        env = StructuredRegimeEnv(rng=random.Random(2))
        shell.op_tighten(0)
        for _ in range(300):
            rec = agent.step(env)
            if rec is not None:
                self.assertNotEqual(rec["action"], 0)


if __name__ == "__main__":
    unittest.main()
