from __future__ import annotations

from pathlib import Path

import pytest

from agent_os_contracts import (
    BENCHMARK_TASK_INVALID,
    BenchmarkTaskValidationError,
    SelfDevelopmentBenchmarkTask,
)
from agent_os_core import (
    BENCHMARK_CONTAINER_RUN_FAILED,
    BENCHMARK_CONTAINER_UNAVAILABLE,
    BENCHMARK_RESTORE_FAILED,
    BenchmarkContainerError,
    ContainerResult,
    build_benchmark_task,
    run_benchmark_verifier,
)

F2P_ID = "tests/queries/tests.py::QueryTests::test_filter"
P2P_ID = "tests/queries/tests.py::QueryTests::test_ordering"
TEST_PATCH = "--- a/tests/x.py\n+++ b/tests/x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
GOOD_DIFF = """\
--- a/src/module.py
+++ b/src/module.py
@@ -1,3 +1,3 @@
 context
-old
+new
 tail
"""


def _task(*, p2p: bool = True) -> SelfDevelopmentBenchmarkTask:
    return build_benchmark_task(
        {
            "task_id": "swe-bench-verified:django__django-11099",
            "repo_url": "https://github.com/django/django",
            "base_commit": "0" * 40,
            "issue_text_hash": "b" * 64,
            "gold_file_path": "django/db/models/query.py",
            "gold_file_bytes": 1234,
            "f2p_node_ids": (F2P_ID,),
            "p2p_node_ids": (P2P_ID,) if p2p else (),
            "env_manifest": {
                "interpreter": "python3.11",
                "pinned_deps": ("pytest==8.3.2",),
                "verifier_timeout_seconds": 120,
                "min_output_tokens": 4096,
            },
        }
    )


class FakeExecutor:
    """Scripted VerifierExecutor: records call order, replays exit codes."""

    def __init__(self, exits: list[int] | None = None) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._exits = list(exits) if exits is not None else [0, 0]
        self.error_at: str | None = None
        self.unexpected_error_at: str | None = None
        self.restore_error: Exception | None = None

    def apply_candidate(
        self,
        work_dir: Path,
        *,
        content: str | None,
        diff: str | None,
    ) -> None:
        self.calls.append(("apply_candidate", (content, diff)))
        self._maybe_raise("apply_candidate")

    def apply_test_patch(self, work_dir: Path, test_patch: str) -> None:
        self.calls.append(("apply_test_patch", (test_patch,)))
        self._maybe_raise("apply_test_patch")

    def run_pytest(
        self,
        work_dir: Path,
        node_ids: tuple[str, ...],
        timeout_seconds: int,
    ) -> ContainerResult:
        self.calls.append(("run_pytest", (node_ids, timeout_seconds)))
        self._maybe_raise("run_pytest")
        exit_code = self._exits.pop(0) if self._exits else 0
        return ContainerResult(
            exit_code=exit_code,
            stdout="",
            stderr=f"pytest exited {exit_code}",
            duration_seconds=0.5,
        )

    def restore(self, work_dir: Path) -> None:
        self.calls.append(("restore", ()))
        if self.restore_error is not None:
            raise self.restore_error

    def _maybe_raise(self, step: str) -> None:
        if self.error_at == step:
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_UNAVAILABLE,
                f"{step} unavailable",
            )
        if self.unexpected_error_at == step:
            raise RuntimeError(f"{step} exploded")

    def method_order(self) -> list[str]:
        return [name for name, _ in self.calls]


def test_verifier_happy_path_order_and_verdict(tmp_path: Path) -> None:
    task = _task()
    executor = FakeExecutor(exits=[0, 0])
    verdict = run_benchmark_verifier(
        task,
        tmp_path,
        test_patch=TEST_PATCH,
        candidate_content="x = 1\n",
        executor=executor,
    )
    assert executor.method_order() == [
        "apply_candidate",
        "apply_test_patch",
        "run_pytest",
        "run_pytest",
        "restore",
    ]
    assert executor.calls[0] == ("apply_candidate", ("x = 1\n", None))
    assert executor.calls[1] == ("apply_test_patch", (TEST_PATCH,))
    assert executor.calls[2] == ("run_pytest", (task.f2p_node_ids, 120))
    assert executor.calls[3] == ("run_pytest", (task.p2p_node_ids, 120))
    assert verdict.solved is True
    assert verdict.f2p_passed is True
    assert verdict.p2p_passed is True
    assert "f2p" in verdict.detail
    assert len(verdict.evidence_digest) == 64
    assert all(char in "0123456789abcdef" for char in verdict.evidence_digest)


def test_verifier_candidate_diff_path(tmp_path: Path) -> None:
    executor = FakeExecutor(exits=[0, 0])
    verdict = run_benchmark_verifier(
        _task(),
        tmp_path,
        test_patch=TEST_PATCH,
        candidate_diff=GOOD_DIFF,
        executor=executor,
    )
    assert executor.calls[0] == ("apply_candidate", (None, GOOD_DIFF))
    assert verdict.solved is True


def test_verifier_rejects_both_candidates(tmp_path: Path) -> None:
    executor = FakeExecutor()
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        run_benchmark_verifier(
            _task(),
            tmp_path,
            test_patch=TEST_PATCH,
            candidate_content="x = 1\n",
            candidate_diff=GOOD_DIFF,
            executor=executor,
        )
    assert excinfo.value.code == BENCHMARK_TASK_INVALID
    assert executor.calls == []


def test_verifier_rejects_neither_candidate(tmp_path: Path) -> None:
    executor = FakeExecutor()
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        run_benchmark_verifier(
            _task(),
            tmp_path,
            test_patch=TEST_PATCH,
            executor=executor,
        )
    assert excinfo.value.code == BENCHMARK_TASK_INVALID
    assert executor.calls == []


def test_verifier_rejects_empty_test_patch(tmp_path: Path) -> None:
    executor = FakeExecutor()
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        run_benchmark_verifier(
            _task(),
            tmp_path,
            test_patch="  ",
            candidate_content="x = 1\n",
            executor=executor,
        )
    assert excinfo.value.code == BENCHMARK_TASK_INVALID
    assert executor.calls == []


def test_verifier_f2p_failure_skips_p2p_and_still_restores(
    tmp_path: Path,
) -> None:
    executor = FakeExecutor(exits=[1])
    verdict = run_benchmark_verifier(
        _task(),
        tmp_path,
        test_patch=TEST_PATCH,
        candidate_content="x = 1\n",
        executor=executor,
    )
    assert executor.method_order() == [
        "apply_candidate",
        "apply_test_patch",
        "run_pytest",
        "restore",
    ]
    assert executor.calls[2] == ("run_pytest", (_task().f2p_node_ids, 120))
    assert verdict.solved is False
    assert verdict.f2p_passed is False
    assert verdict.p2p_passed is False


def test_verifier_p2p_failure_is_not_solved(tmp_path: Path) -> None:
    executor = FakeExecutor(exits=[0, 1])
    verdict = run_benchmark_verifier(
        _task(),
        tmp_path,
        test_patch=TEST_PATCH,
        candidate_content="x = 1\n",
        executor=executor,
    )
    assert executor.method_order() == [
        "apply_candidate",
        "apply_test_patch",
        "run_pytest",
        "run_pytest",
        "restore",
    ]
    assert verdict.f2p_passed is True
    assert verdict.p2p_passed is False
    assert verdict.solved is False


def test_verifier_without_p2p_solves_on_f2p_green(tmp_path: Path) -> None:
    executor = FakeExecutor(exits=[0])
    verdict = run_benchmark_verifier(
        _task(p2p=False),
        tmp_path,
        test_patch=TEST_PATCH,
        candidate_content="x = 1\n",
        executor=executor,
    )
    assert executor.method_order() == [
        "apply_candidate",
        "apply_test_patch",
        "run_pytest",
        "restore",
    ]
    assert verdict.solved is True
    assert verdict.f2p_passed is True
    assert verdict.p2p_passed is True


def test_verifier_executor_error_propagates_and_restore_runs(
    tmp_path: Path,
) -> None:
    executor = FakeExecutor()
    executor.error_at = "run_pytest"
    with pytest.raises(BenchmarkContainerError) as excinfo:
        run_benchmark_verifier(
            _task(),
            tmp_path,
            test_patch=TEST_PATCH,
            candidate_content="x = 1\n",
            executor=executor,
        )
    assert excinfo.value.code == BENCHMARK_CONTAINER_UNAVAILABLE
    assert executor.method_order() == [
        "apply_candidate",
        "apply_test_patch",
        "run_pytest",
        "restore",
    ]


def test_verifier_unexpected_executor_error_is_wrapped(tmp_path: Path) -> None:
    executor = FakeExecutor()
    executor.unexpected_error_at = "apply_test_patch"
    with pytest.raises(BenchmarkContainerError) as excinfo:
        run_benchmark_verifier(
            _task(),
            tmp_path,
            test_patch=TEST_PATCH,
            candidate_content="x = 1\n",
            executor=executor,
        )
    assert excinfo.value.code == BENCHMARK_CONTAINER_RUN_FAILED
    assert isinstance(excinfo.value.__cause__, RuntimeError)
    assert executor.method_order() == [
        "apply_candidate",
        "apply_test_patch",
        "restore",
    ]


def test_verifier_restore_failure_raises_restore_failed(tmp_path: Path) -> None:
    executor = FakeExecutor(exits=[0, 0])
    executor.restore_error = RuntimeError("git checkout failed")
    with pytest.raises(BenchmarkContainerError) as excinfo:
        run_benchmark_verifier(
            _task(),
            tmp_path,
            test_patch=TEST_PATCH,
            candidate_content="x = 1\n",
            executor=executor,
        )
    assert excinfo.value.code == BENCHMARK_RESTORE_FAILED
    assert executor.method_order()[-1] == "restore"


def test_verifier_restore_failure_wins_over_flow_error(tmp_path: Path) -> None:
    executor = FakeExecutor()
    executor.error_at = "run_pytest"
    executor.restore_error = RuntimeError("restore exploded")
    with pytest.raises(BenchmarkContainerError) as excinfo:
        run_benchmark_verifier(
            _task(),
            tmp_path,
            test_patch=TEST_PATCH,
            candidate_content="x = 1\n",
            executor=executor,
        )
    assert excinfo.value.code == BENCHMARK_RESTORE_FAILED
    assert executor.method_order()[-1] == "restore"


def test_verifier_evidence_digest_binds_candidate(tmp_path: Path) -> None:
    first = run_benchmark_verifier(
        _task(),
        tmp_path,
        test_patch=TEST_PATCH,
        candidate_content="x = 1\n",
        executor=FakeExecutor(exits=[0, 0]),
    )
    again = run_benchmark_verifier(
        _task(),
        tmp_path,
        test_patch=TEST_PATCH,
        candidate_content="x = 1\n",
        executor=FakeExecutor(exits=[0, 0]),
    )
    changed = run_benchmark_verifier(
        _task(),
        tmp_path,
        test_patch=TEST_PATCH,
        candidate_content="x = 2\n",
        executor=FakeExecutor(exits=[0, 0]),
    )
    assert first.evidence_digest == again.evidence_digest
    assert first.evidence_digest != changed.evidence_digest
    assert first.evidence_digest != _task().task_digest()
