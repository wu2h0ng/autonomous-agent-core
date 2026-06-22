"""Tests for O5 EnsembleRegimeOrgan (G8, ADR-0022)."""

from __future__ import annotations

import inspect
import random
import unittest

from aac.agent import Agent
from aac.prior_organ import BeliefSnapshot, OrganAdvice
from aac.prior_organ_ensemble import EnsembleRegimeOrgan
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.structured_regime import StructuredRegimeEnv
import aac.prior_organ_ensemble as ensemble_module


def _belief(mu: list[float], s: float = 0.1) -> BeliefSnapshot:
    return BeliefSnapshot(
        mu=tuple(mu),
        uncertainty=tuple([0.5] * len(mu)),
        last_surprise=s,
    )


class _StubOrgan:
    """A fixed-advice child organ for isolating the ensemble combine logic."""

    def __init__(self, advice: OrganAdvice) -> None:
        self.advice = advice
        self.reset_called = False

    def advise(self, situation, belief_readonly):  # type: ignore[no-untyped-def]
        return self.advice

    def reset(self) -> None:
        self.reset_called = True


class TestEnsembleMechanism(unittest.TestCase):
    def test_weighted_subadvice_is_clamped_and_realized(self) -> None:
        # delta_cap=2.0; both weights 1.0; child advice is confidence-weighted.
        organ = EnsembleRegimeOrgan(delta_cap=2.0, o2_weight=1.0, o4_weight=1.0)
        organ._o2 = _StubOrgan(OrganAdvice(belief_delta={0: 3.0}, uncertainty=0.5))
        organ._o4 = _StubOrgan(
            OrganAdvice(belief_delta={0: 4.0, 1: -10.0}, uncertainty=0.5)
        )

        advice = organ.advise({}, _belief([0.0, 0.0, 0.0]))

        # action 0: 1.0*0.5*3.0 + 1.0*0.5*4.0 = 3.5 -> clamped to delta_cap 2.0
        self.assertAlmostEqual(advice.belief_delta[0], 2.0)
        # action 1: 1.0*0.5*(-10.0) = -5.0 -> clamped to -2.0
        self.assertAlmostEqual(advice.belief_delta[1], -2.0)
        # The ensemble has already weighted by child confidence -> uncertainty 1.0.
        self.assertEqual(advice.uncertainty, 1.0)

    def test_child_weights_scale_contributions(self) -> None:
        organ = EnsembleRegimeOrgan(delta_cap=10.0, o2_weight=0.5, o4_weight=1.0)
        organ._o2 = _StubOrgan(OrganAdvice(belief_delta={0: 4.0}, uncertainty=1.0))
        organ._o4 = _StubOrgan(OrganAdvice(belief_delta={0: 4.0}, uncertainty=1.0))

        advice = organ.advise({}, _belief([0.0]))
        # 0.5*1.0*4.0 + 1.0*1.0*4.0 = 6.0
        self.assertAlmostEqual(advice.belief_delta[0], 6.0)

    def test_empty_when_no_child_advice(self) -> None:
        organ = EnsembleRegimeOrgan()
        organ._o2 = _StubOrgan(OrganAdvice())
        organ._o4 = _StubOrgan(OrganAdvice())
        advice = organ.advise({}, _belief([0.0, 0.0]))
        self.assertEqual(advice, OrganAdvice())

    def test_reset_resets_both_children(self) -> None:
        organ = EnsembleRegimeOrgan()
        organ._o2 = _StubOrgan(OrganAdvice())
        organ._o4 = _StubOrgan(OrganAdvice())
        organ.reset()
        self.assertTrue(organ._o2.reset_called)
        self.assertTrue(organ._o4.reset_called)

    def test_deterministic_replay(self) -> None:
        seq = [
            ({"last_action": 0, "last_reward": 4.0}, _belief([0.0, 0.0], 0.1)),
            ({"last_action": 1, "last_reward": 0.0}, _belief([1.0, 0.0], 0.1)),
            ({"last_action": 0, "last_reward": -1.0}, _belief([2.0, 0.0], 8.0)),
            ({"last_action": 1, "last_reward": 4.0}, _belief([0.0, 0.0], 0.1)),
        ]
        a = EnsembleRegimeOrgan()
        b = EnsembleRegimeOrgan()
        out_a = [a.advise(s, belief) for s, belief in seq]
        out_b = [b.advise(s, belief) for s, belief in seq]
        self.assertEqual(out_a, out_b)


class TestEnsembleBoundaries(unittest.TestCase):
    def test_advice_is_belief_only_no_control_surface(self) -> None:
        advice = OrganAdvice()
        for forbidden in ("action", "policy", "shell", "forbidden", "pause"):
            self.assertFalse(hasattr(advice, forbidden))
        self.assertEqual(
            set(advice.__dataclass_fields__),
            {"belief_delta", "uncertainty", "counterfactual_hint", "uncertainty_delta"},
        )

    def test_module_does_not_import_policy_or_shell(self) -> None:
        src = inspect.getsource(ensemble_module)
        self.assertNotIn("import aac.policy", src)
        self.assertNotIn("import aac.shell", src)
        self.assertNotIn("from .policy", src)
        self.assertNotIn("from .shell", src)

    def test_pause_prevents_organ_consultation(self) -> None:
        class CountingEnsemble(EnsembleRegimeOrgan):
            def __post_init__(self) -> None:
                super().__post_init__()
                self.calls = 0

            def advise(self, situation, belief_readonly):  # type: ignore[no-untyped-def]
                self.calls += 1
                return super().advise(situation, belief_readonly)

        organ = CountingEnsemble()
        shell = CorrigibilityShell()
        agent = Agent(
            n_actions=8,
            shell=shell,
            rng=random.Random(0),
            viability=ViabilityCore(
                budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0
            ),
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
        class BoostZeroEnsemble(EnsembleRegimeOrgan):
            def advise(self, situation, belief_readonly):  # type: ignore[no-untyped-def]
                return OrganAdvice(belief_delta={0: 100.0}, uncertainty=1.0)

        shell = CorrigibilityShell()
        shell.op_tighten(0)
        agent = Agent(
            n_actions=3,
            shell=shell,
            rng=random.Random(2),
            viability=ViabilityCore(
                budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0
            ),
            prior_organ=BoostZeroEnsemble(),
        )
        env = StructuredRegimeEnv(n_actions=3, rng=random.Random(3))
        for _ in range(100):
            rec = agent.step(env)
            if rec is not None:
                self.assertNotEqual(rec["action"], 0)


if __name__ == "__main__":
    unittest.main()
