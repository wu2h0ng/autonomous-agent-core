"""Tests for strong-locus Stage 4 real-data harness."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestStrongLocusStage4(unittest.TestCase):
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

    def _make_preprocessed_json(self, tmp: str) -> str:
        path = os.path.join(tmp, "preprocessed.json")
        data = {
            "accession": "FAKE",
            "publication": "Fake dataset",
            "pathway": "p53 signaling pathway",
            "pathway_id": "hsa04115",
            "sample": "fake.h5ad",
            "selected_genes": ["A", "B", "C", "D"],
            "gene_index": {"A": 0, "B": 1, "C": 2, "D": 3},
            "locked_genes_present": ["A", "B", "C", "D"],
            "locked_genes_missing": [],
            "consultable_targets": ["A", "B"],
            "held_out_targets": ["C", "D"],
            "observational_cells": [
                [0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0],
            ],
            "consultable_interventions": {
                "0:ko": [[2.0, 0.0, 0.0, 0.0]],
                "1:ko": [[0.0, 2.0, 0.0, 0.0]],
            },
            "held_out_interventions": {
                "2:ko": [[0.0, 0.0, 2.0, 0.0]],
                "3:ko": [[0.0, 0.0, 0.0, 2.0]],
            },
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path

    def _make_spec_json(self, tmp: str) -> str:
        path = os.path.join(tmp, "spec.json")
        data = {
            "budget": 2,
            "likelihood_mode": "linear",
            "score_effect_threshold": 0.5,
            "empirical_effect_threshold": 0.5,
            "model_lock": "stub",
            "temperature": 0.0,
            "max_tokens": 100,
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path

    def test_stage4_stub_runs_all_arms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preprocessed = self._make_preprocessed_json(tmp)
            spec = self._make_spec_json(tmp)
            result_path = os.path.join(tmp, "result.json")
            proc = self._run_cli(
                [
                    "experiments/strong_locus_structure_crossover.py",
                    "--stage",
                    "4",
                    "--backend",
                    "stub",
                    "--preprocessed",
                    preprocessed,
                    "--spec",
                    spec,
                    "--result-path",
                    result_path,
                    "--plumbing-path",
                    os.path.join(tmp, "plumbing.jsonl"),
                ]
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(result_path, "r", encoding="utf-8") as fh:
                result = json.load(fh)

            self.assertEqual(result["stage"], 4)
            self.assertTrue(result["c7_halt_test_passes"])
            self.assertTrue(result["stub_only"])
            arms = result["results"][0]["arm_results"]
            expected_arms = {
                "corr",
                "organ_alone",
                "organ_tools",
                "organ_tools_externalized",
                "governed_loop",
                "passive_loop",
                "learned_select",
            }
            self.assertEqual(set(arms.keys()), expected_arms)
            for arm in arms.values():
                self.assertIn("ap", arm)
                self.assertIn("shd", arm)
                self.assertIn("interventions_spent", arm)

    def test_stage4_preprocessed_metadata_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preprocessed = self._make_preprocessed_json(tmp)
            spec = self._make_spec_json(tmp)
            result_path = os.path.join(tmp, "result.json")
            proc = self._run_cli(
                [
                    "experiments/strong_locus_structure_crossover.py",
                    "--stage",
                    "4",
                    "--backend",
                    "stub",
                    "--preprocessed",
                    preprocessed,
                    "--spec",
                    spec,
                    "--result-path",
                    result_path,
                    "--plumbing-path",
                    os.path.join(tmp, "plumbing.jsonl"),
                ]
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(result_path, "r", encoding="utf-8") as fh:
                result = json.load(fh)
            self.assertEqual(
                result["preprocessed_metadata"]["pathway"],
                "p53 signaling pathway",
            )
            self.assertEqual(result["results"][0]["selected_genes"], ["A", "B", "C", "D"])


if __name__ == "__main__":
    unittest.main()
