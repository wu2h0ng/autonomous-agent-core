"""ADR-0028 survival-axis de-risk guards: determinism, arm wiring, C6/C7 on the gate."""

from __future__ import annotations

import random
import unittest

from aac.policy import PolicySelector
from aac.world_model import ActionOutcomeModel


class TestSurvivalArmWiring(unittest.TestCase):
    def test_arms_differ_only_in_temperature_regime(self) -> None:
        from experiments.survival_axis_c1 import EXPLOITER, EXPLORER, GATED, _build

        ex = _build(EXPLORER, 0, 100.0, 1.5)
        self.assertEqual(ex.policy.base_temperature, 2.0)
        self.assertFalse(ex.policy.confidence_gate)

        xp = _build(EXPLOITER, 0, 100.0, 1.5)
        self.assertEqual(xp.policy.base_temperature, 0.05)
        self.assertFalse(xp.policy.confidence_gate)

        ga = _build(GATED, 0, 100.0, 1.5)
        self.assertTrue(ga.policy.confidence_gate)


class TestSurvivalMeasurementDeterministic(unittest.TestCase):
    def test_run_is_deterministic_replay(self) -> None:
        from experiments.survival_axis_c1 import GATED, _run

        self.assertEqual(_run(GATED, 1010, 100.0, 1.5), _run(GATED, 1010, 100.0, 1.5))


class TestSurvivalC7ForbiddenDominatesGate(unittest.TestCase):
    def test_gate_never_selects_forbidden(self) -> None:
        sel = PolicySelector(
            rng=random.Random(0),
            forbidden=frozenset({2}),
            confidence_gate=True,
            gate_kappa=0.5,
            gate_temp_floor=0.1,
        )
        model = ActionOutcomeModel(n_actions=4)
        model.mu = [1.0, 1.0, 9.0, 1.0]  # action 2 looks best but is forbidden
        model.uncertainty = [1.0, 1.0, 1.0, 1.0]
        picks = {sel.select(model, explore_drive=0.5, pressure=0.0) for _ in range(200)}
        self.assertNotIn(2, picks)


if __name__ == "__main__":
    unittest.main()
