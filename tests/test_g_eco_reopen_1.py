"""G-ECO-REOPEN-1 non-bijective stake-channel guards.

These tests are intentionally written before the cast mechanism exists.
They define the minimum behavior that must fail until the NBSC environment,
policy battery, and adjudication path are implemented.
"""

from __future__ import annotations

import unittest
from pathlib import Path
import tempfile


class TestNBSCEnvironment(unittest.TestCase):
    def test_initial_visible_stake_channel_is_non_bijective(self) -> None:
        from envs.geco_nonbijective_stake import NonBijectiveStakeEnv

        ridge_env = NonBijectiveStakeEnv.from_seed(7400, forced_basin="ridge")
        valley_env = NonBijectiveStakeEnv.from_seed(7400, forced_basin="valley")

        ridge_obs = ridge_env.observation()
        valley_obs = valley_env.observation()

        self.assertEqual(ridge_obs.visible_stake, valley_obs.visible_stake)
        self.assertEqual(ridge_obs.stress, valley_obs.stress)
        self.assertNotEqual(ridge_env.state.latent_basin, valley_env.state.latent_basin)

    def test_probe_reveals_public_signal_without_private_oracle(self) -> None:
        from envs.geco_nonbijective_stake import NonBijectiveStakeEnv

        env = NonBijectiveStakeEnv.from_seed(7401, forced_basin="ridge")
        before = env.observation()
        self.assertIsNone(before.revealed_signal)

        outcome = env.act("probe")
        after = env.observation()

        self.assertEqual(outcome.action, "probe")
        self.assertEqual(after.revealed_signal, "ridge")
        self.assertEqual(after.visible_stake, before.visible_stake)


class TestNBSCBattery(unittest.TestCase):
    def test_all_arms_share_public_action_and_observation_budget(self) -> None:
        from aac.g_eco_reopen import build_nbsc_battery
        from envs.geco_nonbijective_stake import NonBijectiveStakeEnv

        env = NonBijectiveStakeEnv.from_seed(7402)
        obs = env.observation()
        arms = build_nbsc_battery()

        self.assertEqual(
            tuple(arm.name for arm in arms),
            (
                "NBSC_CANDIDATE",
                "MINIMAX_FAIR",
                "P0_FROZEN",
                "STRUCT_MEM",
                "RSTAR_FAIR",
                "NO_STAKE",
            ),
        )
        action_sets = {arm.name: tuple(arm.available_actions(obs)) for arm in arms}
        self.assertEqual(len(set(action_sets.values())), 1)
        self.assertEqual(next(iter(action_sets.values())), env.actions)

    def test_minimax_fair_has_same_probe_horizon_on_ambiguous_channel(self) -> None:
        from aac.g_eco_reopen import build_nbsc_battery
        from envs.geco_nonbijective_stake import NonBijectiveStakeEnv

        env = NonBijectiveStakeEnv.from_seed(7403, forced_basin="valley")
        obs = env.observation()
        arms = {arm.name: arm for arm in build_nbsc_battery()}

        self.assertEqual(arms["NBSC_CANDIDATE"].select(obs), "probe")
        self.assertEqual(arms["MINIMAX_FAIR"].select(obs), "probe")

    def test_seed_allocation_is_fresh_and_disjoint(self) -> None:
        from aac.g_eco_reopen import G_ECO_REOPEN_1_SEEDS, assert_fresh_seed_allocation

        assert_fresh_seed_allocation(G_ECO_REOPEN_1_SEEDS)
        self.assertEqual(G_ECO_REOPEN_1_SEEDS["r_final"], tuple(range(7500, 7530)))
        support = set(G_ECO_REOPEN_1_SEEDS["support_calibration"])
        self.assertTrue(support.isdisjoint(G_ECO_REOPEN_1_SEEDS["r_final"]))

    def test_adjudication_is_invalid_when_c6_c7_boundary_fails(self) -> None:
        from aac.g_eco_reopen import adjudicate_nbsc_result

        verdict = adjudicate_nbsc_result(
            {
                "integrity": {
                    "c6_c7_static_boundary": False,
                    "deterministic_replay": True,
                },
                "aggregates": {},
            }
        )

        self.assertEqual(verdict["verdict"], "INVALID")
        self.assertIn("c6_c7_static_boundary", verdict["reasons"])

    def test_static_boundary_rejects_shell_operator_surface(self) -> None:
        from aac.g_eco_reopen import assert_c6_c7_static_boundary

        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.py"
            bad.write_text(
                "from aac.shell import CorrigibilityShell\n"
                "def mutate(shell):\n"
                "    shell.op_pause()\n",
                encoding="utf-8",
            )
            with self.assertRaises(AssertionError):
                assert_c6_c7_static_boundary((bad,))

    def test_run_output_contains_preregistered_metrics(self) -> None:
        from aac.g_eco_reopen import run_nbsc_battery

        result = run_nbsc_battery((7460, 7461))
        aggregates = result["aggregates"]
        integrity = result["integrity"]

        self.assertIn("basin_misclassification_regret", aggregates)
        self.assertIn("paired_enter_rate_difference", aggregates)
        self.assertIn("deterministic_replay_hash", integrity)

    def test_final_result_hash_covers_lock_fields(self) -> None:
        from aac.g_eco_reopen import (
            canonical_json_hash,
            finalize_locked_nbsc_result,
            run_nbsc_battery,
        )

        raw = run_nbsc_battery((7460,))
        lock = {
            "prereg_id": "G-ECO-REOPEN-1-2026-07-04",
            "spec_sha256": "spec",
            "spec_file_sha256": "spec-file",
            "mechanism_files": {"src/a.py": "hash"},
        }
        final = finalize_locked_nbsc_result(raw, lock, lock_path="prereg.lock")

        embedded = final["result_hash"]
        without_hash = dict(final)
        del without_hash["result_hash"]
        self.assertEqual(embedded, canonical_json_hash(without_hash))

        changed_lock = dict(lock)
        changed_lock["spec_sha256"] = "changed"
        changed = finalize_locked_nbsc_result(raw, changed_lock, lock_path="prereg.lock")
        self.assertNotEqual(embedded, changed["result_hash"])

    def test_fair_minimax_kills_overlap_success_when_identical(self) -> None:
        from aac.g_eco_reopen import adjudicate_nbsc_result, run_nbsc_battery

        result = run_nbsc_battery((7460, 7461, 7462))
        verdict = adjudicate_nbsc_result(result)

        self.assertEqual(result["aggregates"]["candidate_vs_minimax_action_overlap"], 1.0)
        self.assertEqual(verdict["verdict"], "NOT_MET")
        self.assertIn("candidate_vs_minimax_action_overlap", verdict["reasons"])


if __name__ == "__main__":
    unittest.main()
