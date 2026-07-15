"""Development-only CLI for R-EVAL-INDEP-1.

Only registry validation and synthetic development qualification exist. There is
no provider transport, provider fallback, r-final, scoring verdict, or promotion
entry point in this package.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from . import EVIDENCE_STATUS, PROVIDER_FALLBACK
from .mutations import REGISTRY, qualify_all_dev, registry_digest, validate_registry


def _base_payload(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "evidence_status": EVIDENCE_STATUS,
        "scientific_verdict": None,
        "provider_calls": 0,
        "provider_fallback": PROVIDER_FALLBACK,
        "result_run_available": False,
    }


def _validate() -> dict[str, Any]:
    validate_registry(REGISTRY)
    payload = _base_payload("validate")
    payload.update(
        {
            "registry_count": len(REGISTRY),
            "registry_sha256": registry_digest(REGISTRY),
            "mutation_classes": sorted(
                fixture.mutation_class.value for fixture in REGISTRY
            ),
        }
    )
    return payload


def _qualify_dev() -> dict[str, Any]:
    records = qualify_all_dev(REGISTRY)
    qualified = [
        record for record in records if record.status == "QUALIFIED_DEV_NOT_EVIDENCE"
    ]
    payload = _base_payload("qualify-dev")
    payload.update(
        {
            "registry_count": len(REGISTRY),
            "registry_sha256": registry_digest(REGISTRY),
            "qualified_count": len(qualified),
            "records": [record.to_mapping() for record in records],
        }
    )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="validate the deterministic dev registry")
    subparsers.add_parser(
        "qualify-dev", help="run synthetic fixture qualification as NOT_EVIDENCE"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        payload = _validate()
    elif args.command == "qualify-dev":
        payload = _qualify_dev()
    else:  # pragma: no cover - argparse owns this closed branch
        raise AssertionError("unreachable command")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
