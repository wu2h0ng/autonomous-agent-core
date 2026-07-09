"""Perturb-seq preprocessing for strong-locus Stage 4.

Downloads/extracts the GEO GSE90063 RAW tar, selects the locked pathway genes,
maps cells to CRISPR KO targets, splits targets into consultable S and held-out
T, and emits a normalized JSON consumable by the strong-locus runner.

Pure stdlib (gzip, tarfile, csv). No pandas/scanpy/h5py required.

Run from autonomous-agent-core root:
    PYTHONPATH=src python experiments/perturb_seq_preprocessing.py \
        --tar experiments/data/perturb_seq/GSE90063_RAW.tar \
        --sample GSM2396858_k562_tfs_7 \
        --lock experiments/variable_selection_lock.json \
        --spec experiments/strong_locus_stage4.spec.json \
        --output experiments/perturb_seq_preprocessed.json
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import random
import re
import sys
import tarfile
import tempfile
from typing import Any

sys.path.insert(0, "src")
sys.path.insert(0, "experiments")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Perturb-seq preprocessing")
    parser.add_argument(
        "--tar",
        default="experiments/data/perturb_seq/GSE90063_RAW.tar",
        help="Path to GSE90063_RAW.tar",
    )
    parser.add_argument(
        "--sample",
        default="GSM2396858_k562_tfs_7",
        help="Sample prefix inside the tar (e.g. GSM2396858_k562_tfs_7)",
    )
    parser.add_argument(
        "--lock",
        default="experiments/variable_selection_lock.json",
        help="variable_selection_lock.json",
    )
    parser.add_argument(
        "--spec",
        default="experiments/strong_locus_stage4.spec.json",
        help="Stage 4 spec JSON",
    )
    parser.add_argument(
        "--output",
        default="experiments/perturb_seq_preprocessed.json",
        help="Output preprocessed JSON",
    )
    parser.add_argument(
        "--max-cells-per-intervention",
        type=int,
        default=200,
        help="Downsample cells per KO to this many (observational budget)",
    )
    parser.add_argument(
        "--log1p-normalize",
        action="store_true",
        default=True,
        help="Apply log1p(count) normalization",
    )
    return parser.parse_args()


def _load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _extract_member(tar: tarfile.TarFile, name: str, dest_dir: str) -> str:
    member = tar.getmember(name)
    tar.extract(member, dest_dir)
    return os.path.join(dest_dir, name)


def _read_cellnames(path: str) -> dict[int, str]:
    """Map column index -> cell barcode."""
    mapping: dict[int, str] = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row:
                continue
            if len(row) == 1:
                # index,barcode on same row separated by whitespace sometimes
                parts = row[0].split()
                if len(parts) >= 2:
                    try:
                        idx = int(parts[0])
                    except ValueError:
                        continue
                    mapping[idx] = parts[1].strip()
                else:
                    # assume row index corresponds to order
                    mapping[len(mapping)] = row[0].strip()
            else:
                try:
                    idx = int(row[0])
                except ValueError:
                    continue
                mapping[idx] = row[1].strip()
    return mapping


def _read_genenames(path: str) -> dict[int, str]:
    """Map row index -> gene name string."""
    mapping: dict[int, str] = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row:
                continue
            if len(row) == 1:
                parts = row[0].split()
                if len(parts) >= 2:
                    try:
                        idx = int(parts[0])
                    except ValueError:
                        continue
                    mapping[idx] = parts[1].strip()
                else:
                    mapping[len(mapping)] = row[0].strip()
            else:
                try:
                    idx = int(row[0])
                except ValueError:
                    continue
                mapping[idx] = row[1].strip()
    return mapping


def _extract_symbol(name: str) -> str | None:
    """Try to extract a human gene symbol from GEO genename entries.

    Accepts formats like:
      hg19_ENSG00000186092_hg19_OR4F5
      OR4F5
      ENSG00000186092_OR4F5
    """
    name = name.strip()
    # Direct symbol if simple alphanumeric/underscore
    if re.fullmatch(r"[A-Za-z0-9_-]+", name):
        # Prefer last underscore-separated token (common in GEO names)
        tokens = name.split("_")
        # If last token is all digits, skip
        for tok in reversed(tokens):
            if not tok.isdigit() and tok:
                return tok.upper()
        return name.upper()
    return None


def _extract_target_gene(label: str) -> str | None:
    """Extract a target gene symbol from a Perturb-seq guide label.

    Handles labels like:
      p_sgEGR1_3   -> EGR1
      p_sgIRF1_2   -> IRF1
      p_sgNR2C2_5  -> NR2C2
      p_INTERGENIC1144056 -> None (control / observational)
    """
    label = label.strip()
    if label.lower().startswith("p_intergenic"):
        return None
    m = re.match(r"p_sg([A-Za-z0-9]+)_\d+", label)
    if m:
        return m.group(1).upper()
    return None


def _read_cbc_gbc_dict(path: str) -> dict[str, str]:
    """Map cell barcode -> target gene / perturbation label.

    Handles several conventions:
      cell_barcode, target_gene
      cell_barcode, guide_barcode, target_gene
      cell, guide, gene
      target_label,"barcode1, barcode2, ..."  (GSE90063 style)
    """
    mapping: dict[str, str] = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header: list[str] | None = None
        format_gse90063 = False
        for row in reader:
            if not row:
                continue
            if header is None:
                header = [h.strip().lower() for h in row]
                if any(
                    k in h for h in header for k in ("cell", "barcode", "target", "gene")
                ):
                    # One-cell-per-row header; map columns by name below.
                    continue
                # No recognisable header: inspect first data row.
                first = row[0].strip()
                if _extract_target_gene(first) is not None or first.lower().startswith("p_intergenic"):
                    format_gse90063 = True
                header = []
                # Fall through to parse the first data row.

            if len(row) < 2:
                continue

            if format_gse90063:
                # GSE90063 style: target_label, "barcode1, barcode2, ..."
                target_label = row[0].strip()
                target_gene = _extract_target_gene(target_label)
                if target_gene is None:
                    # control / intergenic -> observational marker
                    target_gene = "NON-TARGET"
                barcodes: list[str] = []
                for part in row[1:]:
                    barcodes.extend(b.strip() for b in part.split(",") if b.strip())
                for bc in barcodes:
                    mapping[bc] = target_gene
            else:
                # one-cell-per-row formats: infer target column from header if present.
                target_col = len(row) - 1
                if header:
                    candidate_cols = [
                        i
                        for i, h in enumerate(header)
                        if "target" in h or "gene" in h
                    ]
                    if candidate_cols:
                        target_col = max(candidate_cols)
                cell = row[0].strip()
                target = row[target_col].strip()
                mapping[cell] = target
    return mapping


def _is_observational_target(target: str) -> bool:
    """Heuristic: non-targeting / control guides are observational."""
    t = target.lower()
    return (
        "non-target" in t
        or "non_target" in t
        or "nt" == t
        or "control" in t
        or "safe" in t
        or t == ""
        or "na" == t
        or "intergenic" in t
    )


def _read_sparse_matrix(
    path: str,
    selected_rows: set[int],
    selected_cols: set[int],
) -> dict[int, dict[int, float]]:
    """Read a MatrixMarket .mtx.txt.gz, keeping only selected rows/cols.

    Returns {row_index: {col_index: value}} in 0-indexed coordinates.
    """
    data: dict[int, dict[int, float]] = {r: {} for r in selected_rows}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        # Skip header / comments
        line = fh.readline()
        while line.startswith("%"):
            line = fh.readline()
        # dimensions line
        while line.strip() == "":
            line = fh.readline()
        # row_count col_count nnz
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                row = int(parts[0]) - 1
                col = int(parts[1]) - 1
                value = float(parts[2])
            except ValueError:
                continue
            if row in selected_rows and col in selected_cols:
                data[row][col] = value
    return data


def _normalize(
    rows: list[list[float]], method: str = "log1p"
) -> list[list[float]]:
    if method == "log1p":
        return [[math.log1p(v) for v in row] for row in rows]
    return rows


def _standardize_rows(rows: list[list[float]]) -> list[list[float]]:
    """Standardize each column using its mean/std across all provided rows."""
    if not rows:
        return rows
    n = len(rows[0])
    means = [sum(row[j] for row in rows) / len(rows) for j in range(n)]
    stds = []
    for j in range(n):
        m = means[j]
        v = sum((row[j] - m) ** 2 for row in rows) / len(rows)
        stds.append(math.sqrt(v) if v > 0 else 1.0)
    return [[(row[j] - means[j]) / stds[j] for j in range(n)] for row in rows]


def preprocess(
    tar_path: str,
    sample: str,
    lock: dict[str, Any],
    spec: dict[str, Any],
    max_cells_per_intervention: int,
    log1p_normalize: bool,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(tar_path, "r") as tar:
            mtx_name = f"{sample}.mtx.txt.gz"
            dict_name = f"{sample}_cbc_gbc_dict.csv.gz"
            # Some samples have lenient/strict variants; prefer the plain dict
            if dict_name not in tar.getnames():
                dict_name = f"{sample}_cbc_gbc_dict_lenient.csv.gz"
            cellnames_name = f"{sample}_cellnames.csv.gz"
            genenames_name = f"{sample}_genenames.csv.gz"

            required = [mtx_name, dict_name, cellnames_name, genenames_name]
            missing = [n for n in required if n not in tar.getnames()]
            if missing:
                raise FileNotFoundError(
                    f"Tar missing required members for {sample}: {missing}. "
                    f"Available: {tar.getnames()[:20]}..."
                )

            mtx_path = _extract_member(tar, mtx_name, tmp)
            dict_path = _extract_member(tar, dict_name, tmp)
            cellnames_path = _extract_member(tar, cellnames_name, tmp)
            genenames_path = _extract_member(tar, genenames_name, tmp)

        cellnames = _read_cellnames(cellnames_path)
        genenames = _read_genenames(genenames_path)
        cell_to_target = _read_cbc_gbc_dict(dict_path)

        # Map locked genes to matrix rows
        locked_genes = [g.upper() for g in lock.get("locked_genes", [])]
        gene_to_row: dict[str, int] = {}
        for idx, name in genenames.items():
            sym = _extract_symbol(name)
            if sym and sym in locked_genes and sym not in gene_to_row:
                gene_to_row[sym] = idx

        present_genes = list(gene_to_row.keys())
        missing_genes = [g for g in locked_genes if g not in gene_to_row]
        if len(present_genes) < 10:
            raise ValueError(
                f"Too few locked genes present in dataset: {len(present_genes)}/12. "
                f"Missing: {missing_genes}"
            )

        # Order selected genes alphabetically for deterministic index mapping
        selected_genes = sorted(present_genes)
        selected_rows = {gene_to_row[g] for g in selected_genes}

        # Classify cells
        observational_cols: list[int] = []
        target_to_cols: dict[str, list[int]] = {}
        for col_idx, barcode in cellnames.items():
            target = cell_to_target.get(barcode)
            if target is None or _is_observational_target(target):
                observational_cols.append(col_idx)
            else:
                target_to_cols.setdefault(target, []).append(col_idx)

        # Only keep targets that are among selected genes (pathway-internal KOs)
        ko_targets = sorted(
            t for t in target_to_cols if t.upper() in {g.upper() for g in selected_genes}
        )
        if len(ko_targets) < 5:
            raise ValueError(
                f"Insufficient consultable KO targets among selected genes: {len(ko_targets)}"
            )

        # Split KOs into consultable S and held-out T
        rng = random.Random(spec.get("train_test_split_seed", 12345))
        shuffled = list(ko_targets)
        rng.shuffle(shuffled)
        split_at = int(len(shuffled) * spec.get("consultable_fraction", 0.7))
        consultable_targets = sorted(shuffled[:split_at])
        held_out_targets = sorted(shuffled[split_at:])

        if len(held_out_targets) < 2:
            raise ValueError(
                f"Too few held-out targets ({len(held_out_targets)}); need >= 2"
            )

        # Read sparse matrix for selected rows and all relevant columns
        relevant_cols = set(observational_cols)
        for cols in target_to_cols.values():
            relevant_cols.update(cols)
        matrix = _read_sparse_matrix(mtx_path, selected_rows, relevant_cols)

        # Build gene-index mapping
        gene_index = {gene: i for i, gene in enumerate(selected_genes)}

        def _get_vector(col_idx: int) -> list[float]:
            return [matrix[gene_to_row[g]].get(col_idx, 0.0) for g in selected_genes]

        # Observational cells
        obs_vectors = [_get_vector(c) for c in observational_cols]
        if len(obs_vectors) < 50:
            raise ValueError(f"Too few observational cells: {len(obs_vectors)}")

        # Interventions: downsample to max_cells_per_intervention
        consultable: dict[tuple[int, str], list[list[float]]] = {}
        held_out: dict[tuple[int, str], list[list[float]]] = {}
        for target in consultable_targets:
            cols = target_to_cols[target]
            if len(cols) > max_cells_per_intervention:
                rng.shuffle(cols)
                cols = cols[:max_cells_per_intervention]
            target_idx = gene_index[target.upper()]
            consultable[(target_idx, "ko")] = [_get_vector(c) for c in cols]
        for target in held_out_targets:
            cols = target_to_cols[target]
            if len(cols) > max_cells_per_intervention:
                rng.shuffle(cols)
                cols = cols[:max_cells_per_intervention]
            target_idx = gene_index[target.upper()]
            held_out[(target_idx, "ko")] = [_get_vector(c) for c in cols]

        # Normalize and standardize using observational statistics only
        if log1p_normalize:
            obs_vectors = _normalize(obs_vectors)
            consultable = {
                k: _normalize(v) for k, v in consultable.items()
            }
            held_out = {k: _normalize(v) for k, v in held_out.items()}

        flattened = (
            obs_vectors
            + [row for lst in consultable.values() for row in lst]
            + [row for lst in held_out.values() for row in lst]
        )
        standardized = _standardize_rows(flattened)
        # unpack
        n_obs = len(obs_vectors)
        n_con = sum(len(v) for v in consultable.values())
        obs_vectors = standardized[:n_obs]
        rest = standardized[n_obs:]
        consultable = {
            k: rest[i : i + len(v)]
            for i, (k, v) in enumerate(consultable.items())
        }
        rest = rest[n_con:]
        held_out = {
            k: rest[i : i + len(v)]
            for i, (k, v) in enumerate(held_out.items())
        }

        return {
            "accession": lock.get("accession"),
            "publication": lock.get("publication"),
            "pathway": lock.get("pathway"),
            "pathway_id": lock.get("pathway_id"),
            "sample": sample,
            "n_cells_observational": len(obs_vectors),
            "n_consultable_interventions": len(consultable),
            "n_held_out_interventions": len(held_out),
            "selected_genes": selected_genes,
            "gene_index": gene_index,
            "locked_genes_present": present_genes,
            "locked_genes_missing": missing_genes,
            "consultable_targets": consultable_targets,
            "held_out_targets": held_out_targets,
            "observational_cells": obs_vectors,
            "consultable_interventions": {
                f"{k[0]}:{k[1]}": v for k, v in consultable.items()
            },
            "held_out_interventions": {
                f"{k[0]}:{k[1]}": v for k, v in held_out.items()
            },
        }


def main() -> int:
    args = _parse_args()
    lock = _load_json(args.lock)
    spec = _load_json(args.spec)

    result = preprocess(
        tar_path=args.tar,
        sample=args.sample,
        lock=lock,
        spec=spec,
        max_cells_per_intervention=args.max_cells_per_intervention,
        log1p_normalize=args.log1p_normalize,
    )

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)

    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
