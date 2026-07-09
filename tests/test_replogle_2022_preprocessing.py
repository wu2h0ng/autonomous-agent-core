"""Tests for Replogle 2022 K562 GWPS bulk h5ad preprocessing."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import anndata
    import numpy as np

    ANNDATA_AVAILABLE = True
except Exception:  # pragma: no cover
    ANNDATA_AVAILABLE = False


@unittest.skipUnless(ANNDATA_AVAILABLE, "anndata/numpy not installed")
class TestReplogle2022Preprocessing(unittest.TestCase):
    def _make_fake_h5ad(
        self,
        tmp: str,
        gene_names: list[str],
        obs_indices: list[str],
    ) -> str:
        import anndata
        import numpy as np

        n_obs = len(obs_indices)
        n_vars = len(gene_names)
        # Deterministic synthetic values so tests are stable
        X = np.arange(n_obs * n_vars, dtype=float).reshape(n_obs, n_vars) % 17
        ad = anndata.AnnData(X=X)
        ad.obs.index = obs_indices
        ad.var["gene_name"] = gene_names
        path = os.path.join(tmp, "fake.h5ad")
        ad.write_h5ad(path)
        return path

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

    def test_end_to_end_creates_expected_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            locked = [
                "ADGRB1", "AIFM2", "APAF1", "ATM", "ATR", "BAX",
                "BBC3", "BCL2", "BCL2L1", "BID", "CASP3", "CASP8",
            ]
            gene_names = locked  # simple one-to-one mapping
            # 50 controls + one row each for 8 KO targets inside pathway
            obs_indices = (
                [f"{i}_NON-TARGETING_NON-TARGETING" for i in range(50)]
                + ["100_AIFM2_P1P2_ENSG1"]
                + ["101_APAF1_P1P2_ENSG2"]
                + ["102_ATM_P1P2_ENSG3"]
                + ["103_ATR_P1P2_ENSG4"]
                + ["104_BAX_P1P2_ENSG5"]
                + ["105_BBC3_P1P2_ENSG6"]
                + ["106_BCL2L1_P1P2_ENSG7"]
                + ["107_BID_P1P2_ENSG8"]
            )
            h5ad_path = self._make_fake_h5ad(tmp, gene_names, obs_indices)

            lock_path = os.path.join(tmp, "lock.json")
            with open(lock_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "accession": "FAKE",
                        "pathway": "p53 signaling pathway",
                        "pathway_id": "hsa04115",
                        "locked_genes": locked,
                    },
                    fh,
                )

            spec_path = os.path.join(tmp, "spec.json")
            with open(spec_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "accession": "FAKE",
                        "dataset": "Fake dataset",
                        "train_test_split_seed": 42,
                        "consultable_fraction": 0.7,
                    },
                    fh,
                )

            output_path = os.path.join(tmp, "out.json")
            csv_path = os.path.join(tmp, "out.csv")

            proc = self._run_cli(
                [
                    "experiments/replogle_2022_preprocessing.py",
                    "--h5ad",
                    h5ad_path,
                    "--lock",
                    lock_path,
                    "--spec",
                    spec_path,
                    "--output",
                    output_path,
                    "--csv",
                    csv_path,
                    "--max-observational-rows",
                    "30",
                ]
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            with open(output_path, "r", encoding="utf-8") as fh:
                result = json.load(fh)

            self.assertEqual(result["pathway_id"], "hsa04115")
            self.assertEqual(result["selected_genes"], sorted(locked))
            self.assertEqual(result["locked_genes_missing"], [])
            self.assertEqual(result["n_cells_observational"], 30)
            # 8 KO targets -> 70% consultable -> 5 or 6 consultable, >=2 held-out
            self.assertGreaterEqual(result["n_consultable_interventions"], 5)
            self.assertGreaterEqual(result["n_held_out_interventions"], 2)
            self.assertEqual(
                result["n_consultable_interventions"] + result["n_held_out_interventions"],
                8,
            )
            self.assertEqual(len(result["observational_cells"][0]), 12)

            # CSV preview has correct number of rows
            with open(csv_path, "r", encoding="utf-8") as fh:
                reader = list(csv.reader(fh))
            header = reader[0]
            self.assertEqual(header[0], "split")
            self.assertEqual(header[1], "target")
            self.assertEqual(len(header), 14)  # 2 + 12 genes
            self.assertEqual(len(reader), 1 + 30 + 8)  # header + obs + interventions

    def test_too_few_ko_targets_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            locked = [
                "ADGRB1", "AIFM2", "APAF1", "ATM", "ATR", "BAX",
                "BBC3", "BCL2", "BCL2L1", "BID", "CASP3", "CASP8",
            ]
            gene_names = locked
            obs_indices = (
                [f"{i}_NON-TARGETING_NON-TARGETING" for i in range(20)]
                + ["100_ATM_P1P2_ENSG1"]
                + ["101_XYZ_P1P2_ENSG2"]  # not in locked set
            )
            h5ad_path = self._make_fake_h5ad(tmp, gene_names, obs_indices)
            lock_path = os.path.join(tmp, "lock.json")
            with open(lock_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "pathway": "p53",
                        "pathway_id": "hsa04115",
                        "locked_genes": locked,
                    },
                    fh,
                )
            spec_path = os.path.join(tmp, "spec.json")
            with open(spec_path, "w", encoding="utf-8") as fh:
                json.dump({"train_test_split_seed": 1, "consultable_fraction": 0.7}, fh)

            proc = self._run_cli(
                [
                    "experiments/replogle_2022_preprocessing.py",
                    "--h5ad",
                    h5ad_path,
                    "--lock",
                    lock_path,
                    "--spec",
                    spec_path,
                    "--output",
                    os.path.join(tmp, "out.json"),
                    "--csv",
                    os.path.join(tmp, "out.csv"),
                ]
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("Insufficient consultable KO targets", proc.stderr)

    def test_extract_target_gene(self) -> None:
        from experiments.replogle_2022_preprocessing import extract_target_gene

        self.assertEqual(extract_target_gene("105_ACTG1_P1P2_ENSG00000121410"), "ACTG1")
        self.assertEqual(extract_target_gene("10928_NON-TARGETING_NON-TARGETING"), "NON-TARGETING")
        self.assertEqual(extract_target_gene("1207_CASP8_P2"), "CASP8")
        self.assertIsNone(extract_target_gene("malformed"))


if __name__ == "__main__":
    unittest.main()
