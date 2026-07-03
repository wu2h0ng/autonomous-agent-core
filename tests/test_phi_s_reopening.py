"""ADR-0040 phi_S reopening falsifier guards."""

from __future__ import annotations

import random
import unittest

from envs.phi_s_reopening import (
    ARCHIVE,
    BUFFER_M,
    MISALIGNED_READOUT,
    OBS_DIM,
    PHI_STAR,
    PhiSReopeningEnv,
    archive_readout,
    flatten_buffer,
)


class TestPhiSEnv(unittest.TestCase):
    def test_deterministic_replay(self) -> None:
        def trace() -> list[tuple[tuple[int, ...], int, float, float]]:
            env = PhiSReopeningEnv(seed=1234, condition="ALIGNED")
            out = []
            for action in (1, -1, 1, 1, -1, -1, 1, -1):
                obs = env.observation()
                reward = env.act(action)
                out.append((obs, env.last_action or 0, reward, env.last_regret))
            return out

        self.assertEqual(trace(), trace())

    def test_observation_and_buffer_shape_are_frozen(self) -> None:
        env = PhiSReopeningEnv(seed=1, condition="ALIGNED")
        self.assertEqual(len(env.observation()), OBS_DIM)
        self.assertEqual(len(env.buffer), BUFFER_M)
        self.assertEqual(len(flatten_buffer(env.buffer)), OBS_DIM * BUFFER_M)
        self.assertTrue(all(v in (-1, 1) for obs in env.buffer for v in obs))

    def test_misaligned_control_uses_different_archive_member(self) -> None:
        env = PhiSReopeningEnv(seed=2, condition="MISALIGNED")
        self.assertEqual(env.phi_star, PHI_STAR)
        self.assertEqual(env.readout_name, MISALIGNED_READOUT)
        self.assertNotEqual(env.readout_name, env.phi_star)


class TestPhiSRepresentability(unittest.TestCase):
    def test_archive_members_are_represented_by_the_perceptron_class(self) -> None:
        from experiments.phi_s_reopening import archive_representation

        env = PhiSReopeningEnv(seed=77, condition="ALIGNED")
        reps = {name: archive_representation(name) for name in ARCHIVE}
        for _ in range(64):
            buffer = env.buffer
            for name, rep in reps.items():
                self.assertEqual(rep.predict(buffer), archive_readout(name, buffer), name)
            env.advance_without_action()

    def test_degree3_kernel_self_dot_matches_feature_count(self) -> None:
        from experiments.phi_s_reopening import FEATURE_COUNT, degree3_monomial_kernel

        env = PhiSReopeningEnv(seed=5, condition="ALIGNED")
        features = env.features64()
        self.assertEqual(degree3_monomial_kernel(features, features), FEATURE_COUNT)


class TestPhiSHarness(unittest.TestCase):
    def test_b_star_calibration_returns_first_meeting_budget(self) -> None:
        from experiments.phi_s_reopening import calibrate_b_star

        result = calibrate_b_star(seeds=(2000,), candidate_budgets=(2, 4), steps=4)
        self.assertIn(result["B_star"], (2, 4))
        meeting = [row["budget"] for row in result["rows"] if row["meets"]]
        if meeting:
            self.assertEqual(result["B_star"], meeting[0])

    def test_misaligned_negative_control_wiring(self) -> None:
        env = PhiSReopeningEnv(seed=90, condition="MISALIGNED")
        saw_difference = False
        for _ in range(64):
            saw_difference = saw_difference or env.phi_star_action() != env.optimal_action()
            env.advance_without_action()
        self.assertTrue(saw_difference)

    def test_verdict_function_returns_frozen_categories(self) -> None:
        from experiments.phi_s_reopening import verdict_for_condition

        def row(budget: int, adv: float, of_adv: float = 0.0, recovery: float = 0.4):
            return {
                "budget": budget,
                "pair_stats": {
                    "ORGAN_vs_BASE-FAIR": {"adv": adv},
                    "ORGAN_vs_ORACLE-FEATURE-BASE": {"adv": of_adv},
                },
                "base_fair_phi_recovery": {"mean_accuracy": recovery},
            }

        h0_summary = {"curve": [row(1, 0.05), row(2, 0.05), row(16, 0.05)]}
        h1a_summary = {"curve": [row(1, 0.30), row(2, 0.05), row(16, 0.05)]}
        h1b_summary = {"curve": [row(1, 0.30), row(2, 0.25), row(16, 0.30)]}
        denied_summary = {"curve": [row(1, 0.30), row(2, 0.25), row(16, 0.30, of_adv=0.20)]}

        cases = [
            ("H0", h0_summary, False),
            ("H1a", h1a_summary, False),
            ("H1b", h1b_summary, False),
            ("INPUT-DENIED", denied_summary, False),
            ("VACUOUS", h0_summary, True),
        ]
        for expected, summary, vacuous in cases:
            got = verdict_for_condition(
                condition="ALIGNED",
                condition_summary=summary,
                b_star=2,
                small_budget=1,
                gg_budget=16,
                misaligned_control_pass=True,
                vacuous=vacuous,
            )
            self.assertEqual(got["verdict"], expected)
            self.assertEqual(
                tuple(got["categories"]),
                ("H0", "H1a", "H1b", "INPUT-DENIED", "VACUOUS"),
            )

    def test_no_random_seed_global_state_needed(self) -> None:
        before = [random.random() for _ in range(3)]
        PhiSReopeningEnv(seed=3, condition="ALIGNED")
        after = [random.random() for _ in range(3)]
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
