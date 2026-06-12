"""Tests for RAP perturbation mixture environment (T-P3.2, ADR-0014)."""
from __future__ import annotations

import random
import unittest

from envs.rap_mixture import (
    DisturbanceKind,
    RAPPerturbationEnv,
    SegmentKind,
    SegmentSpec,
    generate_segments,
)


class TestSegmentGeneration(unittest.TestCase):
    def test_generate_segments_is_reproducible_and_covers_total(self) -> None:
        node_ids = ("world_model_greedy", "random")
        a = generate_segments(
            rng=random.Random(7),
            total_steps=150,
            node_ids=node_ids,
            disturbance_rate=0.5,
        )
        b = generate_segments(
            rng=random.Random(7),
            total_steps=150,
            node_ids=node_ids,
            disturbance_rate=0.5,
        )
        self.assertEqual(a, b)
        self.assertEqual(sum(s.length for s in a), 150)
        for segment in a[:-1]:
            self.assertGreaterEqual(segment.length, 40)
            self.assertLessEqual(segment.length, 80)

    def test_segment_validation(self) -> None:
        with self.assertRaises(ValueError):
            SegmentSpec(SegmentKind.STABLE, 0)
        with self.assertRaises(ValueError):
            SegmentSpec(SegmentKind.STABLE, 1, node_id="random")
        with self.assertRaises(ValueError):
            SegmentSpec(SegmentKind.STABLE, 1, DisturbanceKind.NODE_DROP)


class TestRAPPerturbationEnv(unittest.TestCase):
    def test_segment_kind_controls_noise_and_regime_period(self) -> None:
        env = RAPPerturbationEnv(
            n_actions=3,
            rng=random.Random(0),
            base_regime_period=20,
            base_noise=0.5,
            segments=(
                SegmentSpec(SegmentKind.STABLE, 2),
                SegmentSpec(SegmentKind.SHIFTING, 3),
                SegmentSpec(SegmentKind.NOISY, 2),
            ),
        )
        self.assertEqual(env.current_segment.kind, SegmentKind.STABLE)
        self.assertEqual(env.noise, 0.5)
        self.assertEqual(env.regime_period, 20)

        env.act(env.best_action)
        env.act(env.best_action)
        self.assertEqual(env.current_segment.kind, SegmentKind.SHIFTING)
        self.assertEqual(env.noise, 0.5)
        self.assertEqual(env.regime_period, 5)

        for _ in range(3):
            env.act(env.best_action)
        self.assertEqual(env.current_segment.kind, SegmentKind.NOISY)
        self.assertEqual(env.noise, 1.5)
        self.assertEqual(env.regime_period, 20)

    def test_situation_reports_node_drop_and_lag(self) -> None:
        env = RAPPerturbationEnv(
            n_actions=2,
            rng=random.Random(1),
            segments=(
                SegmentSpec(
                    SegmentKind.STABLE,
                    1,
                    DisturbanceKind.NODE_DROP,
                    node_id="random",
                ),
                SegmentSpec(
                    SegmentKind.NOISY,
                    1,
                    DisturbanceKind.NODE_LAG,
                    node_id="efe_policy",
                ),
            ),
        )
        self.assertFalse(env.node_available("random"))
        self.assertEqual(env.situation()["dropped_node"], "random")
        self.assertIsNone(env.situation()["lagged_node"])

        env.act(0)
        self.assertTrue(env.node_lagged("efe_policy"))
        self.assertEqual(env.situation()["lagged_node"], "efe_policy")
        self.assertIsNone(env.situation()["dropped_node"])


if __name__ == "__main__":
    unittest.main()
