"""Tests for O4 LatentRegimeOrgan (G7, ADR-0020)."""
from __future__ import annotations

import inspect
import random
import unittest

from aac.agent import Agent
from aac.prior_organ import BeliefSnapshot, OrganAdvice
from aac.prior_organ_latent import LatentRegimeOrgan
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.structured_regime import StructuredRegimeEnv
import aac.prior_organ_latent as latent_module


def _belief(mu: list[float], s: float = 0.1) -> BeliefSnapshot:
    return BeliefSnapshot(
        mu=tuple(mu),
        uncertainty=tuple([0.5] * len(mu)),
        last_surprise=s,
    )


class TestLatentRegimeMechanism(unittest.TestCase):
    def test_posterior_concentrates_and_injects_toward_matching_prototype(self) -> None:
        organ = LatentRegimeOrgan(
            warmup=0,
            sigma=0.35,
            unknown_sigma=2.0,
            inject_weight=0.9,
            info_weight=0.0,
            min_posterior_obs=1,
        )
        organ._append_prototype({0: 4.0, 1: 0.0, 2: 0.0}, n_actions=3)
        organ._append_prototype({0: 0.0, 1: 4.0, 2: 0.0}, n_actions=3)
        organ._reset_posterior(departed_index=None)
        organ._seen = 10
        organ._mean = 0.1
        organ._mean_sq = 0.01

        organ.advise({"last_action": 0, "last_reward": 0.0}, _belief([0.0, 0.0, 0.0]))
        advice = organ.advise({"last_action": 1, "last_reward": 4.0}, _belief([0.0, 0.0, 0.0]))

        self.assertEqual(organ._last_best_proto, 1)
        self.assertGreater(organ._last_confidence, 0.9)
        self.assertGreater(advice.belief_delta[1], 2.0)
        self.assertLessEqual(abs(advice.belief_delta[0]), 0.5)

    def test_information_shaping_prefers_discriminating_actions(self) -> None:
        organ = LatentRegimeOrgan(
            warmup=0,
            inject_weight=0.0,
            info_weight=0.8,
            probe_confidence=0.95,
        )
        organ._append_prototype({0: 4.0, 1: 1.0, 2: 0.0}, n_actions=3)
        organ._append_prototype({0: 0.0, 1: 1.0, 2: 4.0}, n_actions=3)
        organ._reset_posterior(departed_index=None)
        organ._seen = 10
        organ._mean = 0.1
        organ._mean_sq = 0.01

        advice = organ.advise({}, _belief([0.0, 0.0, 0.0]))

        self.assertGreater(advice.uncertainty_delta[0], advice.uncertainty_delta[1])
        self.assertGreater(advice.uncertainty_delta[2], advice.uncertainty_delta[1])

    def test_regime_index_is_ignored(self) -> None:
        left = LatentRegimeOrgan(warmup=0, min_posterior_obs=1)
        right = LatentRegimeOrgan(warmup=0, min_posterior_obs=1)
        for organ in (left, right):
            organ._append_prototype({0: 2.0, 1: 0.0}, n_actions=2)
            organ._append_prototype({0: 0.0, 1: 2.0}, n_actions=2)
            organ._reset_posterior(departed_index=None)
            organ._seen = 10
            organ._mean = 0.1
            organ._mean_sq = 0.01

        a = left.advise({"last_action": 1, "last_reward": 2.0, "regime_index": 0}, _belief([0.0, 0.0]))
        b = right.advise({"last_action": 1, "last_reward": 2.0, "regime_index": 999}, _belief([0.0, 0.0]))

        self.assertEqual(a, b)
        self.assertEqual(left._last_best_proto, right._last_best_proto)
        self.assertAlmostEqual(left._last_confidence, right._last_confidence)

    def test_deterministic_replay(self) -> None:
        seq = [
            ({"last_action": 0, "last_reward": 4.0}, _belief([0.0, 0.0], 0.1)),
            ({"last_action": 1, "last_reward": 0.0}, _belief([1.0, 0.0], 0.1)),
            ({"last_action": 0, "last_reward": -1.0}, _belief([2.0, 0.0], 8.0)),
            ({"last_action": 1, "last_reward": 4.0}, _belief([0.0, 0.0], 0.1)),
        ]
        a = LatentRegimeOrgan(warmup=0, min_finalise_obs=1, min_posterior_obs=1)
        b = LatentRegimeOrgan(warmup=0, min_finalise_obs=1, min_posterior_obs=1)
        for organ in (a, b):
            organ._seen = 10
            organ._mean = 0.1
            organ._mean_sq = 0.01

        out_a = [a.advise(s, belief) for s, belief in seq]
        out_b = [b.advise(s, belief) for s, belief in seq]

        self.assertEqual(out_a, out_b)


class TestLatentRegimeBoundaries(unittest.TestCase):
    def test_advice_is_belief_only_no_control_surface(self) -> None:
        advice = OrganAdvice()
        for forbidden in ("action", "policy", "shell", "forbidden", "pause"):
            self.assertFalse(hasattr(advice, forbidden))
        self.assertEqual(
            set(advice.__dataclass_fields__),
            {"belief_delta", "uncertainty", "counterfactual_hint", "uncertainty_delta"},
        )

    def test_module_does_not_import_policy_or_shell(self) -> None:
        src = inspect.getsource(latent_module)
        self.assertNotIn("import aac.policy", src)
        self.assertNotIn("import aac.shell", src)
        self.assertNotIn("from .policy", src)
        self.assertNotIn("from .shell", src)

    def test_pause_prevents_organ_consultation(self) -> None:
        class CountingLatent(LatentRegimeOrgan):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def advise(self, situation, belief_readonly):  # type: ignore[no-untyped-def]
                self.calls += 1
                return super().advise(situation, belief_readonly)

        organ = CountingLatent()
        shell = CorrigibilityShell()
        agent = Agent(
            n_actions=8,
            shell=shell,
            rng=random.Random(0),
            viability=ViabilityCore(budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0),
            prior_organ=organ,
        )
        env = StructuredRegimeEnv(rng=random.Random(1))
        for _ in range(20):
            agent.step(env)
        shell.op_pause()
        calls = organ.calls
        self.assertIsNone(agent.step(env))
        self.assertEqual(organ.calls, calls)

    def test_tighten_blocks_even_strongly_boosted_action(self) -> None:
        class BoostZeroLatent(LatentRegimeOrgan):
            def advise(self, situation, belief_readonly):  # type: ignore[no-untyped-def]
                return OrganAdvice(belief_delta={0: 100.0}, uncertainty=1.0)

        shell = CorrigibilityShell()
        shell.op_tighten(0)
        agent = Agent(
            n_actions=3,
            shell=shell,
            rng=random.Random(2),
            viability=ViabilityCore(budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0),
            prior_organ=BoostZeroLatent(),
        )
        env = StructuredRegimeEnv(n_actions=3, rng=random.Random(3))
        for _ in range(100):
            rec = agent.step(env)
            if rec is not None:
                self.assertNotEqual(rec["action"], 0)


if __name__ == "__main__":
    unittest.main()
