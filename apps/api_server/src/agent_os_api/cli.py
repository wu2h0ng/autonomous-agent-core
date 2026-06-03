from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TextIO

from .runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig


def run_cli(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a local Trusted Loop smoke query.")
    parser.add_argument("--question", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--domain-pack",
        type=Path,
        default=Path("domain_packs/content_commerce"),
    )
    args = parser.parse_args(argv)

    runtime = ContentCommerceRuntimeFactory(
        RuntimeFactoryConfig(domain_pack_path=args.domain_pack)
    ).build()
    result = runtime.run(
        args.question,
        {
            "start_date": args.start_date,
            "end_date": args.end_date,
            "limit": args.limit,
        },
    )

    payload = {
        "intent": result.intent.metric_name,
        "provider_id": result.provider_contract.provider_id if result.provider_contract else None,
        "evidence_chain_id": result.evidence_chain.evidence_chain_id,
        "action_proposal_id": result.action_proposal.proposal_id,
        "trace_steps": [event.step for event in result.trace_events],
    }
    output = stdout
    if output is None:
        import sys

        output = sys.stdout
    output.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    output.write("\n")
    return 0


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
