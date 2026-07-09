"""Leak-probe harness for strong-locus Stage 4 Perturb-seq.

Presents an anonymized view of the data (correlation matrix + marginal
histograms + dynamics description) to a locked LLM and checks whether it can
re-identify the dataset, pathway, or gene names. Seeds that exceed the frozen
chance threshold are discarded before scoring.

Pure stdlib. Run from autonomous-agent-core root:
    PYTHONPATH=src python experiments/strong_locus_leak_probe.py \
        --preprocessed experiments/perturb_seq_preprocessed.json \
        --spec experiments/strong_locus_stage4.spec.json \
        --output experiments/strong_locus_leak_probe.result.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from typing import Any

sys.path.insert(0, "src")
sys.path.insert(0, "experiments")

from aac.llm_client import build_backend
from aac.plumbing_instrument import PlumbingInstrument


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strong-locus Stage 4 leak probe")
    parser.add_argument(
        "--preprocessed",
        required=True,
        help="Preprocessed Perturb-seq JSON from perturb_seq_preprocessing.py",
    )
    parser.add_argument(
        "--spec",
        default="experiments/strong_locus_stage4.spec.json",
        help="Stage 4 spec JSON",
    )
    parser.add_argument(
        "--output",
        default="experiments/strong_locus_leak_probe.result.json",
        help="Output result JSON",
    )
    parser.add_argument(
        "--backend",
        choices=["stub", "anthropic", "openai"],
        default="stub",
        help="LLM backend",
    )
    return parser.parse_args()


def _load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _anonymize_tokens(n_nodes: int, seed: int) -> list[str]:
    """Return anonymized token names that do not leak gene identity."""
    rng = random.Random(seed)
    pool = [f"X{i:02d}" for i in range(n_nodes)]
    rng.shuffle(pool)
    return pool


def _correlation_matrix(data: list[list[float]]) -> list[list[float]]:
    n = len(data[0])
    means = [sum(row[j] for row in data) / len(data) for j in range(n)]
    stds = []
    for j in range(n):
        v = sum((row[j] - means[j]) ** 2 for row in data) / len(data)
        stds.append(math.sqrt(v) if v > 0 else 1.0)

    corr = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                corr[i][j] = 1.0
                continue
            num = sum((row[i] - means[i]) * (row[j] - means[j]) for row in data)
            denom = stds[i] * stds[j] * len(data)
            corr[i][j] = num / denom if denom > 0 else 0.0
    return corr


def _marginal_histograms(data: list[list[float]], bins: int = 10) -> list[list[float]]:
    n = len(data[0])
    hists = []
    for j in range(n):
        vals = [row[j] for row in data]
        lo, hi = min(vals), max(vals)
        if hi == lo:
            hists.append([1.0] + [0.0] * (bins - 1))
            continue
        counts = [0] * bins
        for v in vals:
            idx = min(bins - 1, int((v - lo) / (hi - lo) * bins))
            counts[idx] += 1
        total = len(vals)
        hists.append([c / total for c in counts])
    return hists


def _build_prompt(
    data: list[list[float]],
    tokens: list[str],
    dynamics_description: str,
) -> str:
    corr = _correlation_matrix(data)
    hists = _marginal_histograms(data)
    n = len(tokens)

    lines = [
        "You are shown an anonymized single-cell perturbation dataset.",
        "Do not use outside knowledge. Answer only based on the provided summary.",
        "",
        dynamics_description,
        "",
        f"Variables (anonymized tokens): {tokens}",
        "",
        "Pairwise absolute correlation matrix (upper triangle):",
    ]
    for i in range(n):
        for j in range(i + 1, n):
            lines.append(f"  {tokens[i]} <-> {tokens[j]}: {abs(corr[i][j]):.3f}")

    lines.extend(["", "Marginal histograms (bin frequencies):"])
    for i in range(n):
        lines.append(f"  {tokens[i]}: {[round(h, 3) for h in hists[i]]}")

    lines.extend([
        "",
        "Question: Based only on the above, can you identify any of the following?",
        "  1. The GEO accession or publication of this dataset.",
        "  2. The biological pathway or gene set represented by these variables.",
        "  3. The real gene names corresponding to the anonymized tokens.",
        "",
        "Return a JSON object with keys: {'dataset_guess': str, 'pathway_guess': str, 'gene_mapping': {token: gene_name}}.",
        "If you cannot identify anything, return empty strings and an empty mapping.",
    ])
    return "\n".join(lines)


def _score_leak(
    response: dict[str, Any],
    actual_accession: str,
    actual_pathway: str,
    actual_genes: list[str],
    tokens: list[str],
    chance_threshold: float,
) -> bool:
    """Return True if the seed fails the leak probe (re-identification)."""
    text = json.dumps(response).lower()
    accession_hits = actual_accession.lower() in text
    pathway_hits = actual_pathway.lower() in text
    gene_hits = sum(1 for g in actual_genes if g.lower() in text)
    token_hits = sum(1 for t in tokens if t.lower() in text and t.lower() in text)

    # A seed fails if any of the protected identifiers are named.
    if accession_hits or pathway_hits:
        return True
    # Naming more than chance_threshold fraction of genes also fails.
    if len(actual_genes) > 0 and gene_hits / len(actual_genes) > chance_threshold:
        return True
    return False


def run_leak_probe(
    preprocessed: dict[str, Any],
    spec: dict[str, Any],
    backend: Any,
) -> dict[str, Any]:
    actual_accession = preprocessed.get("accession", "")
    actual_pathway = preprocessed.get("pathway", "")
    actual_genes = preprocessed.get("selected_genes", [])
    observational = preprocessed.get("observational_cells", [])
    n_nodes = len(observational[0]) if observational else 0

    chance_threshold = spec.get("leak_probe_chance_threshold", 0.10)
    n_seeds = spec.get("leak_probe_seeds", 5)
    seed_base = spec.get("leak_probe_seed_base", 6000)

    dynamics_description = (
        "This is a single-cell CRISPR knock-out transcriptomics dataset. "
        "Each variable is a gene measured across cells. Some cells received a "
        "targeted knock-out intervention; others are observational controls."
    )

    instrument = PlumbingInstrument(run_id="leak_probe", arm="leak_probe")
    backend.instrument = instrument

    failed_seeds: list[int] = []
    passed_seeds: list[int] = []
    details: list[dict[str, Any]] = []

    for i in range(n_seeds):
        seed = seed_base + i
        tokens = _anonymize_tokens(n_nodes, seed)
        prompt = _build_prompt(observational, tokens, dynamics_description)
        response = backend.call(prompt)
        failed = _score_leak(
            response, actual_accession, actual_pathway, actual_genes, tokens, chance_threshold
        )
        if failed:
            failed_seeds.append(seed)
        else:
            passed_seeds.append(seed)
        details.append(
            {
                "seed": seed,
                "failed": failed,
                "response_keys": list(response.keys()) if isinstance(response, dict) else [],
            }
        )

    all_failed = len(passed_seeds) == 0 and n_seeds > 0
    verdict = "HONEST_NEGATIVE" if all_failed else "RUNNABLE"

    return {
        "verdict": verdict,
        "actual_accession": actual_accession,
        "actual_pathway": actual_pathway,
        "actual_genes": actual_genes,
        "n_seeds": n_seeds,
        "failed_seeds": failed_seeds,
        "passed_seeds": passed_seeds,
        "chance_threshold": chance_threshold,
        "backend": spec.get("model_lock", "unknown"),
        "stub_only": getattr(backend, "stub_only", True),
        "plumbing_counts": instrument.counts(),
        "details": details,
    }


def main() -> int:
    args = _parse_args()
    preprocessed = _load_json(args.preprocessed)
    spec = _load_json(args.spec)

    backend = build_backend(args.backend)
    result = run_leak_probe(preprocessed, spec, backend)

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)

    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
