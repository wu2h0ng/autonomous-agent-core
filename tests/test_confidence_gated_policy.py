"""Tests for G9 confidence-gated policy temperature (ADR-0023).

The gate is a SUBJECT-side mechanism: it reads the agent's own ActionOutcomeModel
and never an organ surface (C6 preserved). It must still obey the shell (C7).
"""

from __future__ import annotations

import inspect
import random
import unittest

from aac.agent import Agent
from aac.policy import PolicySelector
from aac.shell import CorrigibilityShell
from aac.viability import ViabilityCore
from aac.world_model import ActionOutcomeModel
from envs.structured_regime import StructuredRegimeEnv
import aac.policy as policy_module


def _model(mu: list[float], unc: list[float]) -> ActionOutcomeModel:
    m = ActionOutcomeModel(n_actions=len(mu))
    m.mu = list(mu)
    m.uncertainty = list(unc)
    return m


class TestConfidenceMeasure(unittest.TestCase):
    def test_high_when_leader_separated_and_certain(self) -> None:
        p = PolicySelector(rng=random.Random(0), confidence_gate=True, gate_kappa=1.0)
        conf = p._confidence(_model([5.0, 0.0, 0.0], [0.01, 0.5, 0.5]))
        self.assertGreater(conf, 0.9)

    def test_uncertainty_lowers_confidence_at_fixed_gap(self) -> None:
        # conf = gap / (kappa*u): same separation, more uncertainty -> less confident.
        p = PolicySelector(rng=random.Random(0), confidence_gate=True, gate_kappa=1.0)
        certain = p._confidence(_model([1.0, 0.0, 0.0], [0.1, 0.5, 0.5]))
        uncertain = p._confidence(_model([1.0, 0.0, 0.0], [2.0, 0.5, 0.5]))
        self.assertGreater(certain, 0.9)
        self.assertLess(uncertain, 0.9)

    def test_low_when_gap_small_relative_to_uncertainty(self) -> None:
        p = PolicySelector(rng=random.Random(0), confidence_gate=True, gate_kappa=1.0)
        conf = p._confidence(_model([0.3, 0.0, 0.0], [1.0, 0.5, 0.5]))
        self.assertLess(conf, 0.5)

    def test_confidence_reads_only_the_subject_model(self) -> None:
        # The signature takes the agent's own model; no organ/belief-advice arg.
        params = list(inspect.signature(PolicySelector._confidence).parameters)
        self.assertEqual(params, ["self", "model"])


class TestGatedSelection(unittest.TestCase):
    def test_gate_off_matches_baseline_temperature_path(self) -> None:
        # With the gate off, two selectors with identical rng must agree, and the
        # behaviour is the documented base+explore temperature (no gating branch).
        a = PolicySelector(rng=random.Random(7))
        b = PolicySelector(rng=random.Random(7), confidence_gate=False)
        model = _model([1.0, 0.5, 0.2], [0.4, 0.4, 0.4])
        outs_a = [a.select(model, 0.3, 0.0) for _ in range(50)]
        outs_b = [b.select(model, 0.3, 0.0) for _ in range(50)]
        self.assertEqual(outs_a, outs_b)

    def test_exploits_leader_when_confident(self) -> None:
        p = PolicySelector(
            rng=random.Random(1),
            confidence_gate=True,
            gate_kappa=1.0,
            gate_temp_floor=0.05,
        )
        model = _model([5.0, 0.0, 0.0], [0.01, 0.8, 0.8])  # confident leader = 0
        picks = [p.select(model, 0.5, 0.0) for _ in range(200)]
        self.assertGreater(picks.count(0), 190)  # near-greedy exploit

    def test_explores_when_unconfident(self) -> None:
        p = PolicySelector(
            rng=random.Random(1),
            confidence_gate=True,
            gate_kappa=1.0,
            gate_temp_floor=0.05,
        )
        model = _model([0.2, 0.1, 0.0], [1.0, 1.0, 1.0])  # uncertain, weak leader
        picks = [p.select(model, 0.7, 0.0) for _ in range(200)]
        self.assertLess(picks.count(0), 190)  # does NOT collapse to greedy

    def test_deterministic_replay(self) -> None:
        model = _model([3.0, 1.0, 0.0], [0.2, 0.6, 0.9])
        a = PolicySelector(rng=random.Random(5), confidence_gate=True)
        b = PolicySelector(rng=random.Random(5), confidence_gate=True)
        self.assertEqual(
            [a.select(model, 0.4, 0.1) for _ in range(40)],
            [b.select(model, 0.4, 0.1) for _ in range(40)],
        )


class TestGatedPolicyBoundaries(unittest.TestCase):
    def test_module_imports_no_organ(self) -> None:
        src = inspect.getsource(policy_module)
        self.assertNotIn("prior_organ", src)
        self.assertNotIn("OrganAdvice", src)

    def test_forbidden_stays_blocked_under_gate(self) -> None:
        # Even when the confident leader is the forbidden action, it is never chosen.
        p = PolicySelector(
            rng=random.Random(2),
            confidence_gate=True,
            gate_kappa=1.0,
            forbidden=frozenset({0}),
        )
        model = _model([5.0, 0.0, 0.0], [0.01, 0.8, 0.8])
        picks = {p.select(model, 0.5, 0.0) for _ in range(200)}
        self.assertNotIn(0, picks)

    def test_pause_makes_gated_step_a_noop(self) -> None:
        shell = CorrigibilityShell()
        agent = Agent(
            n_actions=8,
            shell=shell,
            rng=random.Random(0),
            viability=ViabilityCore(
                budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0
            ),
            policy_gate=True,
        )
        env = StructuredRegimeEnv(rng=random.Random(1))
        for _ in range(20):
            agent.step(env)
        shell.op_pause()
        self.assertIsNone(agent.step(env))

    def test_tighten_blocks_action_under_gated_policy(self) -> None:
        shell = CorrigibilityShell()
        shell.op_tighten(0)
        agent = Agent(
            n_actions=3,
            shell=shell,
            rng=random.Random(2),
            viability=ViabilityCore(
                budget=1e9, metabolic_cost=0.0, capacity=1e9, safe_budget=1.0
            ),
            policy_gate=True,
        )
        env = StructuredRegimeEnv(n_actions=3, rng=random.Random(3))
        for _ in range(100):
            rec = agent.step(env)
            if rec is not None:
                self.assertNotEqual(rec["action"], 0)


if __name__ == "__main__":
    unittest.main()
