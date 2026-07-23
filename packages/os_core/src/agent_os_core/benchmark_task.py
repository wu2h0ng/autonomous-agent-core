from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from agent_os_contracts import (
    BENCHMARK_GOLD_FILE_MAX_BYTES,
    BENCHMARK_TASK_INVALID,
    BenchmarkTaskValidationError,
    SelfDevelopmentBenchmarkTask,
    is_valid_benchmark_node_id,
)


VERIFIER_ARGV_SCHEMA = "python -m pytest <node-id> [<node-id> ...]"
"""Enumerated verifier argv (ADR-0056 decision 6): the only allowed form.

Node ids are validated per argument; no flags, no shell, and the argv is
always materialized as a list so it never passes through a shell string.
"""


def build_benchmark_task(payload: Mapping[str, Any]) -> SelfDevelopmentBenchmarkTask:
    """Validate an external benchmark task payload and bind it (fail closed).

    Unknown keys are rejected by the contract; every validation failure is
    surfaced as BenchmarkTaskValidationError with code BENCHMARK_TASK_INVALID.
    """

    if not isinstance(payload, Mapping):
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            "benchmark task payload must be a mapping",
        )
    try:
        task = SelfDevelopmentBenchmarkTask.model_validate(dict(payload))
    except ValidationError as exc:
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            f"benchmark task payload failed contract validation: {exc}",
        ) from exc
    validate_f2p_p2p_disjoint(task)
    return task


def validate_f2p_p2p_disjoint(task: SelfDevelopmentBenchmarkTask) -> None:
    """Fail closed if the F2P and curated P2P node-id sets overlap."""

    overlap = sorted(set(task.f2p_node_ids).intersection(task.p2p_node_ids))
    if overlap:
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            "f2p and p2p node ids must be disjoint: " + ",".join(overlap),
        )


def build_verifier_argv(
    node_ids: tuple[str, ...],
    *,
    timeout_seconds: int,
) -> list[str]:
    """Build the enumerated verifier argv as a LIST (never a shell string).

    Only VERIFIER_ARGV_SCHEMA is produced: ``python -m pytest <node-id>...``.
    timeout_seconds is validated here (fail-closed default) and enforced by
    the runner consuming this argv; it is never embedded as a pytest flag.
    """

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or timeout_seconds < 1
    ):
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            "verifier timeout_seconds must be a positive integer",
        )
    if not node_ids:
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            "at least one pytest node id is required",
        )
    for node_id in node_ids:
        if not is_valid_benchmark_node_id(node_id):
            raise BenchmarkTaskValidationError(
                BENCHMARK_TASK_INVALID,
                f"verifier node id is not allowlisted: {node_id!r}",
            )
    return ["python", "-m", "pytest", *node_ids]


def validate_gold_file(
    path: Path,
    *,
    max_bytes: int = BENCHMARK_GOLD_FILE_MAX_BYTES,
) -> tuple[int, int]:
    """Return (byte_count, line_count) for the gold file; fail closed.

    Fails with BENCHMARK_TASK_INVALID if the file is missing or larger than
    max_bytes: the provider prompt truncates file content, so oversized gold
    files are unsolvable by construction (design packet section 3).
    """

    if not path.is_file():
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            f"gold file is missing: {path}",
        )
    data = path.read_bytes()
    if len(data) > max_bytes:
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            f"gold file exceeds {max_bytes} bytes: {len(data)}",
        )
    return len(data), len(data.splitlines())
