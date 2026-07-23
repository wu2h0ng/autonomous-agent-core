from __future__ import annotations

import subprocess
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
    ContainerRunner,
    ContainerVerifierExecutor,
    GoldValidationResult,
    build_benchmark_task,
    run_gold_validation,
)

F2P_ID = "tests/queries/tests.py::QueryTests::test_filter"
P2P_ID = "tests/queries/tests.py::QueryTests::test_ordering"
IMAGE_TAG = "agent-os-benchmark:django"
TEST_PATCH = "--- a/tests/test_x.py\n+++ b/tests/test_x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
GOLD_PATCH = """\
--- a/src/module.py
+++ b/src/module.py
@@ -1,3 +1,3 @@
 context
-old
+new
 tail
"""
GOLD_PATCH_ALT = """\
--- a/src/module.py
+++ b/src/module.py
@@ -1,3 +1,3 @@
 context
-old
+newer
 tail
"""


def _task(*, p2p: bool = True) -> SelfDevelopmentBenchmarkTask:
    return build_benchmark_task(
        {
            "task_id": "swe-bench-verified:django__django-11099",
            "repo_url": "https://github.com/django/django",
            "base_commit": "0" * 40,
            "issue_text_hash": "b" * 64,
            "gold_file_path": "src/module.py",
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


class FakeDockerRunner:
    """Scripted DockerRunner: records argv/timeout, replays exit codes."""

    def __init__(self, exits: list[int]) -> None:
        self._exits = list(exits)
        self.calls: list[tuple[list[str], int | None]] = []

    def __call__(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), timeout))
        exit_code = self._exits.pop(0) if self._exits else 0
        return subprocess.CompletedProcess(argv, exit_code, "out", "err")


class FakeGitRunner:
    """Scripted GitApplyRunner: records argv/cwd/input, replays codes."""

    def __init__(self, returncodes: list[int] | None = None) -> None:
        self._returncodes = list(returncodes) if returncodes is not None else []
        self.calls: list[tuple[list[str], Path, str]] = []

    def __call__(
        self,
        argv: list[str],
        *,
        cwd: Path,
        input: str,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), cwd, input))
        returncode = self._returncodes.pop(0) if self._returncodes else 0
        return subprocess.CompletedProcess(
            argv, returncode, "", "git error" if returncode else ""
        )

    def argv_calls(self) -> list[list[str]]:
        return [argv for argv, _, _ in self.calls]


def _executor(
    repo: Path,
    *,
    docker: FakeDockerRunner | None = None,
    git: FakeGitRunner | None = None,
) -> ContainerVerifierExecutor:
    return ContainerVerifierExecutor(
        runner=ContainerRunner(runner=docker or FakeDockerRunner([0])),
        image_tag=IMAGE_TAG,
        repo_root_host=repo,
        gold_file_path="src/module.py",
        git_runner=git or FakeGitRunner(),
    )


def _verifier_argv_tail(argv: list[str]) -> list[str]:
    return argv[argv.index(IMAGE_TAG) + 1 :]


def test_apply_candidate_content_writes_gold_file_on_host(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    target = tmp_path / "src" / "module.py"
    target.write_text("old bytes\n", encoding="utf-8")
    docker = FakeDockerRunner([0])
    git = FakeGitRunner()
    executor = _executor(tmp_path, docker=docker, git=git)
    executor.apply_candidate(tmp_path, content="new bytes\n", diff=None)
    assert target.read_text(encoding="utf-8") == "new bytes\n"
    assert docker.calls == []
    assert git.calls == []


def test_apply_candidate_requires_exactly_one_form(tmp_path: Path) -> None:
    executor = _executor(tmp_path)
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        executor.apply_candidate(tmp_path, content="x", diff=GOLD_PATCH)
    assert excinfo.value.code == BENCHMARK_TASK_INVALID
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        executor.apply_candidate(tmp_path, content=None, diff=None)
    assert excinfo.value.code == BENCHMARK_TASK_INVALID


def test_apply_candidate_diff_and_test_patch_use_git_apply(
    tmp_path: Path,
) -> None:
    git = FakeGitRunner()
    executor = _executor(tmp_path, git=git)
    executor.apply_candidate(tmp_path, content=None, diff=GOLD_PATCH)
    executor.apply_test_patch(tmp_path, TEST_PATCH)
    assert git.argv_calls() == [
        ["git", "apply", "--check"],
        ["git", "apply"],
        ["git", "apply", "--check"],
        ["git", "apply"],
    ]
    assert all(cwd == tmp_path for _, cwd, _ in git.calls)


def test_run_pytest_goes_through_container_runner_with_built_argv(
    tmp_path: Path,
) -> None:
    docker = FakeDockerRunner([0])
    executor = _executor(tmp_path, docker=docker)
    result = executor.run_pytest(tmp_path, (F2P_ID, P2P_ID), 120)
    assert result.exit_code == 0
    assert len(docker.calls) == 1
    argv, timeout = docker.calls[0]
    assert timeout == 120
    assert _verifier_argv_tail(argv) == [
        "python",
        "-m",
        "pytest",
        F2P_ID,
        P2P_ID,
    ]
    assert argv[argv.index("--network") + 1] == "none"


def test_restore_calls_git_checkout_then_clean_in_order(
    tmp_path: Path,
) -> None:
    git = FakeGitRunner()
    executor = _executor(tmp_path, git=git)
    executor.restore(tmp_path)
    assert git.argv_calls() == [
        ["git", "checkout", "--", "."],
        ["git", "clean", "-fdx", "-e", ".venv"],
    ]
    assert all(cwd == tmp_path for _, cwd, _ in git.calls)


def test_restore_git_failure_raises_restore_failed(tmp_path: Path) -> None:
    git = FakeGitRunner(returncodes=[1])
    executor = _executor(tmp_path, git=git)
    with pytest.raises(BenchmarkContainerError) as excinfo:
        executor.restore(tmp_path)
    assert excinfo.value.code == BENCHMARK_RESTORE_FAILED
    assert git.argv_calls() == [["git", "checkout", "--", "."]]


def test_work_dir_outside_repo_root_fails_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    executor = _executor(repo)
    with pytest.raises(BenchmarkContainerError) as excinfo:
        executor.run_pytest(outside, (F2P_ID,), 120)
    assert excinfo.value.code == BENCHMARK_CONTAINER_RUN_FAILED


class FakeVerifierExecutor:
    """Scripted VerifierExecutor for the gold-validation flow."""

    def __init__(self, exits: list[int]) -> None:
        self._exits = list(exits)
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.error_at: str | None = None

    def apply_candidate(
        self,
        work_dir: Path,
        *,
        content: str | None,
        diff: str | None,
    ) -> None:
        self.calls.append(("apply_candidate", (content, diff)))

    def apply_test_patch(self, work_dir: Path, test_patch: str) -> None:
        self.calls.append(("apply_test_patch", (test_patch,)))

    def run_pytest(
        self,
        work_dir: Path,
        node_ids: tuple[str, ...],
        timeout_seconds: int,
    ) -> ContainerResult:
        self.calls.append(("run_pytest", (node_ids, timeout_seconds)))
        if self.error_at == "run_pytest":
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_UNAVAILABLE, "docker daemon down"
            )
        exit_code = self._exits.pop(0) if self._exits else 0
        return ContainerResult(
            exit_code=exit_code,
            stdout="",
            stderr="",
            duration_seconds=0.1,
        )

    def restore(self, work_dir: Path) -> None:
        self.calls.append(("restore", ()))

    def method_order(self) -> list[str]:
        return [name for name, _ in self.calls]


def test_gold_validation_all_green(tmp_path: Path) -> None:
    executor = FakeVerifierExecutor([1, 0, 0])
    result = run_gold_validation(
        _task(),
        tmp_path,
        executor=executor,
        gold_patch=GOLD_PATCH,
        test_patch=TEST_PATCH,
    )
    assert isinstance(result, GoldValidationResult)
    assert result.task_id == _task().task_id
    assert result.ok is True
    assert result.f2p_red_at_base is True
    assert result.f2p_green_at_gold is True
    assert result.p2p_green_at_gold is True
    assert len(result.evidence_digest) == 64
    assert executor.method_order() == [
        "restore",
        "apply_test_patch",
        "run_pytest",
        "restore",
        "restore",
        "apply_candidate",
        "apply_test_patch",
        "run_pytest",
        "run_pytest",
        "restore",
    ]
    assert executor.calls[5] == ("apply_candidate", (None, GOLD_PATCH))
    assert executor.calls[6] == ("apply_test_patch", (TEST_PATCH,))


def test_gold_validation_not_red_at_base_is_not_ok(tmp_path: Path) -> None:
    executor = FakeVerifierExecutor([0, 0, 0])
    result = run_gold_validation(
        _task(),
        tmp_path,
        executor=executor,
        gold_patch=GOLD_PATCH,
        test_patch=TEST_PATCH,
    )
    assert result.ok is False
    assert result.f2p_red_at_base is False
    assert result.f2p_green_at_gold is True
    assert "base" in result.detail


def test_gold_validation_p2p_failure_is_not_ok(tmp_path: Path) -> None:
    executor = FakeVerifierExecutor([1, 0, 1])
    result = run_gold_validation(
        _task(),
        tmp_path,
        executor=executor,
        gold_patch=GOLD_PATCH,
        test_patch=TEST_PATCH,
    )
    assert result.ok is False
    assert result.f2p_red_at_base is True
    assert result.f2p_green_at_gold is True
    assert result.p2p_green_at_gold is False
    assert "p2p" in result.detail


def test_gold_validation_f2p_red_at_gold_skips_p2p(tmp_path: Path) -> None:
    executor = FakeVerifierExecutor([1, 1])
    result = run_gold_validation(
        _task(),
        tmp_path,
        executor=executor,
        gold_patch=GOLD_PATCH,
        test_patch=TEST_PATCH,
    )
    assert result.ok is False
    assert result.f2p_green_at_gold is False
    assert result.p2p_green_at_gold is False
    assert executor.method_order().count("run_pytest") == 2


def test_gold_validation_without_p2p_is_vacuously_green(
    tmp_path: Path,
) -> None:
    executor = FakeVerifierExecutor([1, 0])
    result = run_gold_validation(
        _task(p2p=False),
        tmp_path,
        executor=executor,
        gold_patch=GOLD_PATCH,
        test_patch=TEST_PATCH,
    )
    assert result.ok is True
    assert result.p2p_green_at_gold is True


def test_gold_validation_digest_binds_patch_bytes(tmp_path: Path) -> None:
    first = run_gold_validation(
        _task(),
        tmp_path,
        executor=FakeVerifierExecutor([1, 0, 0]),
        gold_patch=GOLD_PATCH,
        test_patch=TEST_PATCH,
    )
    again = run_gold_validation(
        _task(),
        tmp_path,
        executor=FakeVerifierExecutor([1, 0, 0]),
        gold_patch=GOLD_PATCH,
        test_patch=TEST_PATCH,
    )
    changed = run_gold_validation(
        _task(),
        tmp_path,
        executor=FakeVerifierExecutor([1, 0, 0]),
        gold_patch=GOLD_PATCH_ALT,
        test_patch=TEST_PATCH,
    )
    assert first.evidence_digest == again.evidence_digest
    assert first.evidence_digest != changed.evidence_digest


def test_gold_validation_infra_error_propagates_and_restores(
    tmp_path: Path,
) -> None:
    executor = FakeVerifierExecutor([])
    executor.error_at = "run_pytest"
    with pytest.raises(BenchmarkContainerError) as excinfo:
        run_gold_validation(
            _task(),
            tmp_path,
            executor=executor,
            gold_patch=GOLD_PATCH,
            test_patch=TEST_PATCH,
        )
    assert excinfo.value.code == BENCHMARK_CONTAINER_UNAVAILABLE
    assert executor.method_order() == [
        "restore",
        "apply_test_patch",
        "run_pytest",
        "restore",
    ]


def test_gold_validation_requires_patch_texts(tmp_path: Path) -> None:
    executor = FakeVerifierExecutor([])
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        run_gold_validation(
            _task(),
            tmp_path,
            executor=executor,
            gold_patch=" ",
            test_patch=TEST_PATCH,
        )
    assert excinfo.value.code == BENCHMARK_TASK_INVALID
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        run_gold_validation(
            _task(),
            tmp_path,
            executor=executor,
            gold_patch=GOLD_PATCH,
            test_patch="",
        )
    assert excinfo.value.code == BENCHMARK_TASK_INVALID
    assert executor.calls == []


def test_gold_validation_through_container_executor(tmp_path: Path) -> None:
    docker = FakeDockerRunner([1, 0, 0])
    git = FakeGitRunner()
    executor = _executor(tmp_path, docker=docker, git=git)
    result = run_gold_validation(
        _task(),
        tmp_path,
        executor=executor,
        gold_patch=GOLD_PATCH,
        test_patch=TEST_PATCH,
    )
    assert result.ok is True
    assert len(docker.calls) == 3
    argv, timeout = docker.calls[0]
    assert timeout == 120
    assert _verifier_argv_tail(argv) == ["python", "-m", "pytest", F2P_ID]
    git_argv = git.argv_calls()
    assert git_argv.count(["git", "checkout", "--", "."]) == 4
    assert git_argv.count(["git", "clean", "-fdx", "-e", ".venv"]) == 4
    # 3 patch applications (test, gold, test), each check-then-apply
    assert git_argv.count(["git", "apply", "--check"]) == 3
    assert git_argv.count(["git", "apply"]) == 3
