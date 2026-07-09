"""Tests for strong-locus Stage 3 harness."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestStage3SpecAndSeeds(unittest.TestCase):
    def test_seed_digest_matches(self) -> None:
        path = os.path.join(REPO_ROOT, "experiments", "strong_locus_stage3.seeds.json")
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        seeds = data["seeds"]
        actual = hashlib.sha256(
            json.dumps(seeds).encode("utf-8")
        ).hexdigest()
        self.assertEqual(actual, data["sha256"])
        self.assertEqual(seeds, list(range(5000, 5020)))

    def test_spec_schema(self) -> None:
        path = os.path.join(REPO_ROOT, "experiments", "strong_locus_stage3.spec.json")
        with open(path, "r", encoding="utf-8") as fh:
            spec = json.load(fh)
        self.assertEqual(spec["stage"], 3)
        self.assertEqual(spec["ks"], [3, 8, 15, 25, 40])
        self.assertEqual(spec["n_obs"], 200)
        self.assertEqual(spec["budget"], 3)
        self.assertIn("kill_conditions", spec)
        self.assertIn("trend_test", spec)


class TestStage3TinyStubRun(unittest.TestCase):
    def _run_cli(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = "src"
        return subprocess.run(
            [sys.executable] + args,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_tiny_stage3_run_and_adjudication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = os.path.join(tmp, "spec.json")
            seeds_path = os.path.join(tmp, "seeds.json")
            result_path = os.path.join(tmp, "result.json")
            plumbing_path = os.path.join(tmp, "plumbing.jsonl")
            verdict_path = os.path.join(tmp, "verdict.json")

            spec = {
                "experiment": "strong-locus-structure-crossover",
                "stage": 3,
                "ks": [3, 8],
                "n_obs": 200,
                "budget": 3,
                "likelihood_mode": "linear",
                "score_effect_threshold": 1.5,
                "empirical_effect_threshold": 1.5,
                "model_lock": "claude-sonnet-4-20250514",
                "temperature": 0.0,
                "max_tokens": 4096,
                "N_PARTICLES": 20,
                "N_MC_SAMPLES": 3,
                "UCB_ALPHA": 1.0,
                "plumbing_kinds": ["clean_wrong", "truncated", "timeout", "unparseable"],
                "trend_test": "spearman one-sided p <= 0.05",
                "effect_floor": "bootstrap 95% CI lower excludes 0",
                "kill_conditions": [],
            }
            seeds = {"band": "5000..5001", "seeds": [5000, 5001]}
            seeds["sha256"] = hashlib.sha256(
                json.dumps(seeds["seeds"]).encode("utf-8")
            ).hexdigest()

            with open(spec_path, "w", encoding="utf-8") as fh:
                json.dump(spec, fh)
            with open(seeds_path, "w", encoding="utf-8") as fh:
                json.dump(seeds, fh)

            run = self._run_cli(
                [
                    "experiments/strong_locus_structure_crossover.py",
                    "--stage",
                    "3",
                    "--backend",
                    "stub",
                    "--spec",
                    spec_path,
                    "--seeds",
                    seeds_path,
                    "--result-path",
                    result_path,
                    "--plumbing-path",
                    plumbing_path,
                ]
            )
            self.assertEqual(
                run.returncode,
                0,
                f"Stage 3 runner failed:\nstdout={run.stdout}\nstderr={run.stderr}",
            )

            with open(result_path, "r", encoding="utf-8") as fh:
                result = json.load(fh)

            self.assertEqual(result["stage"], 3)
            self.assertEqual(result["backend"], "stub")
            self.assertTrue(result.get("stub_only"))
            self.assertIn("hyperparameter_hash", result)
            self.assertIn("plumbing_summary", result)
            self.assertTrue(result.get("c7_halt_test_passes"))
            self.assertEqual(len(result["results"]), 4)  # 2 seeds * 2 ks

            # Each result row has plumbing and arm_results
            for row in result["results"]:
                self.assertIn("plumbing", row)
                self.assertIn("arm_results", row)
                for arm in ("organ_alone", "organ_tools", "organ_tools_externalized"):
                    self.assertIn(arm, row["arm_results"])

            # Adjudication
            adj = self._run_cli(
                [
                    "experiments/strong_locus_stage3_adjudicate.py",
                    "--result",
                    result_path,
                    "--spec",
                    spec_path,
                    "--output",
                    verdict_path,
                ]
            )
            self.assertEqual(
                adj.returncode,
                0,
                f"Adjudicator failed:\nstdout={adj.stdout}\nstderr={adj.stderr}",
            )
            with open(verdict_path, "r", encoding="utf-8") as fh:
                verdict = json.load(fh)
            self.assertIn("verdict", verdict)
            self.assertIn("statistics", verdict)
            self.assertEqual(verdict["verdict"], "INVALID")  # stub_only
            self.assertIn("stub_only", verdict["reason"].lower())


if __name__ == "__main__":
    unittest.main()
