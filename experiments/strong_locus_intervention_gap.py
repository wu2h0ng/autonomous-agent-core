"""Intervention-gap analyzer for strong-locus Stage 4.

Given a locked variable set and a Perturb-seq dataset, this module:

1. Reports which locked variables are observable in the gene list.
2. Reports which locked variables have CRISPR KO interventions available.
3. Proposes symbolic missing interventions (deterministic guide labels only).
4. Recommends whether to proceed, request missing interventions, or pivot.

This is a research-harness tool. It does not generate real biological sequences,
does not call LLMs, and does not execute experiments. Any "request" it produces
is a proposal for an external experimental operator or a future dataset switch.

Run from autonomous-agent-core root:
    PYTHONPATH=src python experiments/strong_locus_intervention_gap.py \
        --tar experiments/data/perturb_seq/GSM2396858_RAW.tar \
        --sample GSM2396858_k562_tfs_7 \
        --lock experiments/variable_selection_lock.json \
        --output experiments/strong_locus_intervention_gap.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
import tempfile
from typing import Any

sys.path.insert(0, "src")
sys.path.insert(0, "experiments")

try:
    from strong_locus_intervention_advisor import advise
except ImportError:
    from experiments.strong_locus_intervention_advisor import advise

from perturb_seq_preprocessing import (
    _extract_member,
    _extract_symbol,
    _extract_target_gene,
    _read_cbc_gbc_dict,
    _read_genenames,
)


DEFAULT_DATASET_CATALOGUE: dict[str, dict[str, Any]] = {
    "Replogle_2022_K562_GWPS": {
        "title": "Replogle et al. 2022, K562 genome-wide Perturb-seq (Cell)",
        "pmid": 35688146,
        "pmcid": "PMC9380471",
        "doi": "10.1016/j.cell.2022.05.013",
        "bioproject": "PRJNA831566",
        "sra_project": "SRP376262",
        "processed_data": "https://ndownloader.figshare.com/files/35773217 (K562_gwps_normalized_bulk_01.h5ad)",
        "coverage": "Genome-wide CRISPRi Perturb-seq in K562",
        "why": "10 of 12 locked KEGG p53-pathway genes are both measured and perturbed, exceeding the >=5 consultable-intervention threshold.",
        "verdict": "CANDIDATE_FIT",
        "assessment": "experiments/replogle_2022_k562_gwps_gap_assessment.json",
    },
    "GSE190604": {
        "title": "Schmidt/Steinhart et al. 2022, primary T-cell CRISPRa/i Perturb-seq",
        "coverage": "Primary human T cells; not K562",
        "why": "Previously misidentified as Replogle 2022. Different cell type and perturbation modality; not the target dataset for strong-locus Stage 4.",
        "verdict": "CATALOGUE_CORRECTION",
    },
    "GSE90063": {
        "title": "Dixit et al. 2016, Perturb-seq of K562 transcription factors",
        "coverage": "Transcription-factor KO screen",
        "why": "Initial sample; not suitable for p53 pathway because TF targets do not overlap pathway genes.",
        "verdict": "HONEST_NEGATIVE",
    },
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Intervention-gap analyzer")
    parser.add_argument(
        "--tar",
        default="experiments/data/perturb_seq/GSM2396858_RAW.tar",
        help="Path to the RAW tar archive",
    )
    parser.add_argument(
        "--sample",
        default="GSM2396858_k562_tfs_7",
        help="Sample prefix inside the tar",
    )
    parser.add_argument(
        "--lock",
        default="experiments/variable_selection_lock.json",
        help="variable_selection_lock.json",
    )
    parser.add_argument(
        "--output",
        default="experiments/strong_locus_intervention_gap.json",
        help="Output JSON report",
    )
    parser.add_argument(
        "--min-consultable",
        type=int,
        default=5,
        help="Minimum number of consultable interventions required",
    )
    parser.add_argument(
        "--guides-per-gene",
        type=int,
        default=3,
        help="Number of symbolic guide labels to propose per missing gene",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["stub", "anthropic", "openai"],
        default="stub",
        help="LLM advisor backend (default stub; falls back to stub if no API key)",
    )
    return parser.parse_args()


def _load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def extract_available_interventions(tar_path: str, sample: str) -> set[str]:
    """Return the set of KO target gene symbols present in the dataset."""
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(tar_path, "r") as tar:
            dict_name = f"{sample}_cbc_gbc_dict.csv.gz"
            if dict_name not in tar.getnames():
                dict_name = f"{sample}_cbc_gbc_dict_lenient.csv.gz"
            if dict_name not in tar.getnames():
                raise FileNotFoundError(
                    f"Tar missing cbc_gbc_dict for {sample}. Available: {tar.getnames()[:20]}..."
                )
            dict_path = _extract_member(tar, dict_name, tmp)
        cell_to_target = _read_cbc_gbc_dict(dict_path)
    targets: set[str] = set()
    for target in cell_to_target.values():
        gene = _extract_target_gene(target)
        if gene:
            targets.add(gene)
        elif target:
            # Some one-cell-per-row formats store the plain gene symbol.
            t = target.strip().upper()
            # Reject obvious control markers, but accept alphanumeric symbols.
            control_markers = {"NON-TARGET", "NON_TARGET", "NT", "CONTROL", "SAFE", "NA", "INTERGENIC"}
            if t and t not in control_markers and t.replace("-", "").replace("_", "").isalnum():
                targets.add(t)
    return targets


def extract_observable_locked_genes(tar_path: str, sample: str, locked_genes: list[str]) -> set[str]:
    """Return the subset of locked genes that appear in the dataset gene list."""
    locked_upper = {g.upper() for g in locked_genes}
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(tar_path, "r") as tar:
            genenames_name = f"{sample}_genenames.csv.gz"
            if genenames_name not in tar.getnames():
                raise FileNotFoundError(
                    f"Tar missing genenames for {sample}. Available: {tar.getnames()[:20]}..."
                )
            genenames_path = _extract_member(tar, genenames_name, tmp)
        genenames = _read_genenames(genenames_path)
    observable: set[str] = set()
    for name in genenames.values():
        sym = _extract_symbol(name)
        if sym and sym in locked_upper:
            observable.add(sym)
    return observable


def propose_missing_interventions(
    missing_genes: list[str],
    guides_per_gene: int = 3,
) -> dict[str, list[str]]:
    """Produce deterministic symbolic guide labels for missing interventions.

    These are placeholders for experimental design / dataset selection only.
    They are NOT real sgRNA sequences and must NOT be used in a wet lab.
    """
    proposal: dict[str, list[str]] = {}
    for gene in sorted(missing_genes):
        proposal[gene] = [f"p_sg{gene}_{i + 1}" for i in range(guides_per_gene)]
    return proposal


def recommend_action(
    n_consultable: int,
    n_observable: int,
    min_consultable: int,
    missing_for_intervention: list[str],
) -> dict[str, Any]:
    """Decide whether to proceed, request interventions, or pivot."""
    # Data-set coverage is the most basic gate: if the locked variables are not
    # even measured, no amount of additional intervention helps.
    if n_observable < 10:
        return {
            "action": "PIVOT_DATASET",
            "reason": "Too few locked genes are observable in this dataset; switching dataset is more promising than requesting interventions on genes not measured.",
            "candidate_datasets": ["Replogle_2022_K562_GWPS"],
        }

    if n_consultable >= min_consultable:
        return {
            "action": "PROCEED",
            "reason": "Enough locked genes have available CRISPR KO interventions.",
        }

    if missing_for_intervention:
        return {
            "action": "REQUEST_INTERVENTIONS",
            "reason": (
                f"Only {n_consultable} locked genes have interventions; need >= {min_consultable}. "
                "The missing genes are observable but not yet perturbed. A future experiment or dataset should include KO guides for them."
            ),
            "candidate_datasets": ["Replogle_2022_K562_GWPS"],
        }

    # Should not reach here, but keep explicit.
    return {
        "action": "HONEST_NEGATIVE",
        "reason": "No consultable interventions among locked genes and no actionable proposal.",
    }


def analyze_gap(
    lock: dict[str, Any],
    tar_path: str,
    sample: str,
    min_consultable: int = 5,
    guides_per_gene: int = 3,
) -> dict[str, Any]:
    locked_genes = [g.upper() for g in lock.get("locked_genes", [])]
    observable = extract_observable_locked_genes(tar_path, sample, locked_genes)
    available_interventions = extract_available_interventions(tar_path, sample)
    consultable = observable & available_interventions
    missing_from_dataset = sorted(set(locked_genes) - observable)
    missing_intervention = sorted(observable - available_interventions)

    proposal = propose_missing_interventions(missing_intervention, guides_per_gene)
    if missing_from_dataset:
        # Cannot request interventions on genes not measured at all.
        for gene in missing_from_dataset:
            proposal[gene] = []

    recommendation = recommend_action(
        n_consultable=len(consultable),
        n_observable=len(observable),
        min_consultable=min_consultable,
        missing_for_intervention=missing_intervention,
    )

    return {
        "accession": lock.get("accession"),
        "sample": sample,
        "pathway": lock.get("pathway"),
        "pathway_id": lock.get("pathway_id"),
        "locked_genes": sorted(locked_genes),
        "n_locked_genes": len(locked_genes),
        "observable_locked_genes": sorted(observable),
        "n_observable_locked_genes": len(observable),
        "missing_from_dataset": missing_from_dataset,
        "available_interventions": sorted(available_interventions),
        "n_available_interventions_total": len(available_interventions),
        "consultable_locked_genes": sorted(consultable),
        "n_consultable_locked_genes": len(consultable),
        "missing_intervention_for_observable": missing_intervention,
        "proposed_missing_interventions": proposal,
        "min_consultable_required": min_consultable,
        "recommendation": recommendation,
        "dataset_catalogue": DEFAULT_DATASET_CATALOGUE,
        "verdict": "FIT" if len(consultable) >= min_consultable else "NOT_FIT",
    }


def main() -> int:
    args = _parse_args()
    lock = _load_json(args.lock)
    report = analyze_gap(
        lock,
        args.tar,
        args.sample,
        min_consultable=args.min_consultable,
        guides_per_gene=args.guides_per_gene,
    )
    report["llm_advice"] = advise(report, provider=args.llm_provider)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
