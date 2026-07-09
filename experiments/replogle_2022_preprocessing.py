"""Replogle 2022 K562 GWPS Perturb-seq preprocessing for strong-locus Stage 4.

Reads the figshare bulk h5ad (`K562_gwps_normalized_bulk_01.h5ad`), selects the
locked KEGG p53-pathway genes, aggregates guide-level pseudo-bulk rows by target
gene, splits KO targets into consultable S and held-out T, and emits a normalized
JSON consumable by the strong-locus Stage 4 runner.

Requires `anndata` and `h5py` (available in the repo virtualenv but not declared
as project dependencies, because the rest of the core is pure stdlib).

Run from autonomous-agent-core root:
    PYTHONPATH=src .venv/bin/python experiments/replogle_2022_preprocessing.py \
        --h5ad experiments/data/perturb_seq/K562_gwps_normalized_bulk_01.h5ad \
        --lock experiments/variable_selection_lock.json \
        --spec experiments/strong_locus_stage4_replogle_2022.spec.json \
        --output experiments/replogle_2022_preprocessed.json \
        --csv experiments/replogle_2022_preprocessed.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import re
import sys
from typing import Any

sys.path.insert(0, "src")
sys.path.insert(0, "experiments")

import numpy as np


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replogle 2022 K562 GWPS preprocessing")
    parser.add_argument(
        "--h5ad",
        default="experiments/data/perturb_seq/K562_gwps_normalized_bulk_01.h5ad",
        help="Path to K562_gwps_normalized_bulk_01.h5ad",
    )
    parser.add_argument(
        "--lock",
        default="experiments/variable_selection_lock.json",
        help="variable_selection_lock.json",
    )
    parser.add_argument(
        "--spec",
        default="experiments/strong_locus_stage4_replogle_2022.spec.json",
        help="Stage 4 spec JSON for Replogle 2022",
    )
    parser.add_argument(
        "--output",
        default="experiments/replogle_2022_preprocessed.json",
        help="Output preprocessed JSON",
    )
    parser.add_argument(
        "--csv",
        default="experiments/replogle_2022_preprocessed.csv",
        help="Output CSV preview (one row per aggregated observation)",
    )
    parser.add_argument(
        "--max-observational-rows",
        type=int,
        default=200,
        help="Cap the number of observational (non-targeting) rows kept",
    )
    parser.add_argument(
        "--log1p-normalize",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply log1p normalization (default true)",
    )
    return parser.parse_args()


def _load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def extract_target_gene(obs_index: str) -> str | None:
    """Extract target gene symbol from h5ad obs index like '105_ACTG1_P1P2_ENSG...'."""
    idx = str(obs_index)
    # Control rows look like '10928_NON-TARGETING_NON-TARGETING'
    if "NON-TARGET" in idx.upper():
        return "NON-TARGETING"
    m = re.match(r"^\d+_(.+?)_", idx)
    if not m:
        return None
    body = m.group(1).upper()
    return body


def find_locked_genes(
    var_names: dict[str, int],
    locked_genes: list[str],
) -> dict[str, int]:
    """Map locked gene symbol -> var index, deterministic first match."""
    gene_to_col: dict[str, int] = {}
    for gene in locked_genes:
        g = gene.upper()
        if g in var_names and g not in gene_to_col:
            gene_to_col[g] = var_names[g]
    return gene_to_col


def aggregate_by_target(
    X: np.ndarray,
    targets: list[str],
) -> tuple[dict[str, np.ndarray], dict[str, int]]:
    """Average all rows belonging to the same target gene.

    Returns (target -> mean vector, target -> count).
    """
    groups: dict[str, list[np.ndarray]] = {}
    for t, row in zip(targets, X):
        groups.setdefault(t, []).append(row)
    means: dict[str, np.ndarray] = {}
    counts: dict[str, int] = {}
    for t, rows in groups.items():
        arr = np.stack(rows, axis=0)
        means[t] = np.mean(arr, axis=0)
        counts[t] = arr.shape[0]
    return means, counts


def _normalize_log1p(rows: list[list[float]]) -> list[list[float]]:
    return [[math.log1p(max(v, 0.0)) for v in row] for row in rows]


def _standardize_rows(rows: list[list[float]]) -> list[list[float]]:
    """Standardize each column to mean 0, std 1 across rows."""
    if not rows:
        return rows
    arr = np.asarray(rows, dtype=float)
    means = np.mean(arr, axis=0)
    stds = np.std(arr, axis=0)
    stds[stds == 0] = 1.0
    standardized = (arr - means) / stds
    return standardized.tolist()


def preprocess(
    h5ad_path: str,
    lock: dict[str, Any],
    spec: dict[str, Any],
    max_observational_rows: int,
    log1p_normalize: bool,
) -> dict[str, Any]:
    import anndata

    ad = anndata.read_h5ad(h5ad_path)

    # Locked genes present in var gene_name
    locked_genes = [g.upper() for g in lock.get("locked_genes", [])]
    var_name_to_col = {
        str(name).upper(): i for i, name in enumerate(ad.var["gene_name"].astype(str))
    }
    gene_to_col = find_locked_genes(var_name_to_col, locked_genes)
    selected_genes = sorted(gene_to_col.keys())
    missing_genes = sorted(set(locked_genes) - set(selected_genes))
    if len(selected_genes) < 10:
        raise ValueError(
            f"Too few locked genes present in dataset: {len(selected_genes)}/12. "
            f"Missing: {missing_genes}"
        )

    # Extract target gene for each obs row
    obs_targets = [extract_target_gene(str(idx)) for idx in ad.obs.index]

    # Select only columns (genes) corresponding to selected locked genes, in order
    selected_cols = [gene_to_col[g] for g in selected_genes]
    X = ad.X[:, selected_cols]
    # Ensure dense; bulk data is already numpy.ndarray, but be safe
    if hasattr(X, "toarray"):
        X = X.toarray()
    X = np.asarray(X, dtype=float)

    # Separate control rows (keep individual cells for observational covariance)
    # from KO rows (aggregate multiple guides per target gene).
    control_mask = np.asarray([t == "NON-TARGETING" for t in obs_targets], dtype=bool)
    if not np.any(control_mask):
        raise ValueError("No NON-TARGETING control rows found in h5ad obs index")
    observational_vectors = X[control_mask].tolist()

    # Cap observational rows
    rng = random.Random(spec.get("train_test_split_seed", 12345))
    if len(observational_vectors) > max_observational_rows:
        rng.shuffle(observational_vectors)
        observational_vectors = observational_vectors[:max_observational_rows]

    # Aggregate guide-level rows by target gene for KOs
    ko_mask = ~control_mask
    means, counts = aggregate_by_target(X[ko_mask], [t for t, m in zip(obs_targets, ko_mask) if m])

    # KO targets among selected genes
    ko_targets = sorted(
        t for t in means if t.upper() in {g.upper() for g in selected_genes}
    )
    if len(ko_targets) < 5:
        raise ValueError(
            f"Insufficient consultable KO targets among selected genes: {len(ko_targets)}"
        )

    # Split into consultable S and held-out T
    split_rng = random.Random(spec.get("train_test_split_seed", 12345))
    shuffled = list(ko_targets)
    split_rng.shuffle(shuffled)
    consultable_fraction = spec.get("consultable_fraction", 0.7)
    split_at = int(len(shuffled) * consultable_fraction)
    consultable_targets = sorted(shuffled[:split_at])
    held_out_targets = sorted(shuffled[split_at:])
    if len(held_out_targets) < 2:
        raise ValueError(f"Too few held-out targets ({len(held_out_targets)}); need >= 2")

    gene_index = {gene: i for i, gene in enumerate(selected_genes)}

    def make_intervention_entry(target: str) -> tuple[str, list[list[float]]]:
        target_idx = gene_index[target.upper()]
        return f"{target_idx}:ko", [means[target].tolist()]

    consultable_interventions = dict(make_intervention_entry(t) for t in consultable_targets)
    held_out_interventions = dict(make_intervention_entry(t) for t in held_out_targets)

    # Normalize and standardize
    if log1p_normalize:
        observational_vectors = _normalize_log1p(observational_vectors)
        consultable_interventions = {
            k: _normalize_log1p(v) for k, v in consultable_interventions.items()
        }
        held_out_interventions = {
            k: _normalize_log1p(v) for k, v in held_out_interventions.items()
        }

    flattened = (
        observational_vectors
        + [row for lst in consultable_interventions.values() for row in lst]
        + [row for lst in held_out_interventions.values() for row in lst]
    )
    standardized = _standardize_rows(flattened)
    n_obs = len(observational_vectors)
    n_con = sum(len(v) for v in consultable_interventions.values())
    observational_vectors = standardized[:n_obs]
    rest = standardized[n_obs:]
    consultable_interventions = {
        k: rest[i : i + len(v)]
        for i, (k, v) in enumerate(consultable_interventions.items())
    }
    rest = rest[n_con:]
    held_out_interventions = {
        k: rest[i : i + len(v)]
        for i, (k, v) in enumerate(held_out_interventions.items())
    }

    return {
        "accession": spec.get("accession"),
        "publication": spec.get("dataset"),
        "pathway": lock.get("pathway"),
        "pathway_id": lock.get("pathway_id"),
        "sample": os.path.basename(h5ad_path),
        "n_cells_observational": len(observational_vectors),
        "n_consultable_interventions": len(consultable_interventions),
        "n_held_out_interventions": len(held_out_interventions),
        "selected_genes": selected_genes,
        "gene_index": gene_index,
        "locked_genes_present": selected_genes,
        "locked_genes_missing": missing_genes,
        "consultable_targets": consultable_targets,
        "held_out_targets": held_out_targets,
        "target_aggregation_counts": {t: counts[t] for t in sorted(counts) if t in selected_genes or t == "NON-TARGETING"},
        "observational_cells": observational_vectors,
        "consultable_interventions": consultable_interventions,
        "held_out_interventions": held_out_interventions,
    }


def write_csv_preview(path: str, result: dict[str, Any]) -> None:
    """Write a human-readable CSV preview: one row per aggregated observation."""
    genes = result["selected_genes"]
    rows: list[list[Any]] = []
    for vec in result["observational_cells"]:
        rows.append(["observational", "control"] + vec)
    for key, vecs in result["consultable_interventions"].items():
        target_idx = int(key.split(":")[0])
        target = result["selected_genes"][target_idx]
        for vec in vecs:
            rows.append(["consultable", target] + vec)
    for key, vecs in result["held_out_interventions"].items():
        target_idx = int(key.split(":")[0])
        target = result["selected_genes"][target_idx]
        for vec in vecs:
            rows.append(["held_out", target] + vec)

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["split", "target"] + genes)
        writer.writerows(rows)


def main() -> int:
    args = _parse_args()
    lock = _load_json(args.lock)
    spec = _load_json(args.spec)

    result = preprocess(
        h5ad_path=args.h5ad,
        lock=lock,
        spec=spec,
        max_observational_rows=args.max_observational_rows,
        log1p_normalize=args.log1p_normalize,
    )

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
    write_csv_preview(args.csv, result)

    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"\nWrote {args.output}")
    print(f"Wrote {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
