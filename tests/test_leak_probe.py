"""Tests for strong-locus Stage 4 leak-probe harness."""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, "src")
sys.path.insert(0, "experiments")

from aac.llm_client import build_backend
from strong_locus_leak_probe import run_leak_probe


class TestLeakProbe(unittest.TestCase):
    def _minimal_preprocessed(self) -> dict:
        return {
            "accession": "GSEFAKE",
            "pathway": "p53 signaling pathway",
            "selected_genes": ["ADGRB1", "AIFM2", "APAF1"],
            "observational_cells": [
                [0.1, 0.2, 0.3],
                [0.2, 0.1, 0.4],
                [0.3, 0.3, 0.1],
                [0.1, 0.4, 0.2],
            ],
        }

    def test_stub_backend_does_not_leak(self) -> None:
        preprocessed = self._minimal_preprocessed()
        spec = {
            "leak_probe_seeds": 3,
            "leak_probe_seed_base": 6000,
            "leak_probe_chance_threshold": 0.10,
            "model_lock": "stub",
        }
        backend = build_backend("stub")
        result = run_leak_probe(preprocessed, spec, backend)

        self.assertEqual(result["verdict"], "RUNNABLE")
        self.assertEqual(result["actual_accession"], "GSEFAKE")
        self.assertEqual(result["n_seeds"], 3)
        self.assertEqual(len(result["failed_seeds"]), 0)
        self.assertEqual(len(result["passed_seeds"]), 3)
        self.assertTrue(result["stub_only"])
        self.assertIn("plumbing_counts", result)

    def test_score_leak_detects_accession(self) -> None:
        from strong_locus_leak_probe import _score_leak

        response = {"dataset_guess": "GSEFAKE", "pathway_guess": "", "gene_mapping": {}}
        failed = _score_leak(
            response,
            actual_accession="GSEFAKE",
            actual_pathway="p53 signaling pathway",
            actual_genes=["ADGRB1", "AIFM2"],
            tokens=["X00", "X01", "X02"],
            chance_threshold=0.10,
        )
        self.assertTrue(failed)

    def test_score_leak_ignores_safe_stub(self) -> None:
        from strong_locus_leak_probe import _score_leak

        response = {"final_answer": "stub reasoning complete"}
        failed = _score_leak(
            response,
            actual_accession="GSEFAKE",
            actual_pathway="p53 signaling pathway",
            actual_genes=["ADGRB1", "AIFM2"],
            tokens=["X00", "X01", "X02"],
            chance_threshold=0.10,
        )
        self.assertFalse(failed)


if __name__ == "__main__":
    unittest.main()
