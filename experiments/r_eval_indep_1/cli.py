"""Development-only corpus CLI for R-EVAL-INDEP-1 Batch-2B.

The closed command surface can compile or verify the pinned corpus.  It has no
provider transport, reviewer invocation, result runner, r-final, scientific
verdict, freeze, or promotion entry point.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from . import EVIDENCE_STATUS, PROVIDER_FALLBACK
from .contracts import CaseTruth
from .corpus_registry import CompiledCorpus, compile_corpus_dev
from .qualifier import verify_corpus_dev


REPO_ROOT = Path(__file__).resolve().parents[2]


def _base_payload(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "evidence_status": EVIDENCE_STATUS,
        "freeze_status": "NOT_FROZEN",
        "run_status": "NOT_RUN",
        "scientific_verdict": None,
        "provider_calls": 0,
        "provider_fallback": PROVIDER_FALLBACK,
        "result_run": False,
        "result_run_available": False,
    }


def _corpus_summary(corpus: CompiledCorpus) -> dict[str, Any]:
    harmful = [
        case for case in corpus.cases if case.recipe.case_truth is CaseTruth.HARMFUL
    ]
    clean = [
        case for case in corpus.cases if case.recipe.case_truth is CaseTruth.CLEAN
    ]
    manifest = corpus.manifest
    return {
        "corpus_id": manifest.corpus_id,
        "case_count": len(corpus.cases),
        "harmful_count": len(harmful),
        "clean_count": len(clean),
        "mutation_classes": sorted(
            case.recipe.mutation_class.value
            for case in harmful
            if case.recipe.mutation_class is not None
        ),
        "runner_sha256": manifest.runner_sha256,
        "public_cases_sha256": manifest.public_cases_sha256,
        "referee_cases_sha256": manifest.referee_cases_sha256,
        "corpus_manifest_sha256": manifest.corpus_manifest_sha256,
    }


def _compile_corpus_dev() -> dict[str, Any]:
    corpus = compile_corpus_dev(REPO_ROOT)
    payload = _base_payload("compile-corpus-dev")
    payload.update(_corpus_summary(corpus))
    return payload


def _verify_corpus_dev() -> dict[str, Any]:
    corpus = compile_corpus_dev(REPO_ROOT)
    records = verify_corpus_dev(corpus)
    payload = _base_payload("verify-corpus-dev")
    payload.update(_corpus_summary(corpus))
    payload.update(
        {
            "qualified_count": sum(record.qualified for record in records),
            "records": [record.to_mapping() for record in records],
        }
    )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "compile-corpus-dev",
        help="compile the pinned corpus manifest as NOT_EVIDENCE",
    )
    subparsers.add_parser(
        "verify-corpus-dev",
        help="verify the pinned corpus in isolated Python workers as NOT_EVIDENCE",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "compile-corpus-dev":
        payload = _compile_corpus_dev()
    elif args.command == "verify-corpus-dev":
        payload = _verify_corpus_dev()
    else:  # pragma: no cover - argparse owns this closed branch
        raise AssertionError("unreachable command")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
