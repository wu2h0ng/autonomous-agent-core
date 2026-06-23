from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import TextIO

from agent_os_contracts import CausalAttributionMethod, CausalOutcomeAttribution

from .outcome_service import (
    attest_adoption_service,
    record_outcome_service,
    run_service,
    search_service,
    trace_service,
)
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
        default=None,
        help=(
            "Query executor to use: 'static' (deterministic fixture rows) "
            "or 'sqlite' (real SQL over the seeded Customer-0 data plane). "
            "Defaults to AGENT_OS_EXECUTOR or 'static'."
        ),
    )


def _add_store_backend_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store-backend",
        choices=(STORE_MEMORY, STORE_POSTGRES),
        default=None,
        help=(
            "Store backend for feedback/knowledge/traces. Defaults to "
            "AGENT_OS_STORE_BACKEND or 'memory'."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL DSN when store-backend is 'postgres'. Defaults to AGENT_OS_DATABASE_URL.",
    )


def _resolve_factory_config(args: argparse.Namespace) -> RuntimeFactoryConfig:
    """Merge CLI overrides with 12-factor env, matching the HTTP app factory."""
    env = dict(os.environ)
    if args.domain_pack is not None:
        env[RuntimeFactoryConfig.ENV_DOMAIN_PACK] = str(args.domain_pack)
    executor = getattr(args, "executor", None)
    if executor is not None:
        env[RuntimeFactoryConfig.ENV_EXECUTOR] = executor
    store_backend = getattr(args, "store_backend", None)
    if store_backend is not None:
        env[RuntimeFactoryConfig.ENV_STORE_BACKEND] = store_backend
    database_url = getattr(args, "database_url", None)
    if database_url is not None:
        env[RuntimeFactoryConfig.ENV_DATABASE_URL] = database_url
    return RuntimeFactoryConfig.from_env(env)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local Trusted Loop smoke command.")
    subparsers = parser.add_subparsers(dest="command")

    query = subparsers.add_parser("query", help="Run a Trusted Loop query.")
    query.add_argument("--question", required=True)
    query.add_argument("--start-date", required=True)
    query.add_argument("--end-date", required=True)
    query.add_argument("--limit", type=int, default=100)
    _add_domain_pack_args(query)
    _add_store_backend_args(query)

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
    _add_store_backend_args(outcome)

    adopt = subparsers.add_parser(
        "adopt",
        help=(
            "Operator-only adoption attestation for a prior trace. Unlike "
            "record-outcome, this uses the external adoption channel and may "
            "promote knowledge."
        ),
    )
    adopt.add_argument("--trace-id", required=True)
    adopt.add_argument("--outcome", required=True)
    adopt.add_argument("--reviewer", default=None)
    adopt.add_argument(
        "--metric",
        action="append",
        default=[],
        metavar="name=value",
        help="Observed metric delta as name=value. Repeatable.",
    )
    adopt.add_argument("--causal-metric", default=None)
    adopt.add_argument("--observed-value", type=float, default=None)
    adopt.add_argument("--counterfactual-value", type=float, default=None)
    adopt.add_argument(
        "--method",
        choices=tuple(method.value for method in CausalAttributionMethod),
        default=None,
    )
    adopt.add_argument("--comparison-ref", default=None)
    adopt.add_argument("--window-start", default=None)
    adopt.add_argument("--window-end", default=None)
    adopt.add_argument("--confidence", type=float, default=None)
    adopt.add_argument("--notes", default=None)
    _add_domain_pack_args(adopt)
    _add_store_backend_args(adopt)

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
    search.add_argument("--domain-pack", type=Path, default=None)
    search.add_argument(
        "--store-backend",
        choices=(STORE_MEMORY, STORE_POSTGRES),
        default=None,
    )
    search.add_argument("--database-url", default=None)

    trace = subparsers.add_parser(
        "trace",
        help=(
            "Audit a past run (answer OR refusal) by trace id. With --store-backend "
            "memory (default) traces are per-process; use 'postgres' + --database-url "
            "to audit the durable run_traces any past process wrote."
        ),
    )
    trace.add_argument("--trace-id", required=True)
    trace.add_argument("--domain-pack", type=Path, default=None)
    trace.add_argument(
        "--store-backend",
        choices=(STORE_MEMORY, STORE_POSTGRES),
        default=None,
    )
    trace.add_argument("--database-url", default=None)

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


SUBCOMMANDS = ("query", "record-outcome", "adopt", "search", "trace")


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


def _build_causal_attribution(args: argparse.Namespace) -> CausalOutcomeAttribution | None:
    causal_fields = {
        "causal_metric": args.causal_metric,
        "observed_value": args.observed_value,
        "counterfactual_value": args.counterfactual_value,
        "method": args.method,
        "comparison_ref": args.comparison_ref,
        "window_start": args.window_start,
        "window_end": args.window_end,
        "confidence": args.confidence,
    }
    if all(value is None for value in causal_fields.values()):
        return None
    missing = [name.replace("_", "-") for name, value in causal_fields.items() if value is None]
    if missing:
        raise SystemExit(f"Missing causal attribution option(s): {', '.join(missing)}.")

    observed = float(args.observed_value)
    counterfactual = float(args.counterfactual_value)
    delta_absolute = observed - counterfactual
    delta_percent = None if counterfactual == 0 else delta_absolute / counterfactual
    return CausalOutcomeAttribution(
        metric_name=args.causal_metric,
        observed_value=observed,
        counterfactual_value=counterfactual,
        delta_absolute=delta_absolute,
        delta_percent=delta_percent,
        method=CausalAttributionMethod(args.method),
        comparison_ref=args.comparison_ref,
        window_start=args.window_start,
        window_end=args.window_end,
        confidence=float(args.confidence),
        notes=args.notes,
    )


def run_cli(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(_normalize_argv(argv))

    if args.command is None:
        parser.print_help()
        return 2

    if args.command == "trace":
        store = ContentCommerceRuntimeFactory(_resolve_factory_config(args)).build_trace_store()
        payload = trace_service(store, trace_id=args.trace_id)
        if payload is None:
            _emit({"error": f"No run trace for {args.trace_id!r}."}, stdout)
            return 1
        _emit(payload, stdout)
        return 0

    if args.command == "search":
        retriever = ContentCommerceRuntimeFactory(
            _resolve_factory_config(args)
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

    factory = ContentCommerceRuntimeFactory(_resolve_factory_config(args))
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

    if args.command == "adopt":
        metric_deltas = _parse_metric_deltas(args.metric)
        payload = attest_adoption_service(
            runtime,
            factory.adoption_ingest(),
            trace_id=args.trace_id,
            outcome=args.outcome,
            reviewer=args.reviewer,
            metric_deltas=metric_deltas or None,
            causal_attribution=_build_causal_attribution(args),
        )
        _emit(payload, stdout)
        return 0

    parser.print_help()
    return 2


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
