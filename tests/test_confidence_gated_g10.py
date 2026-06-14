"""G10 (ADR-0024) guards: C6/C7 on the reused gate + deterministic measurement.

The gate mechanism itself is exhaustively tested in test_confidence_gated_policy.py
(G9). G10 is measurement-only, so these tests cover what G10 adds: the gate stays
C6/C7-clean as used by the confirmation arms, the bootstrap CI is deterministic, and
the per-seed area is a deterministic replay.
"""
from __future__ import annotations

import random
import unittest

from aac.policy import PolicySelector
from aac.world_model import ActionOutcomeModel


class TestG10C6GateReadsOnlyBelief(unittest.TestCase):
    def test_confidence_reads_only_action_outcome_model(self) -> None:
        # A well-separated, certain leader => confidence near 1 (subject-side only).
        model = ActionOutcomeModel(n_actions=4)
        model.mu = [5.0, 0.0, 0.0, 0.0]
        model.uncertainty = [0.01, 1.0, 1.0, 1.0]
        sel = PolicySelector(
            rng=random.Random(0), confidence_gate=True, gate_kappa=0.5, gate_temp_floor=0.1
        )
        self.assertGreater(sel._confidence(model), 0.9)

        # A tiny gap under high uncertainty => confidence near 0.
        model.mu = [0.1, 0.0, 0.0, 0.0]
        model.uncertainty = [2.0, 2.0, 2.0, 2.0]
        self.assertLess(sel._confidence(model), 0.2)


class TestG10C7ForbiddenDominatesGate(unittest.TestCase):
    def test_forbidden_action_never_selected_under_gate(self) -> None:
        # Action 2 has the highest mu but is forbidden (shell tighten); the gate
        # must never select it — corrigibility dominates a confident belief.
        sel = PolicySelector(
            rng=random.Random(1),
            forbidden=frozenset({2}),
            confidence_gate=True,
            gate_kappa=0.5,
            gate_temp_floor=0.1,
        )
        model = ActionOutcomeModel(n_actions=4)
        model.mu = [1.0, 1.0, 9.0, 1.0]
        model.uncertainty = [1.0, 1.0, 1.0, 1.0]
        picks = {sel.select(model, explore_drive=0.5, pressure=0.0) for _ in range(200)}
        self.assertNotIn(2, picks)


class TestG10MeasurementDeterministic(unittest.TestCase):
    def test_bootstrap_ci_is_deterministic_and_brackets_mean(self) -> None:
        from experiments.confidence_gated_g10 import _bootstrap_ci_mean

        vals = [10.0, 20.0, 30.0, 40.0, 50.0]  # mean 30
        ci1 = _bootstrap_ci_mean(vals, n_boot=1000, seed=42)
        ci2 = _bootstrap_ci_mean(vals, n_boot=1000, seed=42)
        self.assertEqual(ci1, ci2)
        lo, hi = ci1
        self.assertLess(lo, 30.0)
        self.assertGreater(hi, 30.0)

    def test_area_is_deterministic_replay(self) -> None:
        from experiments.confidence_gated_g9 import GATE_FROZEN, _area

        kw = dict(gate=True, kappa=GATE_FROZEN["gate_kappa"], temp_floor=GATE_FROZEN["gate_temp_floor"])
        a = _area(800, lambda: None, **kw)
        b = _area(800, lambda: None, **kw)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
