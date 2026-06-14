"""Tests for the G10 completeness check additive base_temperature arg (ADR-0030).

The C6/C7 and gate mechanism guards already live in test_confidence_gated_policy.py;
here we only cover the new additive wiring. End-to-end survival/area comparisons are
experiment scripts (experiments/completeness_g10.py), not pass/fail unit tests (§2.7).
"""
from __future__ import annotations

import random
import unittest

from aac.agent import Agent
from aac.policy import PolicySelector
from aac.shell import CorrigibilityShell


def _agent(**kw):
    return Agent(n_actions=3, shell=CorrigibilityShell(), rng=random.Random(0), **kw)


class TestBaseTemperatureWiring(unittest.TestCase):
    def test_default_base_temperature_unchanged(self) -> None:
        self.assertEqual(_agent().policy.base_temperature, 0.3)

    def test_agent_forwards_base_temperature_to_policy(self) -> None:
        self.assertEqual(_agent(base_temperature=0.05).policy.base_temperature, 0.05)

    def test_b_temp_is_gate_off(self) -> None:
        # B-temp = fixed low temperature, NO confidence gate.
        p = _agent(base_temperature=0.1).policy
        self.assertFalse(p.confidence_gate)
        self.assertEqual(p.base_temperature, 0.1)

    def test_low_fixed_temperature_is_sharper_than_default(self) -> None:
        # Same belief, no gate: a lower base temperature concentrates choice on the
        # mu/uncertainty argmax more than the default does.
        from aac.world_model import ActionOutcomeModel
        model = ActionOutcomeModel(n_actions=3)
        model.mu = [2.0, 0.0, 0.0]
        model.uncertainty = [0.3, 0.3, 0.3]
        cold = PolicySelector(rng=random.Random(1), base_temperature=0.02)
        warm = PolicySelector(rng=random.Random(1), base_temperature=1.0)
        cold_top = [cold.select(model, 0.0, 0.0) for _ in range(200)].count(0)
        warm_top = [warm.select(model, 0.0, 0.0) for _ in range(200)].count(0)
        self.assertGreater(cold_top, warm_top)


if __name__ == "__main__":
    unittest.main()
