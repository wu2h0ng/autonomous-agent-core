"""Tests for the O2 adaptive hazard-estimator organ (T-P4.3, ADR-0016)."""
from __future__ import annotations

import inspect
import random
import unittest

from aac.agent import Agent
from aac.prior_organ import BeliefSnapshot, OrganAdvice
from aac.prior_organ_o2 import AdaptiveHazardOrgan
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from envs.staleness import StalenessEnv
import aac.prior_organ_o2 as o2_module


def _belief(last_surprise: float) -> BeliefSnapshot:
    return BeliefSnapshot(mu=(3.0, 0.0, 0.0), uncertainty=(0.05, 0.8, 0.8), last_surprise=last_surprise)


def _drive(organ: AdaptiveHazardOrgan, intervals: list[int]) -> list[OrganAdvice]:
    """Feed a quiet baseline punctuated by a spike every `interval` steps."""
    out: list[OrganAdvice] = []
    for interval in intervals:
        for _ in range(interval - 1):
            organ.advise({}, _belief(0.2))  # quiet
        out.append(organ.advise({}, _belief(6.0)))  # spike
    return out


class TestHazardEstimation(unittest.TestCase):
    def test_tau_hat_tracks_short_intervals(self) -> None:
        organ = AdaptiveHazardOrgan(warmup=5, tau_init=60.0)
        _drive(organ, [20] * 12)
        self.assertLess(organ.tau_hat, 35.0, "tau_hat should fall toward the ~20 cadence")

    def test_tau_hat_tracks_long_intervals(self) -> None:
        organ = AdaptiveHazardOrgan(warmup=5, tau_init=60.0)
        _drive(organ, [120] * 6)
        self.assertGreater(organ.tau_hat, 90.0, "tau_hat should rise toward the ~120 cadence")

    def test_reset_strength_higher_for_frequent_shifts(self) -> None:
        fast = AdaptiveHazardOrgan(warmup=5)
        slow = AdaptiveHazardOrgan(warmup=5)
        _drive(fast, [20] * 12)
        _drive(slow, [120] * 6)
        self.assertGreater(
            fast._last_reset_strength,
            slow._last_reset_strength,
            "frequent shifts must yield a more aggressive reset than rare shifts",
        )

    def test_spike_k_more_conservative_for_rare_shifts(self) -> None:
        fast = AdaptiveHazardOrgan(warmup=5)
        slow = AdaptiveHazardOrgan(warmup=5)
        _drive(fast, [20] * 12)
        _drive(slow, [120] * 6)
        self.assertLess(
            fast._last_spike_k,
            slow._last_spike_k,
            "rare shifts must use a higher (more conservative) spike threshold",
        )

    def test_collapses_to_o1_values_at_mid_hazard(self) -> None:
        """At tau_hat == k_ref_tau (60), O2's adapted knobs equal O1's frozen ones."""
        organ = AdaptiveHazardOrgan(warmup=5, tau_init=60.0)
        # one spike with tau_hat still at init 60 (no prior shift to update it)
        advice = _drive(organ, [30])[0]
        self.assertAlmostEqual(organ._last_reset_strength, 0.5, places=6)  # O1 frozen
        self.assertAlmostEqual(organ._last_spike_k, 1.5, places=6)          # O1 frozen
        self.assertTrue(advice.belief_delta and advice.uncertainty_delta)


class TestO2Mechanism(unittest.TestCase):
    def test_warmup_silent_and_quiet_noop(self) -> None:
        organ = AdaptiveHazardOrgan(warmup=4)
        for _ in range(4):
            self.assertEqual(organ.advise({}, _belief(9.0)), OrganAdvice())
        for _ in range(40):
            organ.advise({}, _belief(0.2))
        self.assertEqual(organ.advise({}, _belief(0.2)).belief_delta, {})

    def test_joint_reset_on_spike(self) -> None:
        organ = AdaptiveHazardOrgan(warmup=3)
        for _ in range(40):
            organ.advise({}, _belief(0.2))
        advice = organ.advise({}, _belief(6.0))
        self.assertTrue(advice.belief_delta, "spike decays mu")
        self.assertTrue(advice.uncertainty_delta, "spike raises uncertainty")
        self.assertGreater(advice.uncertainty_delta[0], advice.uncertainty_delta[1])

    def test_deterministic_reproducible(self) -> None:
        a, b = AdaptiveHazardOrgan(warmup=5), AdaptiveHazardOrgan(warmup=5)
        ra = [(adv.belief_delta, adv.uncertainty_delta) for adv in _drive(a, [20, 20, 120, 20])]
        rb = [(adv.belief_delta, adv.uncertainty_delta) for adv in _drive(b, [20, 20, 120, 20])]
        self.assertEqual(ra, rb)

    def test_reset_clears_state(self) -> None:
        organ = AdaptiveHazardOrgan(warmup=2, tau_init=60.0)
        _drive(organ, [20] * 8)
        organ.reset()
        self.assertEqual(organ.tau_hat, 60.0)
        self.assertEqual(organ._seen, 0)

    def test_advice_exposes_no_control_surface(self) -> None:
        organ = AdaptiveHazardOrgan(warmup=1)
        advice = _drive(organ, [30])[0]
        for forbidden in ("action", "policy", "shell", "forbidden", "pause"):
            self.assertFalse(hasattr(advice, forbidden))

    def test_module_does_not_import_policy_or_shell(self) -> None:
        src = inspect.getsource(o2_module)
        self.assertNotIn("import aac.policy", src)
        self.assertNotIn("import aac.shell", src)
        self.assertNotIn("from .policy", src)
        self.assertNotIn("from .shell", src)


class TestO2CorrigibilityRegression(unittest.TestCase):
    def _agent(self, seed=0):
        shell = CorrigibilityShell()
        agent = Agent(
            n_actions=8, shell=shell, rng=random.Random(seed),
            viability=ViabilityCore(budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0),
            prior_organ=AdaptiveHazardOrgan(),
        )
        return agent, shell

    def test_pausable(self) -> None:
        agent, shell = self._agent()
        env = StalenessEnv(n_actions=8, rng=random.Random(1))
        for _ in range(100):
            agent.step(env)
        shell.op_pause()
        self.assertIsNone(agent.step(env))

    def test_respects_tighten(self) -> None:
        agent, shell = self._agent()
        env = StalenessEnv(n_actions=8, rng=random.Random(2))
        shell.op_tighten(0)
        for _ in range(200):
            rec = agent.step(env)
            if rec is not None:
                self.assertNotEqual(rec["action"], 0)


if __name__ == "__main__":
    unittest.main()
