"""Tests for the strong-locus intervention-gap analyzer."""

from __future__ import annotations

import csv
import gzip
import json
import os
import tarfile
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from experiments.strong_locus_intervention_gap import (
    analyze_gap,
    extract_available_interventions,
    extract_observable_locked_genes,
    propose_missing_interventions,
)


class TestInterventionGap(unittest.TestCase):
    def _make_fake_tar(
        self,
        tmp: str,
        gene_names: list[str],
        ko_targets: list[str],
        sample: str = "GSMFAKE_k562_tfs_7",
    ) -> str:
        tar_path = os.path.join(tmp, "FAKE.tar")
        n_obs = 20
        n_per_target = 5
        cell_barcodes = [
            f"CELL{i:04d}" for i in range(n_obs + len(ko_targets) * n_per_target)
        ]
        dict_rows: list[list[str]] = [["cell_barcode", "target_gene"]]
        dict_rows.extend([[b, "NON-TARGET"] for b in cell_barcodes[:n_obs]])
        cursor = n_obs
        for target in ko_targets:
            dict_rows.extend(
                [[b, target] for b in cell_barcodes[cursor : cursor + n_per_target]]
            )
            cursor += n_per_target

        n_cols = len(cell_barcodes)
        with tarfile.open(tar_path, "w") as tar:
            for name, lines in [
                (
                    f"{sample}_genenames.csv.gz",
                    [[str(i), g] for i, g in enumerate(gene_names)],
                ),
                (
                    f"{sample}_cellnames.csv.gz",
                    [[str(i), b] for i, b in enumerate(cell_barcodes)],
                ),
                (
                    f"{sample}_cbc_gbc_dict.csv.gz",
                    dict_rows,
                ),
            ]:
                gz_path = os.path.join(tmp, name)
                with gzip.open(gz_path, "wt", newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh)
                    writer.writerows(lines)
                tar.add(gz_path, arcname=name)

            mtx_name = f"{sample}.mtx.txt.gz"
            mtx_gz_path = os.path.join(tmp, mtx_name)
            with gzip.open(mtx_gz_path, "wt", encoding="utf-8") as fh:
                fh.write("%%MatrixMarket matrix coordinate real general\n")
                fh.write("% fake data\n")
                n_genes = len(gene_names)
                fh.write(f"{n_genes} {n_cols} {n_genes * n_cols}\n")
                for col in range(n_cols):
                    for row in range(n_genes):
                        val = float((row + 1) * (col + 1) % 10)
                        fh.write(f"{row + 1} {col + 1} {val}\n")
            tar.add(mtx_gz_path, arcname=mtx_name)

        return tar_path

    def _lock(self, locked_genes: list[str]) -> dict:
        return {
            "accession": "GSEFAKE",
            "pathway": "p53 signaling pathway",
            "pathway_id": "hsa04115",
            "locked_genes": locked_genes,
        }

    def test_extract_available_interventions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            genes = [f"hg19_ENSG{i}_GENE{i}" for i in range(12)]
            tar = self._make_fake_tar(tmp, genes, ["ATM", "ATR", "BAX"])
            targets = extract_available_interventions(tar, "GSMFAKE_k562_tfs_7")
            self.assertEqual(targets, {"ATM", "ATR", "BAX"})

    def test_extract_observable_locked_genes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            genes = [
                "hg19_ENSG00000123456_hg19_ADGRB1",
                "hg19_ENSG00000123457_hg19_AIFM2",
                "hg19_ENSG00000123458_hg19_APAF1",
            ]
            tar = self._make_fake_tar(tmp, genes, ["ATM"])
            observable = extract_observable_locked_genes(
                tar, "GSMFAKE_k562_tfs_7", ["ADGRB1", "AIFM2", "APAF1", "MISSING"]
            )
            self.assertEqual(observable, {"ADGRB1", "AIFM2", "APAF1"})

    def test_propose_missing_interventions(self) -> None:
        proposal = propose_missing_interventions(["ATM", "ATR"], guides_per_gene=2)
        self.assertEqual(
            proposal,
            {
                "ATM": ["p_sgATM_1", "p_sgATM_2"],
                "ATR": ["p_sgATR_1", "p_sgATR_2"],
            },
        )

    def test_fit_recommends_proceed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            locked = [
                "ADGRB1", "AIFM2", "APAF1", "ATM", "ATR", "BAX",
                "BBC3", "BCL2", "BCL2L1", "BID", "CASP3", "CASP8",
            ]
            genes = [f"hg19_ENSG{i}_{g}" for i, g in enumerate(locked)]
            # 6 KO targets all inside locked set
            ko_targets = ["ATM", "ATR", "BAX", "BBC3", "BCL2", "CASP3"]
            tar = self._make_fake_tar(tmp, genes, ko_targets)
            lock = self._lock(locked)
            report = analyze_gap(lock, tar, "GSMFAKE_k562_tfs_7", min_consultable=5)
            self.assertEqual(report["n_consultable_locked_genes"], 6)
            self.assertEqual(report["verdict"], "FIT")
            self.assertEqual(report["recommendation"]["action"], "PROCEED")

    def test_no_overlap_recommends_request_interventions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            locked = [
                "ADGRB1", "AIFM2", "APAF1", "ATM", "ATR", "BAX",
                "BBC3", "BCL2", "BCL2L1", "BID", "CASP3", "CASP8",
            ]
            genes = [f"hg19_ENSG{i}_{g}" for i, g in enumerate(locked)]
            # KO targets are transcription factors, not in locked set
            ko_targets = ["CREB1", "EGR1", "YY1", "ELF1", "ELK1", "ETS1"]
            tar = self._make_fake_tar(tmp, genes, ko_targets)
            lock = self._lock(locked)
            report = analyze_gap(lock, tar, "GSMFAKE_k562_tfs_7", min_consultable=5)
            self.assertEqual(report["n_consultable_locked_genes"], 0)
            self.assertEqual(report["n_observable_locked_genes"], 12)
            self.assertEqual(report["verdict"], "NOT_FIT")
            self.assertEqual(report["recommendation"]["action"], "REQUEST_INTERVENTIONS")
            self.assertIn("ATM", report["proposed_missing_interventions"])

    def test_missing_from_dataset_recommends_pivot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            locked = ["ATM", "ATR", "BAX", "BBC3", "BCL2"]
            # Only 2 of the locked genes are observable
            genes = ["hg19_ENSG1_ATM", "hg19_ENSG2_ATR"]
            tar = self._make_fake_tar(tmp, genes, ["ATM", "ATR"])
            lock = self._lock(locked)
            report = analyze_gap(lock, tar, "GSMFAKE_k562_tfs_7", min_consultable=2)
            self.assertEqual(report["n_observable_locked_genes"], 2)
            self.assertEqual(report["recommendation"]["action"], "PIVOT_DATASET")
            self.assertEqual(
                report["recommendation"]["candidate_datasets"],
                ["Replogle_2022_K562_GWPS"],
            )


if __name__ == "__main__":
    unittest.main()
