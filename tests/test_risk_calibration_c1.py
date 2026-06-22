"""ADR-0029 risk-calibration de-risk guards: env behaviour + deterministic measurement."""

from __future__ import annotations

import random
import unittest


class TestStationaryRiskEnv(unittest.TestCase):
    def test_trap_emits_catastrophe_and_counts_it(self) -> None:
        from experiments.risk_calibration_c1 import StationaryRiskEnv

        env = StationaryRiskEnv(
            8, random.Random(0), p_cat=1.0
        )  # trap always catastrophic
        self.assertEqual(env.act(env.trap), env.cat)
        self.assertEqual(env.catastrophes, 1)
        # a safe action is near its mean and never a catastrophe
        safe = env.act(1)
        self.assertGreater(safe, 0.0)
        self.assertEqual(env.catastrophes, 1)

    def test_no_catastrophe_when_pcat_zero(self) -> None:
        from experiments.risk_calibration_c1 import StationaryRiskEnv

        env = StationaryRiskEnv(8, random.Random(0), p_cat=0.0)
        for _ in range(50):
            self.assertGreater(env.act(env.trap), 0.0)  # trap mean positive, no cat
        self.assertEqual(env.catastrophes, 0)


class TestRiskMeasurementDeterministic(unittest.TestCase):
    def test_run_is_deterministic_replay(self) -> None:
        from experiments.risk_calibration_c1 import GATED, _run

        self.assertEqual(
            _run(GATED, 1100, 40.0, 1.5, 0.05), _run(GATED, 1100, 40.0, 1.5, 0.05)
        )


if __name__ == "__main__":
    unittest.main()
