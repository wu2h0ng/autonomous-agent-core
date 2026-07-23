"""Benchmark verifier flow orchestration (ADR-0056 decision 3).

The flow is identical for the chain arm and the cheap-baseline arm:

    workspace at base commit (prepared by the caller)
    -> apply candidate (complete-file replacement or unified diff)
    -> apply the hidden test patch
    -> run the declared FAIL_TO_PASS node ids
    -> run the curated PASS_TO_PASS node ids (only when F2P is green)
    -> restore base bytes (always, even on failure)

Solve = F2P all green AND P2P all green. This function IS the verifier
flow whose independent round-level re-run is the only accepted solve
evidence; a chain-internal VERIFIED outcome is telemetry, never evidence
(ADR-0056 decision 3, design packet section 3).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, TypeVar

from agent_os_contracts import (
    BENCHMARK_TASK_INVALID,
    BenchmarkTaskValidationError,
    SelfDevelopmentBenchmarkTask,
    content_digest,
)

from .benchmark_container import (
    BENCHMARK_CONTAINER_RUN_FAILED,
    BenchmarkContainerError,
    ContainerResult,
)
from .benchmark_task import build_verifier_argv


BENCHMARK_RESTORE_FAILED = "BENCHMARK_RESTORE_FAILED"
VERIFIER_EVIDENCE_SCHEMA = "SELFDEV2-BENCHMARK-VERDICT-V1"

_T = TypeVar("_T")


class VerifierExecutor(Protocol):
    """Executes the concrete verifier steps against one task workspace.

    Production wiring applies the candidate to the bind-mounted workspace
    (complete-file write of the gold file path, or apply_unified_diff for
    diffs), applies the hidden test patch, runs pytest through
    ContainerRunner and restores base bytes; tests inject scripted fakes.
    """

    def apply_candidate(
        self,
        work_dir: Path,
        *,
        content: str | None,
        diff: str | None,
    ) -> None: ...

    def apply_test_patch(self, work_dir: Path, test_patch: str) -> None: ...

    def run_pytest(
        self,
        work_dir: Path,
        node_ids: tuple[str, ...],
        timeout_seconds: int,
    ) -> ContainerResult: ...

    def restore(self, work_dir: Path) -> None: ...


@dataclass(frozen=True)
class BenchmarkVerdict:
    """Outcome of one verifier-flow run for one task attempt.

    p2p_passed is True only when the curated P2P set ran green, or when the
    task declares no P2P ids (vacuous); a declared-but-unrun P2P set (F2P
    failed first) is False.
    """

    solved: bool
    f2p_passed: bool
    p2p_passed: bool
    detail: str
    evidence_digest: str


def run_benchmark_verifier(
    task: SelfDevelopmentBenchmarkTask,
    work_dir: Path,
    *,
    test_patch: str,
    candidate_content: str | None = None,
    candidate_diff: str | None = None,
    executor: VerifierExecutor,
) -> BenchmarkVerdict:
    """Run the ADR-0056 decision-3 verifier flow; fail closed throughout.

    Exactly one of candidate_content (complete-file replacement of the gold
    file) or candidate_diff (unified diff, applied via apply_unified_diff by
    the executor) is required, plus the hidden test patch. The per-task
    timeout comes from the task env manifest. Executor infrastructure
    errors propagate as BenchmarkContainerError and are never swallowed
    into a verdict; restore ALWAYS runs in a finally block, and a restore
    failure raises BENCHMARK_RESTORE_FAILED (even over an in-flight flow
    error) because the workspace state is then unknown.
    """

    if candidate_content is not None and candidate_diff is not None:
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            "only one of candidate_content or candidate_diff may be given",
        )
    if candidate_content is not None:
        candidate_kind = "content"
        candidate_text = candidate_content
    elif candidate_diff is not None:
        candidate_kind = "diff"
        candidate_text = candidate_diff
    else:
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            "exactly one of candidate_content or candidate_diff is required",
        )
    if not isinstance(test_patch, str) or not test_patch.strip():
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            "the hidden test patch is required",
        )

    timeout_seconds = task.env_manifest.verifier_timeout_seconds
    f2p_argv = build_verifier_argv(
        task.f2p_node_ids,
        timeout_seconds=timeout_seconds,
    )
    p2p_argv = (
        build_verifier_argv(task.p2p_node_ids, timeout_seconds=timeout_seconds)
        if task.p2p_node_ids
        else None
    )
    candidate_digest = hashlib.sha256(
        candidate_text.encode("utf-8")
    ).hexdigest()

    f2p_result: ContainerResult | None = None
    p2p_result: ContainerResult | None = None
    try:
        _executor_step(
            "apply_candidate",
            lambda: executor.apply_candidate(
                work_dir,
                content=candidate_content,
                diff=candidate_diff,
            ),
        )
        _executor_step(
            "apply_test_patch",
            lambda: executor.apply_test_patch(work_dir, test_patch),
        )
        f2p_result = _executor_step(
            "run_pytest[f2p]",
            lambda: executor.run_pytest(
                work_dir,
                task.f2p_node_ids,
                timeout_seconds,
            ),
        )
        if f2p_result.exit_code == 0 and task.p2p_node_ids:
            p2p_result = _executor_step(
                "run_pytest[p2p]",
                lambda: executor.run_pytest(
                    work_dir,
                    task.p2p_node_ids,
                    timeout_seconds,
                ),
            )
    finally:
        try:
            executor.restore(work_dir)
        except Exception as exc:
            raise BenchmarkContainerError(
                BENCHMARK_RESTORE_FAILED,
                "verifier restore failed; workspace state is unknown: "
                f"{exc!r}",
            ) from exc

    assert f2p_result is not None  # otherwise the flow raised above
    f2p_passed = f2p_result.exit_code == 0
    if p2p_result is not None:
        p2p_passed = p2p_result.exit_code == 0
    elif task.p2p_node_ids:
        p2p_passed = False  # declared but never ran: f2p failed first
    else:
        p2p_passed = True  # vacuous: the task declares no p2p set
    solved = f2p_passed and p2p_passed
    evidence_digest = content_digest(
        {
            "schema": VERIFIER_EVIDENCE_SCHEMA,
            "task_digest": task.task_digest(),
            "candidate_kind": candidate_kind,
            "candidate_digest": candidate_digest,
            "f2p_argv": f2p_argv,
            "p2p_argv": p2p_argv,
            "f2p_exit_code": f2p_result.exit_code,
            "p2p_exit_code": (
                p2p_result.exit_code if p2p_result is not None else None
            ),
            "solved": solved,
        }
    )
    return BenchmarkVerdict(
        solved=solved,
        f2p_passed=f2p_passed,
        p2p_passed=p2p_passed,
        detail=_verdict_detail(task, f2p_result, p2p_result, solved),
        evidence_digest=evidence_digest,
    )


def _executor_step(step: str, call: Callable[[], _T]) -> _T:
    """Run one executor step; typed errors pass through, others fail closed."""

    try:
        return call()
    except (BenchmarkContainerError, BenchmarkTaskValidationError):
        raise
    except Exception as exc:
        raise BenchmarkContainerError(
            BENCHMARK_CONTAINER_RUN_FAILED,
            f"verifier executor step {step!r} failed unexpectedly: {exc!r}",
        ) from exc


def _verdict_detail(
    task: SelfDevelopmentBenchmarkTask,
    f2p_result: ContainerResult,
    p2p_result: ContainerResult | None,
    solved: bool,
) -> str:
    parts = [
        f"f2p exit={f2p_result.exit_code} passed={f2p_result.exit_code == 0}"
    ]
    if p2p_result is not None:
        parts.append(
            f"p2p exit={p2p_result.exit_code} "
            f"passed={p2p_result.exit_code == 0}"
        )
    elif task.p2p_node_ids:
        parts.append("p2p not run (f2p failed)")
    else:
        parts.append("p2p not declared")
    parts.append(f"solved={solved}")
    return "; ".join(parts)
