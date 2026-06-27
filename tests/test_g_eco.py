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
import json
import hashlib
from dataclasses import replace
from pathlib import Path

from aac.shell import CorrigibilityShell


def _bad_static_firewall_callee() -> bool:
    battery_outputs = {"MINIMAX": 1.0}
    return bool(battery_outputs)


def _bad_static_firewall_wrapper(state: object) -> bool:
    del state
    return _bad_static_firewall_callee()


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

    def test_lookahead_depth_changes_prediction(self) -> None:
        from aac.g_eco import GEcoSharedSubstrate
        from envs.ecological_4cond import Ecological4CondEnv

        env = Ecological4CondEnv(rng=random.Random(41))
        obs = env.observation()

        one_step = GEcoSharedSubstrate(lookahead_depth=1).lookahead(obs, "shield")
        three_step = GEcoSharedSubstrate(lookahead_depth=3).lookahead(obs, "shield")

        self.assertNotEqual(one_step.next_state, three_step.next_state)
        self.assertNotEqual(one_step.risk, three_step.risk)


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

    def test_rfinal_filter_rejects_calibration_refs_by_real_builder(self) -> None:
        from aac.g_eco import (
            assert_no_calibration_refs_in_rfinal,
            build_g_eco_arms,
            rfinal_arm_names,
        )

        arms = build_g_eco_arms(include_cheats=True)
        allowed = assert_no_calibration_refs_in_rfinal(arms, rfinal_arm_names())
        refs = {arm.name for arm in arms if arm.calibration_only}

        self.assertTrue(refs)
        self.assertTrue(set(allowed).isdisjoint(refs))

        with self.assertRaises(AssertionError):
            assert_no_calibration_refs_in_rfinal(
                arms, (*rfinal_arm_names(), "HOMEOSTATIC_ORACLE")
            )

    def test_oracle_and_wcref_are_privileged_not_runtime_aliases(self) -> None:
        from aac.g_eco import build_g_eco_arms
        from envs.ecological_4cond import Ecological4CondEnv, GEcoState

        env = Ecological4CondEnv(rng=random.Random(13))
        env.state = GEcoState(
            energy=58.0,
            integrity=48.0,
            need_a=61.0,
            need_b=39.0,
            shield=0.0,
        )
        arms = {arm.name: arm for arm in build_g_eco_arms(include_cheats=True)}
        obs = arms["VH"].substrate.observe(env)
        preds = arms["VH"].substrate.predict_all(obs)

        self.assertNotEqual(
            arms["HOMEOSTATIC_ORACLE"].score_actions(obs, preds),
            arms["VH"].score_actions(obs, preds),
        )
        self.assertNotEqual(
            arms["WCREF"].score_actions(obs, preds),
            arms["MINIMAX"].score_actions(obs, preds),
        )

    def test_runtime_arms_ignore_truth_state_but_cheats_use_it(self) -> None:
        from aac.g_eco import build_g_eco_arms
        from envs.ecological_4cond import Ecological4CondEnv, GEcoState

        env = Ecological4CondEnv(rng=random.Random(17))
        arms = {arm.name: arm for arm in build_g_eco_arms(include_cheats=True)}
        obs = arms["VH"].substrate.observe(env)
        altered_truth = replace(
            obs,
            truth_state=GEcoState(
                energy=12.0,
                integrity=90.0,
                need_a=10.0,
                need_b=85.0,
                shield=0.0,
            ),
        )

        for name in ("VH", "MINIMAX", "P0", "RSTAR", "O1", "BT"):
            self.assertEqual(
                arms[name].score_actions(obs),
                arms[name].score_actions(altered_truth),
                name,
            )

        self.assertNotEqual(
            arms["HOMEOSTATIC_ORACLE"].score_actions(obs),
            arms["HOMEOSTATIC_ORACLE"].score_actions(altered_truth),
        )
        self.assertNotEqual(
            arms["WCREF"].score_actions(obs),
            arms["WCREF"].score_actions(altered_truth),
        )

    def test_wcref_enter_rate_is_not_below_runtime_minimax(self) -> None:
        from aac.g_eco import GEcoMetrics, build_g_eco_arms
        from envs.ecological_4cond import Ecological4CondEnv

        def enter_rate(arm_name: str) -> float:
            entered = 0
            seeds = tuple(range(1810, 1815))
            for seed in seeds:
                env = Ecological4CondEnv(rng=random.Random(20_000 + seed))
                arms = {arm.name: arm for arm in build_g_eco_arms(include_cheats=True)}
                arm = arms[arm_name]
                metrics = GEcoMetrics()
                for _ in range(30):
                    obs = arm.substrate.observe(env)
                    action = arm.select(obs)
                    if action is None:
                        break
                    env.act(action)
                    metrics.observe(
                        step=env.t, state=env.state, action=action, alive=env.alive
                    )
                    if not env.alive:
                        break
                entered += int(bool(metrics.summary()["entered_region"]))
            return entered / len(seeds)

        self.assertGreaterEqual(enter_rate("WCREF"), enter_rate("MINIMAX"))

    def test_frozen_battery_arms_expose_real_source_metadata(self) -> None:
        from aac.g_eco import build_g_eco_battery
        from aac.prior_organ_o1 import ResetScaffoldOrgan
        from experiments.confidence_gated_g9 import GATE_FROZEN
        from experiments.ecological_g12 import BTEMP, load_rstar_params

        arms = {arm.name: arm for arm in build_g_eco_battery()}

        self.assertEqual(
            arms["P0"].source.params["gate_kappa"], GATE_FROZEN["gate_kappa"]
        )
        self.assertEqual(
            arms["P0"].source.params["gate_temp_floor"],
            GATE_FROZEN["gate_temp_floor"],
        )

        rstar = load_rstar_params()
        self.assertEqual(
            arms["RSTAR"].source.params["base_temperature"], rstar.base_temperature
        )
        self.assertEqual(arms["RSTAR"].source.params["inertia"], rstar.inertia)
        self.assertEqual(
            arms["RSTAR"].source.params["surprise_gain"], rstar.surprise_gain
        )

        self.assertEqual(
            arms["O1"].source.params["spike_k"], ResetScaffoldOrgan().spike_k
        )
        self.assertEqual(
            arms["O1"].source.params["reset_strength"],
            ResetScaffoldOrgan().reset_strength,
        )
        self.assertEqual(arms["BT"].source.params["base_temperature"], BTEMP)

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
    def test_observation_is_partial_lagged_noisy_and_truth_separated(self) -> None:
        from envs.ecological_4cond import Ecological4CondEnv

        env = Ecological4CondEnv(rng=random.Random(31))
        env.act("feed")
        env.act("repair")
        obs = env.observation()

        self.assertEqual(obs.truth_state, env.state)
        self.assertNotEqual(obs.state, env.state)
        self.assertLess(len(obs.observed_channels), 4)
        self.assertTrue(
            set(obs.observed_channels).issubset(
                {"energy", "integrity", "need_a", "need_b"}
            )
        )

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
        obs = vh.substrate.observe(env)
        original_action = vh.select(obs)
        self.assertIsNotNone(original_action)
        forbidden_idx = env.actions.index(original_action)
        shell.op_tighten(forbidden_idx)
        action = vh.select(vh.substrate.observe(env), shell=shell.view())
        self.assertNotEqual(action, original_action)
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


class TestGEcoPreGate2Freeze(unittest.TestCase):
    def _rehash_payload(self, payload: dict[str, object]) -> dict[str, object]:
        comparable = dict(payload)
        comparable.pop("content_hash", None)
        comparable["content_hash"] = hashlib.sha256(
            json.dumps(comparable, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return comparable

    def test_rate_scan_freezes_only_tri_border_witness(self) -> None:
        from aac.g_eco import scan_rate_grid

        freeze = scan_rate_grid(seeds=tuple(range(1800, 1810)), steps=36)
        payload = freeze.to_dict()

        self.assertEqual(payload["kind"], "g_eco.rates")
        self.assertEqual(payload["status"], "frozen_candidate")
        self.assertEqual(payload["seed_range"], [1800, 1809])
        self.assertEqual(payload["tri_border"]["naive_uniform_full_region_rate"], 0.0)
        self.assertGreater(
            payload["tri_border"]["homeostatic_oracle_full_region_rate"], 0.0
        )
        self.assertGreater(payload["tri_border"]["wcref_full_region_rate"], 0.0)
        self.assertTrue(payload["firewall"]["no_battery_outputs_used"])

        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn("VH", serialized)
        self.assertNotIn("MINIMAX", serialized)

    def test_battery_freeze_records_parameters_without_performance(self) -> None:
        from aac.g_eco import freeze_battery_parameters

        payload = freeze_battery_parameters().to_dict()

        self.assertEqual(payload["kind"], "g_eco.battery")
        self.assertEqual(
            tuple(payload["rfinal_arm_names"]),
            ("VH", "LIN", "LEX", "THR", "QUOTA", "MINIMAX", "P0", "RSTAR", "O1", "BT"),
        )
        self.assertIn("P0", payload["sources"])
        self.assertIn("RSTAR", payload["sources"])
        self.assertNotIn("enter_rate", json.dumps(payload, sort_keys=True))

    def test_vh_parameter_freeze_is_calibration_selected_and_pinned(self) -> None:
        from aac.g_eco import freeze_battery_parameters, scan_rate_grid

        rates = scan_rate_grid(seeds=tuple(range(1800, 1810)), steps=36)
        payload = freeze_battery_parameters(
            rates, seeds=tuple(range(1810, 1815)), steps=24
        ).to_dict()
        repeat = freeze_battery_parameters(
            rates, seeds=tuple(range(1810, 1815)), steps=24
        ).to_dict()

        self.assertEqual(payload["content_hash"], repeat["content_hash"])
        self.assertIn("candidate_parameters", payload)
        vh = payload["candidate_parameters"]["VH"]
        self.assertEqual(vh["source"]["kind"], "calibration_grid")
        self.assertEqual(vh["source"]["seed_range"], [1810, 1814])
        self.assertEqual(vh["source"]["steps"], 24)
        self.assertIn("selected_label", vh["source"])
        self.assertIn("parameter_grid_hash", vh["source"])
        self.assertIn("params", vh)
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn("enter_rate", serialized)
        self.assertNotIn("full_region_rate", serialized)

    def test_theta_lock_formula_uses_only_naive_oracle_inputs(self) -> None:
        from aac.g_eco import GEcoHalt, derive_threshold_freeze

        freeze = derive_threshold_freeze(
            naive_er=0.0,
            oracle_er=1.0,
            seed_count=10,
            K=4,
        )
        payload = freeze.to_dict()

        self.assertEqual(payload["kind"], "g_eco.thresholds")
        self.assertEqual(payload["theta_lo"], 0.05)
        self.assertEqual(payload["theta_hi"], 0.5)
        self.assertEqual(
            set(payload["formula_inputs"]), {"naive_er", "oracle_er", "seed_count", "K"}
        )
        self.assertEqual(
            payload["content_hash"],
            derive_threshold_freeze(
                naive_er=0.0,
                oracle_er=1.0,
                seed_count=10,
                K=4,
            ).to_dict()["content_hash"],
        )

        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn("VH", serialized)
        self.assertNotIn("MINIMAX", serialized)
        self.assertEqual(
            payload["verdict_mechanics"],
            {
                "bootstrap": {
                    "B": 10000,
                    "resample_seed": 611038,
                    "ci_method": "percentile",
                },
                "battery_best_tie_break": [
                    "enter_rate_desc",
                    "survival_steps_desc",
                    "irreversible_loss_asc",
                    "arm_name_asc",
                ],
                "comparison": {
                    "epsilon": 1e-12,
                    "rounding": "none",
                },
            },
        )

        with self.assertRaises(GEcoHalt) as ctx:
            derive_threshold_freeze(naive_er=0.90, oracle_er=1.0, seed_count=10, K=4)
        self.assertEqual(ctx.exception.code, "R4_THETA_DEGENERATE")

    def test_static_firewalls_are_ast_guards_not_self_report_only(self) -> None:
        from aac.g_eco import assert_g_eco_static_firewalls, assert_static_firewall

        assert_g_eco_static_firewalls()

        def bad_region(state: object) -> bool:
            del state
            MINIMAX_enter_rate = 1.0
            return MINIMAX_enter_rate > 0.0

        with self.assertRaises(AssertionError):
            assert_static_firewall(
                bad_region,
                forbidden_identifiers={"MINIMAX_enter_rate", "enter_rate"},
                context="negative-control",
            )

    def test_static_firewall_follows_same_module_callees(self) -> None:
        from aac.g_eco import assert_static_firewall

        with self.assertRaises(AssertionError):
            assert_static_firewall(
                _bad_static_firewall_wrapper,
                forbidden_identifiers={"battery_outputs"},
                context="recursive-negative-control",
            )

    def test_audit_firewall_exposes_halt_booleans_not_arm_rates(self) -> None:
        from aac.g_eco import (
            build_baseline_audit,
            freeze_battery_parameters,
            scan_rate_grid,
        )

        rates = scan_rate_grid(seeds=tuple(range(1800, 1810)), steps=36)
        battery = freeze_battery_parameters()
        audit = build_baseline_audit(
            rates,
            battery,
            seeds=tuple(range(1810, 1815)),
            steps=36,
        ).to_dict()

        self.assertEqual(audit["kind"], "g_eco.baseline_audit")
        self.assertTrue(audit["firewall"]["withheld_arm_level_enter_rates"])
        self.assertIn("ablation_invalid", audit["halt_booleans"])
        self.assertIn("ablation_hitchhiking", audit["halt_booleans"])
        self.assertIn("vh_minimax_indistinguishable", audit["halt_booleans"])
        self.assertNotIn("arm_enter_rates", audit)
        serialized_outputs = json.dumps(audit["mechanical_outputs"], sort_keys=True)
        self.assertTrue(audit["mechanical_outputs"]["predicate_values_withheld"])
        self.assertNotIn("enter_rate", serialized_outputs)
        self.assertNotIn("full_region_delta", serialized_outputs)
        self.assertNotIn("action_overlap", serialized_outputs)
        self.assertNotIn("margin", serialized_outputs)

    def test_pregate2_candidate_writer_keeps_rfinal_locked(self) -> None:
        from experiments import g_eco

        with tempfile.TemporaryDirectory() as tmp:
            out = g_eco.write_pregate2_candidate(
                Path(tmp), audit_seeds=tuple(range(1810, 1815))
            )
            self.assertTrue((Path(tmp) / "g_eco.rates.json").exists())
            self.assertTrue((Path(tmp) / "g_eco.battery.json").exists())
            self.assertTrue((Path(tmp) / "g_eco.thresholds.json").exists())
            self.assertTrue((Path(tmp) / "g_eco.baseline_audit.json").exists())
            self.assertEqual(out["gate2_locked"], True)
            self.assertNotIn("verdict", out)

            # Gate-2 unlock verifier is now implemented but stays LOCKED without a
            # founder co-sign over the exact bundle (see tests/test_gate2_unlock.py).
            with self.assertRaisesRegex(RuntimeError, "co-sign"):
                g_eco.assert_gate2_unlocked(Path(tmp))

    def test_pregate2_candidate_verifier_accepts_intact_candidate_but_keeps_gate_locked(
        self,
    ) -> None:
        from experiments import g_eco

        with tempfile.TemporaryDirectory() as tmp:
            g_eco.write_pregate2_candidate(
                Path(tmp), audit_seeds=tuple(range(1810, 1815))
            )
            report = g_eco.verify_pregate2_candidate_bundle(Path(tmp))

            self.assertEqual(report["kind"], "G-Eco pre-Gate-2 candidate verification")
            self.assertEqual(report["gate2_locked"], True)
            self.assertEqual(report["verified_candidate_bundle"], True)
            self.assertEqual(report["static_firewalls_verified"], True)
            self.assertIn("g_eco.baseline_audit.json", report["files"])
            self.assertNotIn("verdict", report)

            # Gate-2 unlock verifier is now implemented but stays LOCKED without a
            # founder co-sign over the exact bundle (see tests/test_gate2_unlock.py).
            with self.assertRaisesRegex(RuntimeError, "co-sign"):
                g_eco.assert_gate2_unlocked(Path(tmp))

    def test_pregate2_candidate_verifier_rejects_tampered_hash(self) -> None:
        from aac.g_eco import GEcoHalt
        from experiments import g_eco

        with tempfile.TemporaryDirectory() as tmp:
            g_eco.write_pregate2_candidate(
                Path(tmp), audit_seeds=tuple(range(1810, 1815))
            )
            path = Path(tmp) / "g_eco.thresholds.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["theta_lo"] = 0.49
            path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

            with self.assertRaises(GEcoHalt) as ctx:
                g_eco.verify_pregate2_candidate_bundle(Path(tmp))
            self.assertEqual(ctx.exception.code, "PREGATE2_HASH_MISMATCH")

    def test_pregate2_candidate_verifier_rejects_missing_file(self) -> None:
        from aac.g_eco import GEcoHalt
        from experiments import g_eco

        with tempfile.TemporaryDirectory() as tmp:
            g_eco.write_pregate2_candidate(
                Path(tmp), audit_seeds=tuple(range(1810, 1815))
            )
            (Path(tmp) / "g_eco.battery.json").unlink()

            with self.assertRaises(GEcoHalt) as ctx:
                g_eco.verify_pregate2_candidate_bundle(Path(tmp))
            self.assertEqual(ctx.exception.code, "PREGATE2_MISSING_FILE")

    def test_pregate2_candidate_verifier_rejects_audit_value_leak_even_with_valid_hash(
        self,
    ) -> None:
        from aac.g_eco import GEcoHalt
        from experiments import g_eco

        with tempfile.TemporaryDirectory() as tmp:
            g_eco.write_pregate2_candidate(
                Path(tmp), audit_seeds=tuple(range(1810, 1815))
            )
            path = Path(tmp) / "g_eco.baseline_audit.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["mechanical_outputs"]["full_region_delta"] = 0.02
            path.write_text(
                json.dumps(self._rehash_payload(payload), indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(GEcoHalt) as ctx:
                g_eco.verify_pregate2_candidate_bundle(Path(tmp))
            self.assertEqual(ctx.exception.code, "PREGATE2_AUDIT_LEAK")


if __name__ == "__main__":
    unittest.main()
