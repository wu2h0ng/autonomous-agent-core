from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TextIO

from .outcome_service import record_outcome_service, run_service, search_service
from .runtime_factory import (
    EXECUTOR_SQLITE,
    EXECUTOR_STATIC,
    STORE_MEMORY,
    STORE_POSTGRES,
    ContentCommerceRuntimeFactory,
    RuntimeFactoryConfig,
)


def _add_domain_pack_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--domain-pack",
        type=Path,
        default=Path("domain_packs/content_commerce"),
    )
    parser.add_argument(
        "--executor",
        choices=(EXECUTOR_STATIC, EXECUTOR_SQLITE),
        default=EXECUTOR_STATIC,
        help=(
            "Query executor to use: 'static' (deterministic fixture rows, default) "
            "or 'sqlite' (real SQL over the seeded Customer-0 data plane)."
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local Trusted Loop smoke command.")
    subparsers = parser.add_subparsers(dest="command")

    query = subparsers.add_parser("query", help="Run a Trusted Loop query.")
    query.add_argument("--question", required=True)
    query.add_argument("--start-date", required=True)
    query.add_argument("--end-date", required=True)
    query.add_argument("--limit", type=int, default=100)
    _add_domain_pack_args(query)

    outcome = subparsers.add_parser(
        "record-outcome",
        help=(
            "Record an observed outcome for a prior run's trace. NOTE: in-memory "
            "stores are per-process, so a fresh CLI invocation will not find a prior "
            "run's trace (knowledge_asset_id=None, knowledge_version=0)."
        ),
    )
    outcome.add_argument("--trace-id", required=True)
    outcome.add_argument("--outcome", required=True)
    outcome.add_argument("--reviewer", default=None)
    outcome.add_argument(
        "--metric",
        action="append",
        default=[],
        metavar="name=value",
        help="Observed metric delta as name=value. Repeatable.",
    )
    _add_domain_pack_args(outcome)

    search = subparsers.add_parser(
        "search",
        help=(
            "Search the knowledge memory (hybrid retrieval). With --store-backend memory "
            "(default) the index is per-process/empty; use 'postgres' + --database-url to "
            "search the durable index the loop writes."
        ),
    )
    search.add_argument("--question", required=True)
    search.add_argument("--metric", default=None)
    search.add_argument("--owner", default=None)
    search.add_argument("--k", type=int, default=5)
    search.add_argument("--domain-pack", type=Path, default=Path("domain_packs/content_commerce"))
    search.add_argument(
        "--store-backend",
        choices=(STORE_MEMORY, STORE_POSTGRES),
        default=STORE_MEMORY,
    )
    search.add_argument("--database-url", default=None)

    return parser


def _parse_metric_deltas(items: list[str]) -> dict[str, object]:
    deltas: dict[str, object] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"Invalid --metric {item!r}; expected name=value.")
        name, _, raw = item.partition("=")
        name = name.strip()
        if not name:
            raise SystemExit(f"Invalid --metric {item!r}; name is empty.")
        deltas[name] = _coerce_value(raw.strip())
    return deltas


def _coerce_value(raw: str) -> object:
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _emit(payload: dict[str, object], stdout: TextIO | None) -> None:
    output = stdout
    if output is None:
        import sys

        output = sys.stdout
    output.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    output.write("\n")


SUBCOMMANDS = ("query", "record-outcome", "search")


def _normalize_argv(argv: list[str] | None) -> list[str] | None:
    """Default to the ``query`` subcommand for the legacy bare option form.

    Older callers invoke ``run_cli(["--question", ...])`` with no subcommand.
    When the first token is an option (or otherwise not a known subcommand),
    prepend ``query`` so the historical behavior keeps working alongside the
    new ``query`` / ``record-outcome`` subcommands.
    """
    if argv is None:
        import sys

        argv = sys.argv[1:]
    if argv and argv[0] not in SUBCOMMANDS and argv[0] not in ("-h", "--help"):
        return ["query", *argv]
    return argv


def run_cli(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(_normalize_argv(argv))

    if args.command is None:
        parser.print_help()
        return 2

    if args.command == "search":
        retriever = ContentCommerceRuntimeFactory(
            RuntimeFactoryConfig(
                domain_pack_path=args.domain_pack,
                store_backend=args.store_backend,
                database_url=args.database_url,
            )
        ).build_knowledge_retriever()
        payload = search_service(
            retriever,
            text=args.question,
            metric_name=args.metric,
            owner=args.owner,
            k=args.k,
        )
        _emit(payload, stdout)
        return 0

    factory = ContentCommerceRuntimeFactory(
        RuntimeFactoryConfig(domain_pack_path=args.domain_pack, executor=args.executor)
    )
    runtime = factory.build()

    if args.command == "query":
        payload = run_service(
            runtime,
            question=args.question,
            parameters={
                "start_date": args.start_date,
                "end_date": args.end_date,
                "limit": args.limit,
            },
        )
        # Preserve the historical query payload shape (trace_steps for smoke debugging).
        _emit(payload, stdout)
        # Expected business block (unsafe SQL, unknown metric, ...) -> non-zero exit.
        return 1 if payload.get("status") == "blocked" else 0

    if args.command == "record-outcome":
        metric_deltas = _parse_metric_deltas(args.metric)
        payload = record_outcome_service(
            runtime,
            trace_id=args.trace_id,
            outcome=args.outcome,
            reviewer=args.reviewer,
            metric_deltas=metric_deltas or None,
        )
        _emit(payload, stdout)
        return 0

    parser.print_help()
    return 2


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
