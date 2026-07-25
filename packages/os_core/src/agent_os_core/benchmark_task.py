from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from agent_os_contracts import (
    BENCHMARK_GOLD_FILE_MAX_BYTES,
    BENCHMARK_TASK_INVALID,
    BenchmarkTaskValidationError,
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    SelfDevelopmentBenchmarkTask,
    WorkflowGraph,
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


@dataclass(frozen=True)
class BenchmarkTaskPackage:
    """Prepared Task/Run package for one admitted benchmark task."""

    benchmark_task: SelfDevelopmentBenchmarkTask
    task_commit_payload: dict[str, object]
    run_inputs: dict[str, object]


def prepare_benchmark_task_package(
    task: SelfDevelopmentBenchmarkTask,
    *,
    task_id: str,
    created_at: datetime | None = None,
    statement: str | None = None,
    duration_seconds: int = 3600,
    max_cost_usd: str = "10",
    max_provider_tokens: int = 100000,
    max_tool_calls: int = 20,
) -> BenchmarkTaskPackage:
    """Compile an admitted benchmark task into the existing Task/Run contracts.

    Same governed spine as Agent OS self-development (read -> provider ->
    approve -> apply -> tests -> evaluate -> done); the tests node executes
    the task's pinned node ids inside the per-task container via
    BenchmarkContainerSandbox, wired by the benchmark CLI (ADR-0056
    decisions 2/3). This does not create, approve or run a task; it only
    prepares the payload the existing task-commit/task-run surfaces
    consume. run_inputs carries target_path and the allowlisted
    test_command display hint — the sandbox drives the real verifier argv.
    """

    if not isinstance(task, SelfDevelopmentBenchmarkTask):
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            "task must be a SelfDevelopmentBenchmarkTask",
        )
    if not task_id or not task_id.strip():
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            "task_id is required",
        )
    if duration_seconds <= 0:
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            "duration_seconds must be positive",
        )
    if max_provider_tokens <= 0 or max_tool_calls <= 0:
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            "provider token and tool-call budgets must be positive",
        )
    digest = task.task_digest()
    now = created_at or datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=duration_seconds)
    goal_id = f"goal:benchmark:{digest[:12]}"
    package_statement = statement or (
        f"Agent OS external benchmark task for {task.gold_file_path}"
    )
    task_commit_payload: dict[str, object] = {
        "commitment": {
            "commitment_id": f"commitment:benchmark:{digest[:12]}",
            "task_id": task_id,
            "goal_id": goal_id,
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "accepted_by": "user:local",
            "accepted_at": now.isoformat(),
            "deliverables": [
                "external benchmark repository patch",
                f"benchmark task digest {digest}",
            ],
            "acceptance_criteria": [
                "admitted benchmark task contract validates",
                "exact-digest approval is recorded before patch effect",
                "containerized verifier evidence is content-bound",
                "compensation restores pre-change bytes",
            ],
            "authority_scopes": [
                "workspace:read",
                "workspace:write",
                "task.configuration.snapshot",
            ],
            "budget": {
                "max_cost_usd": max_cost_usd,
                "max_duration_seconds": duration_seconds,
                "max_provider_tokens": max_provider_tokens,
                "max_tool_calls": max_tool_calls,
            },
            "risk_tier": 1,
            "exit_conditions": ["verified", "compensated on failure"],
            "expires_at": expires_at.isoformat(),
        },
        "workflow": _benchmark_workflow(now).model_dump(mode="json"),
        "expected_outcome": {
            "expected_outcome_id": f"expected:benchmark:{digest[:12]}",
            "task_id": task_id,
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "evaluator_type": "pytest",
            "evaluator_version": "1",
            "evidence_requirements": ["test-report"],
            "failure_semantics": ["non-zero exit"],
            "threshold": 1,
            "observation_window_seconds": duration_seconds,
            "frozen_at": now.isoformat(),
        },
        "benchmark_task": task.model_dump(mode="json"),
        "statement": package_statement,
    }
    return BenchmarkTaskPackage(
        benchmark_task=task,
        task_commit_payload=task_commit_payload,
        run_inputs={
            "target_path": task.gold_file_path,
            "test_command": "python -m pytest",
        },
    )


def _benchmark_workflow(created_at: datetime) -> WorkflowGraph:
    nodes = (
        NodeSpec(
            node_id="read",
            kind=NodeKind.TOOL,
            capability="workspace.read",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(
            node_id="provider",
            kind=NodeKind.PROVIDER,
            capability="provider.chat",
        ),
        NodeSpec(node_id="approve", kind=NodeKind.APPROVAL),
        NodeSpec(
            node_id="apply",
            kind=NodeKind.TOOL,
            capability="workspace.apply_patch",
            idempotency=IdempotencyMode.COMPENSATABLE,
        ),
        NodeSpec(
            node_id="tests",
            kind=NodeKind.TOOL,
            capability="workspace.run_tests",
            idempotency=IdempotencyMode.COMPENSATABLE,
        ),
        NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION),
        NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
    )
    edges = tuple(
        EdgeSpec(source=source, target=target)
        for source, target in (
            ("read", "provider"),
            ("provider", "approve"),
            ("approve", "apply"),
            ("apply", "tests"),
            ("tests", "evaluate"),
            ("evaluate", "done"),
        )
    )
    return WorkflowGraph(
        workflow_id="workflow:benchmark-s2",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=created_at,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=nodes,
        edges=edges,
    )
