"""G-Eco lower-half mechanism guards.

These tests intentionally stop before §6 calibration, freeze artifacts,
Gate-2, and r-final. They verify only the mechanism substrate, arm inventory,
calibration-only references, deterministic replay, reset boundary, and C6/C7
guards required before any frozen run can be considered.
"""

from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from aac.shell import CorrigibilityShell


class TestGEcoSharedSubstrate(unittest.TestCase):
    def test_substrate_prediction_is_bit_identical_across_arms(self) -> None:
        from aac.g_eco import build_g_eco_arms
        from envs.ecological_4cond import Ecological4CondEnv

        env = Ecological4CondEnv(rng=random.Random(11))
        arms = build_g_eco_arms()
        substrate_ids = {id(arm.substrate) for arm in arms}
        self.assertEqual(len(substrate_ids), 1)

        obs = arms[0].substrate.observe(env)
        baseline = {
            action: arms[0].substrate.lookahead(obs, action) for action in env.actions
        }
        for arm in arms[1:]:
            self.assertEqual(
                {
                    action: arm.substrate.lookahead(obs, action)
                    for action in env.actions
                },
                baseline,
            )

    def test_private_substrate_is_a_guard_failure(self) -> None:
        from aac.g_eco import (
            GEcoArm,
            GEcoSharedSubstrate,
            assert_shared_substrate,
            build_g_eco_arms,
        )

        arms = list(build_g_eco_arms())
        arms.append(
            GEcoArm(
                name="PRIVATE",
                family="battery",
                substrate=GEcoSharedSubstrate(lookahead_depth=2),
                aggregator=arms[0].aggregator,
            )
        )
        with self.assertRaises(AssertionError):
            assert_shared_substrate(tuple(arms))


class TestGEcoArmsAndRefs(unittest.TestCase):
    def test_battery_has_nine_arms_and_cheats_never_enter_rfinal(self) -> None:
        from aac.g_eco import build_calibration_refs, build_g_eco_battery

        battery = build_g_eco_battery()
        self.assertEqual(
            tuple(arm.name for arm in battery),
            ("LIN", "LEX", "THR", "QUOTA", "MINIMAX", "P0", "RSTAR", "O1", "BT"),
        )
        self.assertFalse(any(arm.calibration_only for arm in battery))

        refs = build_calibration_refs()
        self.assertEqual(
            tuple(ref.name for ref in refs), ("HOMEOSTATIC_ORACLE", "WCREF")
        )
        self.assertTrue(all(ref.calibration_only for ref in refs))

    def test_vh_and_no_stake_share_substrate_but_not_value_order(self) -> None:
        from aac.g_eco import build_g_eco_arms
        from envs.ecological_4cond import Ecological4CondEnv, GEcoState

        env = Ecological4CondEnv(rng=random.Random(7))
        env.state = GEcoState(
            energy=28.0,
            integrity=80.0,
            need_a=45.0,
            need_b=46.0,
            shield=0.0,
        )
        arms = {arm.name: arm for arm in build_g_eco_arms()}
        obs = arms["VH"].substrate.observe(env)
        predictions = {
            action: arms["VH"].substrate.lookahead(obs, action)
            for action in env.actions
        }
        vh_scores = arms["VH"].score_actions(obs, predictions)
        no_stake_scores = arms["VH_noStake"].score_actions(obs, predictions)

        self.assertEqual(id(arms["VH"].substrate), id(arms["VH_noStake"].substrate))
        self.assertNotEqual(vh_scores, no_stake_scores)
        self.assertEqual(arms["VH"].select(obs), "feed")
        self.assertNotEqual(arms["VH_noStake"].select(obs), "feed")


class TestGEcoEnvAndMetrics(unittest.TestCase):
    def test_deterministic_replay_and_no_external_rollback(self) -> None:
        from envs.ecological_4cond import Ecological4CondEnv

        actions = ("serve_a", "feed", "shield", "serve_b", "repair", "serve_a")
        a = Ecological4CondEnv(rng=random.Random(21))
        b = Ecological4CondEnv(rng=random.Random(21))
        trace_a = [a.act(action) for action in actions]
        trace_b = [b.act(action) for action in actions]

        self.assertEqual(trace_a, trace_b)
        self.assertEqual(a.state, b.state)
        self.assertFalse(hasattr(a, "rollback_external_world"))

        integrity_before = a.state.integrity
        a.act("repair")
        self.assertLessEqual(a.state.integrity, integrity_before)

    def test_region_and_metrics_use_only_environment_state(self) -> None:
        from aac.g_eco import GEcoMetrics, entered_viable_region
        from envs.ecological_4cond import GEcoState

        viable = GEcoState(energy=70.0, integrity=75.0, need_a=35.0, need_b=30.0)
        nonviable = GEcoState(energy=25.0, integrity=75.0, need_a=35.0, need_b=30.0)

        self.assertTrue(entered_viable_region(viable))
        self.assertFalse(entered_viable_region(nonviable))

        metrics = GEcoMetrics()
        metrics.observe(step=0, state=nonviable, action="feed", alive=True)
        metrics.observe(step=1, state=viable, action="serve_a", alive=True)
        summary = metrics.summary()
        self.assertEqual(summary["entered_region"], True)
        self.assertEqual(summary["enter_step"], 1)
        self.assertEqual(summary["survival_steps"], 2)


class TestGEcoC6C7AndGate2(unittest.TestCase):
    def test_pause_and_tighten_dominate_g_eco_policy(self) -> None:
        from aac.g_eco import build_g_eco_arms
        from envs.ecological_4cond import Ecological4CondEnv

        env = Ecological4CondEnv(rng=random.Random(5))
        vh = {arm.name: arm for arm in build_g_eco_arms()}["VH"]
        shell = CorrigibilityShell()
        shell.op_pause()
        self.assertIsNone(vh.select(vh.substrate.observe(env), shell=shell.view()))

        shell = CorrigibilityShell()
        shell.op_tighten(0)
        action = vh.select(vh.substrate.observe(env), shell=shell.view())
        self.assertNotEqual(action, env.actions[0])
        self.assertTrue(shell.audit.verify())

    def test_rfinal_refuses_without_gate2_freeze_bundle(self) -> None:
        from experiments import g_eco

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                g_eco.assert_gate2_unlocked(Path(tmp))

    def test_lower_half_entrypoint_runs_only_mechanism_smoke(self) -> None:
        from experiments import g_eco

        result = g_eco.mechanism_check(seeds=(1800,), steps=12)
        self.assertEqual(result["kind"], "G-Eco lower-half mechanism-check")
        self.assertEqual(result["gate2_locked"], True)
        self.assertNotIn("verdict", result)

        with self.assertRaises(SystemExit):
            g_eco.main(["r-final"])


if __name__ == "__main__":
    unittest.main()
