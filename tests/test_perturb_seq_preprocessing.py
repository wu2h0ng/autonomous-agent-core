"""Tests for Perturb-seq preprocessing using a synthetic tar archive."""

from __future__ import annotations

import csv
import gzip
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestPerturbSeqPreprocessing(unittest.TestCase):
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

    def _make_fake_tar(self, tmp: str) -> str:
        tar_path = os.path.join(tmp, "GSE90063_RAW.tar")
        # genenames: rows 0..11 correspond to locked genes (all present)
        gene_names = [
            "hg19_ENSG00000123456_hg19_ADGRB1",
            "hg19_ENSG00000123457_hg19_AIFM2",
            "hg19_ENSG00000123458_hg19_APAF1",
            "hg19_ENSG00000123459_hg19_ATM",
            "hg19_ENSG00000123460_hg19_ATR",
            "hg19_ENSG00000123461_hg19_BAX",
            "hg19_ENSG00000123462_hg19_BBC3",
            "hg19_ENSG00000123463_hg19_BCL2",
            "hg19_ENSG00000123464_hg19_BCL2L1",
            "hg19_ENSG00000123465_hg19_BID",
            "hg19_ENSG00000123466_hg19_CASP3",
            "hg19_ENSG00000123467_hg19_CASP8",
        ]
        # cellnames: 250 cells (100 observational + 6 KO targets x 25 each)
        n_obs = 100
        n_per_target = 25
        ko_targets = ["ATM", "ATR", "BAX", "BBC3", "BCL2", "CASP3"]
        cell_barcodes = [f"CELL{i:04d}" for i in range(n_obs + len(ko_targets) * n_per_target)]
        dict_rows: list[list[str]] = [["cell_barcode", "target_gene"]]
        dict_rows.extend([[b, "NON-TARGET"] for b in cell_barcodes[:n_obs]])
        cursor = n_obs
        for target in ko_targets:
            dict_rows.extend([[b, target] for b in cell_barcodes[cursor : cursor + n_per_target]])
            cursor += n_per_target

        n_cols = len(cell_barcodes)
        with tarfile.open(tar_path, "w") as tar:
            for name, lines in [
                (
                    "GSMFAKE_k562_tfs_7_genenames.csv.gz",
                    [[str(i), g] for i, g in enumerate(gene_names)],
                ),
                (
                    "GSMFAKE_k562_tfs_7_cellnames.csv.gz",
                    [[str(i), b] for i, b in enumerate(cell_barcodes)],
                ),
                (
                    "GSMFAKE_k562_tfs_7_cbc_gbc_dict.csv.gz",
                    dict_rows,
                ),
            ]:
                gz_path = os.path.join(tmp, name)
                with gzip.open(gz_path, "wt", newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh)
                    writer.writerows(lines)
                tar.add(gz_path, arcname=name)

            # mtx: small sparse 12 x N, one value per cell per gene
            mtx_name = "GSMFAKE_k562_tfs_7.mtx.txt.gz"
            mtx_gz_path = os.path.join(tmp, mtx_name)
            with gzip.open(mtx_gz_path, "wt", encoding="utf-8") as fh:
                fh.write("%%MatrixMarket matrix coordinate real general\n")
                fh.write("% fake data\n")
                fh.write(f"12 {n_cols} {12 * n_cols}\n")
                for col in range(n_cols):
                    for row in range(12):
                        val = float((row + 1) * (col + 1) % 10)
                        fh.write(f"{row + 1} {col + 1} {val}\n")
            tar.add(mtx_gz_path, arcname=mtx_name)

        return tar_path

    def test_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tar_path = self._make_fake_tar(tmp)
            lock_path = os.path.join(tmp, "lock.json")
            spec_path = os.path.join(tmp, "spec.json")
            out_path = os.path.join(tmp, "preprocessed.json")

            lock = {
                "accession": "GSEFAKE",
                "pathway": "p53 signaling pathway",
                "pathway_id": "hsa04115",
                "n_target": 12,
                "locked_genes": [
                    "ADGRB1", "AIFM2", "APAF1", "ATM", "ATR", "BAX",
                    "BBC3", "BCL2", "BCL2L1", "BID", "CASP3", "CASP8",
                ],
                "locked_by": "founder",
                "locked_at": "2026-07-06",
            }
            spec = {
                "train_test_split_seed": 42,
                "consultable_fraction": 0.7,
            }
            with open(lock_path, "w", encoding="utf-8") as fh:
                json.dump(lock, fh)
            with open(spec_path, "w", encoding="utf-8") as fh:
                json.dump(spec, fh)

            run = self._run_cli(
                [
                    "experiments/perturb_seq_preprocessing.py",
                    "--tar",
                    tar_path,
                    "--sample",
                    "GSMFAKE_k562_tfs_7",
                    "--lock",
                    lock_path,
                    "--spec",
                    spec_path,
                    "--output",
                    out_path,
                    "--max-cells-per-intervention",
                    "50",
                ]
            )
            self.assertEqual(
                run.returncode,
                0,
                f"preprocessing failed:\nstdout={run.stdout}\nstderr={run.stderr}",
            )
            with open(out_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            self.assertEqual(data["accession"], "GSEFAKE")
            self.assertEqual(data["pathway"], "p53 signaling pathway")
            self.assertEqual(len(data["selected_genes"]), 12)
            self.assertEqual(data["n_cells_observational"], 100)
            # 6 targets, split 0.7 -> 4 consultable, 2 held-out
            self.assertEqual(data["n_consultable_interventions"], 4)
            self.assertEqual(data["n_held_out_interventions"], 2)
            self.assertEqual(len(data["observational_cells"][0]), 12)


if __name__ == "__main__":
    unittest.main()
