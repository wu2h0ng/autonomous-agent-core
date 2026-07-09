"""Diagnostic for Replogle 2022 Stage 4 held-out intervention signal strength.

Computes standardized mean differences and SEM-thresholded scores for every
held-out intervention against observational controls, across a range of
effect thresholds. Emits a JSON that explains why n_true == 0 under the
locked threshold and records the honest-negative/insufficient-data verdict.

Run from autonomous-agent-core root:
    PYTHONPATH=src .venv/bin/python experiments/strong_locus_stage4_replogle_2022_diagnostic.py
"""
from __future__ import annotations

import json
import math
import sys
from typing import Any

sys.path.insert(0, "src")
sys.path.insert(0, "experiments")


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    count = 0
    mean = 0.0
    m2 = 0.0
    for x in values:
        count += 1
        delta = x - mean
        mean += delta / count
        delta2 = x - mean
        m2 += delta * delta2
    var = m2 / (count - 1) if count > 1 else 0.0
    return var ** 0.5


def load_preprocessed(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def effect_sizes(
    held_out: dict[str, list[list[float]]],
    observational: list[list[float]],
    gene_index: dict[str, int],
    selected_genes: list[str],
) -> list[dict[str, Any]]:
    n_nodes = len(selected_genes)
    obs_mean = [_mean([row[j] for row in observational]) for j in range(n_nodes)]
    obs_std = [_std([row[j] for row in observational]) for j in range(n_nodes)]
    records: list[dict[str, Any]] = []
    for key, data in held_out.items():
        target_idx = int(key.split(":")[0])
        target_name = selected_genes[target_idx]
        for j in range(n_nodes):
            if j == target_idx:
                continue
            interv_values = [row[j] for row in data]
            interv_mean = _mean(interv_values)
            diff = interv_mean - obs_mean[j]
            sem = _std(interv_values) / (len(interv_values) ** 0.5)
            sem_score = abs(diff) / (sem if sem > 1e-9 else 1.0)
            std_score = abs(diff) / (obs_std[j] if obs_std[j] > 1e-9 else 1.0)
            records.append(
                {
                    "target": target_name,
                    "target_idx": target_idx,
                    "effect_node": selected_genes[j],
                    "effect_node_idx": j,
                    "n_intervention_samples": len(data),
                    "observational_mean": obs_mean[j],
                    "intervention_mean": interv_mean,
                    "mean_diff": diff,
                    "observational_std": obs_std[j],
                    "sem": sem,
                    "sem_score": sem_score,
                    "std_score": std_score,
                }
            )
    return records


def n_true_at_thresholds(records: list[dict[str, Any]]) -> dict[str, dict[float, int]]:
    thresholds = [0.5, 1.0, 1.5, 2.0, 3.0]
    return {
        "sem": {t: sum(1 for r in records if r["sem_score"] >= t) for t in thresholds},
        "std": {t: sum(1 for r in records if r["std_score"] >= t) for t in thresholds},
    }


def main() -> int:
    preprocessed = load_preprocessed("experiments/replogle_2022_preprocessed.json")
    selected_genes = preprocessed["selected_genes"]
    observational = preprocessed["observational_cells"]
    held_out = preprocessed["held_out_interventions"]

    records = effect_sizes(held_out, observational, preprocessed["gene_index"], selected_genes)
    by_threshold = n_true_at_thresholds(records)

    locked_threshold = 1.5
    n_true_locked = by_threshold["sem"][locked_threshold]

    top_sem = sorted(records, key=lambda r: r["sem_score"], reverse=True)[:10]
    top_std = sorted(records, key=lambda r: r["std_score"], reverse=True)[:10]

    result: dict[str, Any] = {
        "diagnostic_type": "replogle_2022_stage4_signal_strength",
        "run_at": "2026-07-06T22:00:00Z",
        "dataset": "Replogle_2022_K562_GWPS",
        "locked_threshold": locked_threshold,
        "n_held_out_interventions": len(held_out),
        "total_possible_edges": len(records),
        "n_true_at_locked_threshold": n_true_locked,
        "n_true_by_threshold": by_threshold,
        "top_sem_scores": [
            {
                "target": r["target"],
                "effect_node": r["effect_node"],
                "n_samples": r["n_intervention_samples"],
                "mean_diff": r["mean_diff"],
                "sem_score": r["sem_score"],
                "std_score": r["std_score"],
            }
            for r in top_sem
        ],
        "top_std_scores": [
            {
                "target": r["target"],
                "effect_node": r["effect_node"],
                "n_samples": r["n_intervention_samples"],
                "mean_diff": r["mean_diff"],
                "sem_score": r["sem_score"],
                "std_score": r["std_score"],
            }
            for r in top_std
        ],
        "root_cause": (
            "The Replogle 2022 pseudo-bulk h5ad provides at most 1-2 aggregated "
            "observations per held-out perturbation target. With the locked SEM "
            "threshold of 1.5, no held-out intervention produces a standardized "
            "mean shift large enough to declare an empirical true edge. The data "
            "are therefore insufficient for the pre-registered Stage 4 structure "
            "crossover under the current threshold."
        ),
        "verdict": "INSUFFICIENT_DATA_HONEST_NEGATIVE",
        "next_options": [
            "Keep the locked threshold and declare Stage 4 not executable on this pseudo-bulk dataset; record the honest negative.",
            "Select a real-data dataset with many replicates per held-out intervention (e.g., single-cell-level counts or a bulk screen with biological replicates) and re-run under the same locked threshold.",
            "If and only if a new ADR/CTO gate is opened, lower the locked threshold or switch to a different empirical-truth definition and pre-register the change before touching data.",
        ],
    }

    with open(
        "experiments/strong_locus_stage4_replogle_2022_diagnostic.json",
        "w",
        encoding="utf-8",
    ) as fh:
        json.dump(result, fh, indent=2, sort_keys=True)

    print(json.dumps(result, indent=2, sort_keys=True))
    print("\nWrote experiments/strong_locus_stage4_replogle_2022_diagnostic.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
