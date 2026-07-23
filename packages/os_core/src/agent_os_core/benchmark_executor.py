"""Production verifier executor and gold env validation (ADR-0056).

Trust split (load-bearing, ADR-0056 decision 2):

- HOST side: ContainerVerifierExecutor only moves OUR controlled bytes —
  the admitted candidate (complete-file content or unified diff) and the
  curated gold/test patches — into the task workspace, via plain python
  file writes and fail-closed argv-list git subprocesses (never a shell).
  No third-party code ever executes on the host.
- CONTAINER side: third-party historic CODE (pytest over the checked-out
  task repo at its base commit) executes only inside the locked-down
  ContainerRunner container: no network, no host environment, read-only
  root filesystem, bounded cpu/memory/pids.

run_gold_validation implements ADR-0056 decision 5 (pre-freeze gold env
validation): base+test-patch must leave the F2P set RED, and
base+gold+test-patch must leave both F2P and curated P2P sets GREEN. The
outcome is evidence for task SELECTION, not a capability signal: executor
infrastructure errors (docker unavailable, restore failure, rejected
patches) propagate as typed errors — task-level INVALID semantics — and are
never folded into a GoldValidationResult.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agent_os_contracts import (
    BENCHMARK_TASK_INVALID,
    BenchmarkTaskValidationError,
    SelfDevelopmentBenchmarkTask,
    content_digest,
)

from .benchmark_baseline import GitApplyRunner, apply_unified_diff
from .benchmark_container import (
    BENCHMARK_CONTAINER_RUN_FAILED,
    BenchmarkContainerError,
    ContainerResult,
    ContainerRunner,
)
from .benchmark_task import build_verifier_argv
from .benchmark_verifier import BENCHMARK_RESTORE_FAILED, VerifierExecutor


DEFAULT_VERIFIER_TIMEOUT_SECONDS = 120
"""Fail-closed verifier timeout floor for direct executor use.

run_benchmark_verifier and run_gold_validation always pass the per-task
manifest timeout; a non-positive timeout_seconds reaching run_pytest is
replaced by this default rather than failing open.
"""

GOLD_VALIDATION_EVIDENCE_SCHEMA = "SELFDEV2-BENCHMARK-GOLD-VALIDATION-V1"


def _run_git(
    argv: list[str],
    *,
    cwd: Path,
    input: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        input=input,
        capture_output=True,
        text=True,
        check=False,
    )


@dataclass(frozen=True)
class ContainerVerifierExecutor:
    """Production VerifierExecutor: host-side byte ops + in-container pytest.

    runner drives the locked-down container; image_tag is the per-repo
    verifier image built at freeze time. repo_root_host is the host-side
    boundary: every work_dir must resolve to it (or a descendant), and the
    gold_file_path write target must resolve inside the workspace — both
    fail closed, so host-side writes can never escape the admitted task
    checkout. git_runner is subprocess git in production (same style as
    benchmark_baseline._run_git_apply) and a scripted fake in tests.
    """

    runner: ContainerRunner
    image_tag: str
    repo_root_host: Path
    gold_file_path: str
    git_runner: GitApplyRunner = _run_git
    default_timeout_seconds: int = DEFAULT_VERIFIER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        _require_safe_gold_file_path(self.gold_file_path)
        if (
            isinstance(self.default_timeout_seconds, bool)
            or not isinstance(self.default_timeout_seconds, int)
            or self.default_timeout_seconds < 1
        ):
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_RUN_FAILED,
                "default_timeout_seconds must be a positive integer",
            )
        if not self.repo_root_host.is_dir():
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_RUN_FAILED,
                f"repo_root_host is not a directory: {self.repo_root_host}",
            )

    def apply_candidate(
        self,
        work_dir: Path,
        *,
        content: str | None,
        diff: str | None,
    ) -> None:
        """Apply the candidate: host-side gold-file write or git apply."""

        checked = self._checked_work_dir(work_dir)
        if (content is None) == (diff is None):
            raise BenchmarkTaskValidationError(
                BENCHMARK_TASK_INVALID,
                "exactly one of content or diff is required",
            )
        if content is not None:
            self._write_gold_file(checked, content)
            return
        assert diff is not None
        apply_unified_diff(checked, diff, runner=self.git_runner)

    def apply_test_patch(self, work_dir: Path, test_patch: str) -> None:
        """Apply the hidden test patch host-side, fail closed."""

        checked = self._checked_work_dir(work_dir)
        apply_unified_diff(checked, test_patch, runner=self.git_runner)

    def run_pytest(
        self,
        work_dir: Path,
        node_ids: tuple[str, ...],
        timeout_seconds: int,
    ) -> ContainerResult:
        """Run the enumerated node-id pytest argv inside the container."""

        checked = self._checked_work_dir(work_dir)
        effective_timeout = (
            timeout_seconds
            if (
                isinstance(timeout_seconds, int)
                and not isinstance(timeout_seconds, bool)
                and timeout_seconds >= 1
            )
            else self.default_timeout_seconds
        )
        argv = build_verifier_argv(
            node_ids, timeout_seconds=effective_timeout
        )
        return self.runner.run_verifier(
            self.image_tag,
            work_dir=checked,
            argv=argv,
            timeout_seconds=effective_timeout,
        )

    def restore(self, work_dir: Path) -> None:
        """Restore base bytes: git checkout, then clean (keep .venv)."""

        checked = self._checked_work_dir(work_dir)
        for argv in (
            ["git", "checkout", "--", "."],
            ["git", "clean", "-fdx", "-e", ".venv"],
        ):
            try:
                completed = self.git_runner(argv, cwd=checked, input="")
            except Exception as exc:
                raise BenchmarkContainerError(
                    BENCHMARK_RESTORE_FAILED,
                    f"git restore step {argv!r} could not execute: {exc!r}",
                ) from exc
            if completed.returncode != 0:
                raise BenchmarkContainerError(
                    BENCHMARK_RESTORE_FAILED,
                    f"git restore step {argv!r} failed: "
                    + _stderr_detail(completed),
                )

    def _checked_work_dir(self, work_dir: Path) -> Path:
        root = self.repo_root_host.resolve()
        resolved = work_dir.resolve()
        if resolved != root and root not in resolved.parents:
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_RUN_FAILED,
                f"work_dir escapes the admitted repo root: {work_dir}",
            )
        return work_dir

    def _write_gold_file(self, work_dir: Path, content: str) -> None:
        root = work_dir.resolve()
        target = (work_dir / self.gold_file_path).resolve()
        if target != root and root not in target.parents:
            raise BenchmarkTaskValidationError(
                BENCHMARK_TASK_INVALID,
                "gold_file_path escapes the workspace: "
                f"{self.gold_file_path!r}",
            )
        try:
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_RUN_FAILED,
                f"could not write gold file bytes on the host: {exc}",
            ) from exc


@dataclass(frozen=True)
class GoldValidationResult:
    """Pre-freeze gold env validation evidence for one candidate task.

    ok is True iff base+test-patch leaves F2P red AND base+gold+test-patch
    leaves F2P and the curated P2P set green (vacuously true when the task
    declares no P2P ids). Only ok tasks may enter the selection pool
    (ADR-0056 decision 5).
    """

    task_id: str
    ok: bool
    f2p_red_at_base: bool
    f2p_green_at_gold: bool
    p2p_green_at_gold: bool
    detail: str
    evidence_digest: str


def run_gold_validation(
    task: SelfDevelopmentBenchmarkTask,
    work_dir: Path,
    *,
    executor: VerifierExecutor,
    gold_patch: str,
    test_patch: str,
) -> GoldValidationResult:
    """Run the ADR-0056 decision-5 gold env validation for one task.

    Phase 1: restore to base, apply the test patch, run F2P — it must be
    RED (any non-zero exit). Phase 2: restore, apply gold + test patches,
    run F2P then P2P — both must be GREEN. Every phase restores in a
    finally block; restore failure raises BENCHMARK_RESTORE_FAILED because
    the workspace state is then unknown. Executor infrastructure errors
    propagate as BenchmarkContainerError (task-level INVALID, never a
    validation verdict); rejected patches propagate as
    BenchmarkTaskValidationError. The evidence digest binds the task
    digest, both patch sha256s and every exit code.
    """

    if not isinstance(gold_patch, str) or not gold_patch.strip():
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            "the gold patch is required",
        )
    if not isinstance(test_patch, str) or not test_patch.strip():
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            "the hidden test patch is required",
        )

    timeout_seconds = task.env_manifest.verifier_timeout_seconds
    gold_patch_sha256 = hashlib.sha256(
        gold_patch.encode("utf-8")
    ).hexdigest()
    test_patch_sha256 = hashlib.sha256(
        test_patch.encode("utf-8")
    ).hexdigest()

    executor.restore(work_dir)
    try:
        executor.apply_test_patch(work_dir, test_patch)
        base_f2p = executor.run_pytest(
            work_dir, task.f2p_node_ids, timeout_seconds
        )
    finally:
        _restore_or_raise(executor, work_dir)

    gold_f2p: ContainerResult | None = None
    gold_p2p: ContainerResult | None = None
    executor.restore(work_dir)
    try:
        executor.apply_candidate(work_dir, content=None, diff=gold_patch)
        executor.apply_test_patch(work_dir, test_patch)
        gold_f2p = executor.run_pytest(
            work_dir, task.f2p_node_ids, timeout_seconds
        )
        if gold_f2p.exit_code == 0 and task.p2p_node_ids:
            gold_p2p = executor.run_pytest(
                work_dir, task.p2p_node_ids, timeout_seconds
            )
    finally:
        _restore_or_raise(executor, work_dir)

    assert gold_f2p is not None  # otherwise the flow raised above
    f2p_red_at_base = base_f2p.exit_code != 0
    f2p_green_at_gold = gold_f2p.exit_code == 0
    if gold_p2p is not None:
        p2p_green_at_gold = gold_p2p.exit_code == 0
    else:
        # vacuous when no p2p set is declared; not run when f2p red at gold
        p2p_green_at_gold = not task.p2p_node_ids
    ok = f2p_red_at_base and f2p_green_at_gold and p2p_green_at_gold
    evidence_digest = content_digest(
        {
            "schema": GOLD_VALIDATION_EVIDENCE_SCHEMA,
            "task_digest": task.task_digest(),
            "gold_patch_sha256": gold_patch_sha256,
            "test_patch_sha256": test_patch_sha256,
            "base_f2p_exit_code": base_f2p.exit_code,
            "gold_f2p_exit_code": gold_f2p.exit_code,
            "gold_p2p_exit_code": (
                gold_p2p.exit_code if gold_p2p is not None else None
            ),
            "f2p_red_at_base": f2p_red_at_base,
            "f2p_green_at_gold": f2p_green_at_gold,
            "p2p_green_at_gold": p2p_green_at_gold,
            "ok": ok,
        }
    )
    return GoldValidationResult(
        task_id=task.task_id,
        ok=ok,
        f2p_red_at_base=f2p_red_at_base,
        f2p_green_at_gold=f2p_green_at_gold,
        p2p_green_at_gold=p2p_green_at_gold,
        detail=_validation_detail(
            task,
            base_f2p,
            gold_f2p,
            gold_p2p,
            ok,
            f2p_red_at_base=f2p_red_at_base,
            f2p_green_at_gold=f2p_green_at_gold,
            p2p_green_at_gold=p2p_green_at_gold,
        ),
        evidence_digest=evidence_digest,
    )


def _restore_or_raise(executor: VerifierExecutor, work_dir: Path) -> None:
    try:
        executor.restore(work_dir)
    except BenchmarkContainerError:
        raise
    except Exception as exc:
        raise BenchmarkContainerError(
            BENCHMARK_RESTORE_FAILED,
            "gold validation restore failed; workspace state is unknown: "
            f"{exc!r}",
        ) from exc


def _validation_detail(
    task: SelfDevelopmentBenchmarkTask,
    base_f2p: ContainerResult,
    gold_f2p: ContainerResult,
    gold_p2p: ContainerResult | None,
    ok: bool,
    *,
    f2p_red_at_base: bool,
    f2p_green_at_gold: bool,
    p2p_green_at_gold: bool,
) -> str:
    parts = [
        f"base f2p exit={base_f2p.exit_code} red={f2p_red_at_base}",
        f"gold f2p exit={gold_f2p.exit_code} green={f2p_green_at_gold}",
    ]
    if gold_p2p is not None:
        parts.append(
            f"gold p2p exit={gold_p2p.exit_code} green={p2p_green_at_gold}"
        )
    elif task.p2p_node_ids:
        parts.append("gold p2p not run (f2p red at gold)")
    else:
        parts.append("gold p2p not declared (vacuous green)")
    reasons: list[str] = []
    if not f2p_red_at_base:
        reasons.append(f"f2p not red at base (exit={base_f2p.exit_code})")
    if not f2p_green_at_gold:
        reasons.append(f"f2p not green at gold (exit={gold_f2p.exit_code})")
    if not p2p_green_at_gold and task.p2p_node_ids:
        if gold_p2p is None:
            reasons.append("p2p did not run at gold (f2p red)")
        else:
            reasons.append(
                f"p2p not green at gold (exit={gold_p2p.exit_code})"
            )
    parts.append("ok=True" if ok else "ok=False: " + ", ".join(reasons))
    return "; ".join(parts)


def _require_safe_gold_file_path(path: str) -> str:
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or any(char.isspace() for char in path)
        or any(segment in ("", ".", "..") for segment in path.split("/"))
    ):
        raise BenchmarkTaskValidationError(
            BENCHMARK_TASK_INVALID,
            f"gold_file_path is not a safe relative path: {path!r}",
        )
    return path


def _stderr_detail(result: subprocess.CompletedProcess[str]) -> str:
    detail = (result.stderr or "").strip()
    return detail if detail else f"exit code {result.returncode}"
