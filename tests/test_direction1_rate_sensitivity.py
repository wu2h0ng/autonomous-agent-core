"""Direction 1 cheap-falsifier guards.

These tests pin the approved pre-build scope for the rate-sensitivity sweep.
They do not select seeds, freeze a packet, or run a sweep.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import unittest


class TestDirection1StaticSpec(unittest.TestCase):
    def test_period_cells_are_bound_to_env_periods(self) -> None:
        from experiments import direction1_rate_sensitivity as exp

        spec = exp.build_default_spec()
        self.assertEqual(
            {cell["id"]: cell["period"] for cell in spec["period_cells"]},
            {"FAST": 20, "DEFAULT": 40, "SLOW": 80},
        )
        for cell in spec["period_cells"]:
            env = exp.build_env(cell["period"], seed=1, spec=spec)
            self.assertEqual(env.period, cell["period"])

    def test_required_arms_are_complete(self) -> None:
        from experiments import direction1_rate_sensitivity as exp

        arms = {arm["id"]: arm for arm in exp.build_default_spec()["arms"]}
        self.assertEqual(
            set(arms),
            {
                "P0_FROZEN",
                "K025",
                "K100",
                "K200",
                "F003",
                "F020",
                "A0_DEFAULT",
                "BT_COLD",
                "COLD_005",
                "BROAD_200",
                "A1_O1",
            },
        )

    def test_gated_arms_keep_base_temperature_03(self) -> None:
        from experiments import direction1_rate_sensitivity as exp

        for arm in exp.build_default_spec()["arms"]:
            if arm["gate"]:
                self.assertIsNone(arm["organ"])
                self.assertEqual(arm["base_temperature"], 0.3)

    def test_fixed_baseline_temperatures_match_spec(self) -> None:
        from experiments import direction1_rate_sensitivity as exp

        arms = {arm["id"]: arm for arm in exp.build_default_spec()["arms"]}
        expected = {
            "A0_DEFAULT": 0.3,
            "BT_COLD": 0.03,
            "COLD_005": 0.05,
            "BROAD_200": 2.0,
            "A1_O1": 0.3,
        }
        for arm_id, base_temperature in expected.items():
            self.assertFalse(arms[arm_id]["gate"])
            self.assertEqual(arms[arm_id]["base_temperature"], base_temperature)

    def test_a1_o1_baseline_present(self) -> None:
        from experiments import direction1_rate_sensitivity as exp

        arms = {arm["id"]: arm for arm in exp.build_default_spec()["arms"]}
        self.assertEqual(arms["A1_O1"]["organ"], "O1")

    def test_rstar_is_not_verdict_arm(self) -> None:
        from experiments import direction1_rate_sensitivity as exp

        spec = exp.build_default_spec()
        self.assertNotIn("RSTAR", {arm["id"] for arm in spec["arms"]})
        bad = dict(spec)
        bad["arms"] = [*spec["arms"], {"id": "RSTAR", "gate": False}]
        with self.assertRaises(ValueError):
            exp.validate_spec(bad)


class TestDirection1DecisionAndSchema(unittest.TestCase):
    def test_result_schema_requires_period_rows_and_aggregates(self) -> None:
        from experiments import direction1_rate_sensitivity as exp

        spec = exp.build_default_spec()
        rows = [
            exp.empty_result_row("FAST", 20, "A0_DEFAULT", 1),
            exp.empty_result_row("DEFAULT", 40, "A0_DEFAULT", 1),
            exp.empty_result_row("SLOW", 80, "A0_DEFAULT", 1),
        ]
        aggregates = [
            exp.empty_period_aggregate("FAST", 20),
            exp.empty_period_aggregate("DEFAULT", 40),
            exp.empty_period_aggregate("SLOW", 80),
        ]
        result = exp.build_result_skeleton(spec, seeds=[1], rows=rows, aggregates=aggregates)
        exp.validate_result_schema(result, spec)

        missing = dict(result)
        missing["aggregates_by_period"] = aggregates[:2]
        with self.assertRaises(ValueError):
            exp.validate_result_schema(missing, spec)

    def test_decide_flat_fixed_schedule_returns_no_new_mechanism(self) -> None:
        from experiments import direction1_rate_sensitivity as exp

        spec = exp.build_default_spec()
        aggregates = [
            {
                "cell": "FAST",
                "period": 20,
                "best_fixed_arm": "A0_DEFAULT",
                "best_gated_arm": "P0_FROZEN",
                "best_fixed_mean_area": 100.0,
                "best_gated_mean_area": 98.0,
            },
            {
                "cell": "DEFAULT",
                "period": 40,
                "best_fixed_arm": "A0_DEFAULT",
                "best_gated_arm": "P0_FROZEN",
                "best_fixed_mean_area": 100.0,
                "best_gated_mean_area": 99.0,
            },
            {
                "cell": "SLOW",
                "period": 80,
                "best_fixed_arm": "A0_DEFAULT",
                "best_gated_arm": "P0_FROZEN",
                "best_fixed_mean_area": 100.0,
                "best_gated_mean_area": 98.0,
            },
        ]
        self.assertEqual(exp.decide(aggregates, spec), "NO_NEW_DIRECTION_1_MECHANISM")

    def test_cli_requires_spec_seed_and_lock(self) -> None:
        from experiments import direction1_rate_sensitivity as exp

        self.assertEqual(exp.main([]), 2)
        self.assertEqual(exp.main(["--spec", "x.json", "--seeds", "y.json"]), 2)

    def test_seed_lock_rejects_drift(self) -> None:
        from experiments import direction1_rate_sensitivity as exp

        data = json.dumps({"seed_fixture": [1, 2, 3]}, sort_keys=True).encode()
        digest = exp.sha256_bytes(data)
        exp.require_digest(data, digest)
        with self.assertRaises(ValueError):
            exp.require_digest(data, "0" * 64)


class TestDirection1C6C7Guards(unittest.TestCase):
    def test_c6_no_hidden_action_writer(self) -> None:
        from experiments import direction1_rate_sensitivity as exp

        spec = exp.build_default_spec()
        for arm in spec["arms"]:
            if arm["gate"]:
                self.assertIsNone(arm["organ"])
        self.assertNotIn("policy_writer", spec)
        self.assertNotIn("hidden_controller", spec)

    def test_c7_shell_not_modified_by_sweep(self) -> None:
        from aac.shell import CorrigibilityShell
        from experiments import direction1_rate_sensitivity as exp

        shell = CorrigibilityShell()
        before = set(shell.forbidden)
        exp.build_agent("P0_FROZEN", seed=1, spec=exp.build_default_spec(), shell=shell)
        self.assertEqual(set(shell.forbidden), before)


class TestDirection1DigestVerifyingCli(unittest.TestCase):
    def test_cli_refuses_digest_mismatch_without_output(self) -> None:
        from experiments import direction1_rate_sensitivity as exp

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_cli_inputs(tmp, exp, implementation_digest="0" * 64)

            rc = exp.main(
                [
                    "--spec",
                    str(paths["spec"]),
                    "--seeds",
                    str(paths["seeds"]),
                    "--lock",
                    str(paths["lock"]),
                    "--out",
                    str(paths["out"]),
                ]
            )

            self.assertEqual(rc, 2)
            self.assertFalse(paths["out"].exists())

    def test_cli_refuses_existing_output(self) -> None:
        from experiments import direction1_rate_sensitivity as exp

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_cli_inputs(tmp, exp)
            paths["out"].write_text("preexisting", encoding="utf-8")

            rc = exp.main(
                [
                    "--spec",
                    str(paths["spec"]),
                    "--seeds",
                    str(paths["seeds"]),
                    "--lock",
                    str(paths["lock"]),
                    "--out",
                    str(paths["out"]),
                ]
            )

            self.assertEqual(rc, 2)
            self.assertEqual(paths["out"].read_text(encoding="utf-8"), "preexisting")

    def test_cli_writes_not_r_final_result_after_digest_checks(self) -> None:
        from experiments import direction1_rate_sensitivity as exp

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_cli_inputs(tmp, exp)

            rc = exp.main(
                [
                    "--spec",
                    str(paths["spec"]),
                    "--seeds",
                    str(paths["seeds"]),
                    "--lock",
                    str(paths["lock"]),
                    "--out",
                    str(paths["out"]),
                ]
            )

            self.assertEqual(rc, 0)
            result = json.loads(paths["out"].read_text(encoding="utf-8"))
            exp.validate_result_schema(result, json.loads(paths["spec"].read_text()))
            self.assertTrue(result["not_r_final"])
            self.assertEqual(result["seeds"], [2400])
            self.assertEqual(
                {row["cell"] for row in result["rows"]},
                {"FAST", "DEFAULT", "SLOW"},
            )
            self.assertEqual(
                {row["arm_id"] for row in result["rows"]},
                {arm["id"] for arm in exp.build_default_spec()["arms"]},
            )
            self.assertIn(
                result["verdict"],
                {"NO_NEW_DIRECTION_1_MECHANISM", "RATE_SENSITIVE_CANDIDATE", "INVALID"},
            )

    def _write_cli_inputs(
        self,
        tmp: str,
        exp: object,
        *,
        implementation_digest: str | None = None,
    ) -> dict[str, pathlib.Path]:
        base = pathlib.Path(tmp)
        spec = exp.build_default_spec()
        spec["shared_constants"] = dict(spec["shared_constants"])
        spec["shared_constants"]["steps"] = 1
        spec_path = base / "spec.json"
        seeds_path = base / "seeds.json"
        lock_path = base / "lock.json"
        out_path = base / "result.json"
        spec_bytes = json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
        seed_doc = {
            "artifact_type": "direction1_rate_sensitivity_seed_list",
            "not_r_final": True,
            "seeds": [2400],
            "generation_rule": {"type": "contiguous_integer_range", "count": 1},
        }
        seed_bytes = json.dumps(seed_doc, sort_keys=True, separators=(",", ":")).encode()
        spec_path.write_bytes(spec_bytes)
        seeds_path.write_bytes(seed_bytes)
        impl_path = pathlib.Path(exp.__file__)
        test_path = pathlib.Path(__file__)
        lock = {
            "status": "RUN_LOCAL_LOCK_DRAFT_ONLY",
            "not_r_final": True,
            "spec": {"sha256": hashlib.sha256(spec_bytes).hexdigest()},
            "bound_files": {
                "implementation": {
                    "path": str(impl_path),
                    "sha256": implementation_digest
                    or hashlib.sha256(impl_path.read_bytes()).hexdigest(),
                },
                "tests": {
                    "path": str(test_path),
                    "sha256": hashlib.sha256(test_path.read_bytes()).hexdigest(),
                },
                "seed_list": {
                    "path": str(seeds_path),
                    "sha256": hashlib.sha256(seed_bytes).hexdigest(),
                },
            },
            "allowed_future_verdicts_after_separate_run_authorization": [
                "NO_NEW_DIRECTION_1_MECHANISM",
                "RATE_SENSITIVE_CANDIDATE",
                "INVALID",
            ],
        }
        lock_path.write_text(json.dumps(lock, sort_keys=True), encoding="utf-8")
        return {"spec": spec_path, "seeds": seeds_path, "lock": lock_path, "out": out_path}


if __name__ == "__main__":
    unittest.main()
