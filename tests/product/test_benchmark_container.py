from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_os_core import (
    BENCHMARK_CONTAINER_BUILD_FAILED,
    BENCHMARK_CONTAINER_RUN_FAILED,
    BENCHMARK_CONTAINER_UNAVAILABLE,
    BENCHMARK_VERIFIER_TIMEOUT,
    BenchmarkContainerError,
    ContainerRunner,
)

GOOD_TAG = "selfdev2-django-11099:20260723"
DOCKERFILE = "FROM python:3.11-slim\nRUN pip install pytest==8.3.2\n"
VERIFIER_ARGV = ["python", "-m", "pytest", "tests/a.py::test_x"]


def _completed(
    argv: list[str],
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def test_docker_available_true() -> None:
    calls: list[list[str]] = []

    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return _completed(argv)

    assert ContainerRunner(runner=fake).docker_available() is True
    assert calls == [["docker", "info"]]


def test_docker_available_false_on_nonzero() -> None:
    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return _completed(argv, returncode=1, stderr="daemon not running")

    assert ContainerRunner(runner=fake).docker_available() is False


def test_docker_available_false_when_cli_missing() -> None:
    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("docker")

    assert ContainerRunner(runner=fake).docker_available() is False


def test_docker_available_false_on_timeout() -> None:
    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=argv, timeout=30.0)

    assert ContainerRunner(runner=fake).docker_available() is False


def test_container_runner_defaults_to_subprocess_run() -> None:
    containers = ContainerRunner()
    assert callable(containers.runner)


def test_build_repo_image_argv_shape_and_stdin(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path | None, str | None, int | None]] = []

    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), cwd, input, timeout))
        return _completed(argv)

    containers = ContainerRunner(runner=fake)
    containers.build_repo_image(GOOD_TAG, DOCKERFILE, context_dir=tmp_path)
    assert calls == [
        (["docker", "build", "-t", GOOD_TAG, "-"], tmp_path, DOCKERFILE, None)
    ]


@pytest.mark.parametrize(
    "tag",
    [
        "",
        "Upper",
        "-lead",
        ".lead",
        ":lead",
        "bad tag",
        "bad;rm",
        "bad/name",
        "tag$",
        "..",
        "a" * 129,
    ],
)
def test_build_repo_image_rejects_bad_tags(tag: str, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return _completed(argv)

    containers = ContainerRunner(runner=fake)
    with pytest.raises(BenchmarkContainerError) as excinfo:
        containers.build_repo_image(tag, DOCKERFILE, context_dir=tmp_path)
    assert excinfo.value.code == BENCHMARK_CONTAINER_BUILD_FAILED
    assert calls == []


def test_build_repo_image_fails_closed_on_nonzero(tmp_path: Path) -> None:
    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return _completed(argv, returncode=1, stderr="step 3 failed")

    containers = ContainerRunner(runner=fake)
    with pytest.raises(BenchmarkContainerError) as excinfo:
        containers.build_repo_image(GOOD_TAG, DOCKERFILE, context_dir=tmp_path)
    assert excinfo.value.code == BENCHMARK_CONTAINER_BUILD_FAILED
    assert "step 3 failed" in excinfo.value.detail


def test_build_repo_image_unavailable_when_cli_missing(tmp_path: Path) -> None:
    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("docker")

    containers = ContainerRunner(runner=fake)
    with pytest.raises(BenchmarkContainerError) as excinfo:
        containers.build_repo_image(GOOD_TAG, DOCKERFILE, context_dir=tmp_path)
    assert excinfo.value.code == BENCHMARK_CONTAINER_UNAVAILABLE


def test_run_verifier_argv_has_every_security_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BENCHMARK_FOO", "present")
    monkeypatch.setenv("PROVIDER_SECRET_KEY", "must-not-leak")
    calls: list[tuple[list[str], Path | None, str | None, int | None]] = []

    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), cwd, input, timeout))
        return _completed(argv, stdout="ok")

    containers = ContainerRunner(runner=fake)
    result = containers.run_verifier(
        GOOD_TAG,
        work_dir=tmp_path,
        argv=list(VERIFIER_ARGV),
        timeout_seconds=120,
        env_allowlist=("BENCHMARK_FOO",),
    )
    expected = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,size=256m",
        "--mount",
        "type=bind,src=" + str(tmp_path.resolve()) + ",dst=/work,rw=true",
        "--workdir",
        "/work",
        "--memory",
        "2g",
        "--cpus",
        "2",
        "--pids-limit",
        "512",
        "--env",
        "BENCHMARK_FOO=present",
        GOOD_TAG,
        *VERIFIER_ARGV,
    ]
    assert calls == [(expected, None, None, 120)]
    assert not any("PROVIDER_SECRET_KEY" in token for token in expected)
    assert "--privileged" not in expected
    assert result.exit_code == 0
    assert result.stdout == "ok"
    assert result.duration_seconds >= 0.0


def test_run_verifier_without_allowlist_passes_no_env(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return _completed(argv)

    containers = ContainerRunner(runner=fake)
    containers.run_verifier(
        GOOD_TAG,
        work_dir=tmp_path,
        argv=list(VERIFIER_ARGV),
        timeout_seconds=120,
    )
    assert "--env" not in calls[0]


@pytest.mark.parametrize("name", ["lower", "1ABC", "A-B", "A" * 65])
def test_run_verifier_rejects_invalid_env_names(
    name: str,
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return _completed(argv)

    containers = ContainerRunner(runner=fake)
    with pytest.raises(BenchmarkContainerError) as excinfo:
        containers.run_verifier(
            GOOD_TAG,
            work_dir=tmp_path,
            argv=list(VERIFIER_ARGV),
            timeout_seconds=120,
            env_allowlist=(name,),
        )
    assert excinfo.value.code == BENCHMARK_CONTAINER_RUN_FAILED
    assert calls == []


def test_run_verifier_fails_closed_when_allowlisted_env_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BENCHMARK_MISSING", raising=False)
    calls: list[list[str]] = []

    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return _completed(argv)

    containers = ContainerRunner(runner=fake)
    with pytest.raises(BenchmarkContainerError) as excinfo:
        containers.run_verifier(
            GOOD_TAG,
            work_dir=tmp_path,
            argv=list(VERIFIER_ARGV),
            timeout_seconds=120,
            env_allowlist=("BENCHMARK_MISSING",),
        )
    assert excinfo.value.code == BENCHMARK_CONTAINER_RUN_FAILED
    assert calls == []


def test_run_verifier_timeout_raises_verifier_timeout(tmp_path: Path) -> None:
    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=argv, timeout=120.0)

    containers = ContainerRunner(runner=fake)
    with pytest.raises(BenchmarkContainerError) as excinfo:
        containers.run_verifier(
            GOOD_TAG,
            work_dir=tmp_path,
            argv=list(VERIFIER_ARGV),
            timeout_seconds=120,
        )
    assert excinfo.value.code == BENCHMARK_VERIFIER_TIMEOUT


def test_run_verifier_unavailable_when_cli_missing(tmp_path: Path) -> None:
    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("docker")

    containers = ContainerRunner(runner=fake)
    with pytest.raises(BenchmarkContainerError) as excinfo:
        containers.run_verifier(
            GOOD_TAG,
            work_dir=tmp_path,
            argv=list(VERIFIER_ARGV),
            timeout_seconds=120,
        )
    assert excinfo.value.code == BENCHMARK_CONTAINER_UNAVAILABLE


@pytest.mark.parametrize("exit_code", [125, 126, 127])
def test_run_verifier_docker_start_failure_is_run_failed(
    exit_code: int,
    tmp_path: Path,
) -> None:
    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return _completed(argv, returncode=exit_code, stderr="docker: Error")

    containers = ContainerRunner(runner=fake)
    with pytest.raises(BenchmarkContainerError) as excinfo:
        containers.run_verifier(
            GOOD_TAG,
            work_dir=tmp_path,
            argv=list(VERIFIER_ARGV),
            timeout_seconds=120,
        )
    assert excinfo.value.code == BENCHMARK_CONTAINER_RUN_FAILED
    assert "docker: Error" in excinfo.value.detail


@pytest.mark.parametrize("exit_code", [1, 2, 5])
def test_run_verifier_verifier_failure_is_result_not_error(
    exit_code: int,
    tmp_path: Path,
) -> None:
    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return _completed(argv, returncode=exit_code, stderr="tests failed")

    containers = ContainerRunner(runner=fake)
    result = containers.run_verifier(
        GOOD_TAG,
        work_dir=tmp_path,
        argv=list(VERIFIER_ARGV),
        timeout_seconds=120,
    )
    assert result.exit_code == exit_code
    assert result.stderr == "tests failed"


def test_run_verifier_rejects_shell_string_argv(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return _completed(argv)

    containers = ContainerRunner(runner=fake)
    with pytest.raises(BenchmarkContainerError) as excinfo:
        containers.run_verifier(
            GOOD_TAG,
            work_dir=tmp_path,
            argv="python -m pytest",  # type: ignore[arg-type]
            timeout_seconds=120,
        )
    assert excinfo.value.code == BENCHMARK_CONTAINER_RUN_FAILED
    assert calls == []


def test_run_verifier_rejects_non_positive_timeout(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return _completed(argv)

    containers = ContainerRunner(runner=fake)
    with pytest.raises(BenchmarkContainerError) as excinfo:
        containers.run_verifier(
            GOOD_TAG,
            work_dir=tmp_path,
            argv=list(VERIFIER_ARGV),
            timeout_seconds=0,
        )
    assert excinfo.value.code == BENCHMARK_CONTAINER_RUN_FAILED
    assert calls == []


def test_run_verifier_rejects_missing_work_dir(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return _completed(argv)

    containers = ContainerRunner(runner=fake)
    with pytest.raises(BenchmarkContainerError) as excinfo:
        containers.run_verifier(
            GOOD_TAG,
            work_dir=tmp_path / "missing",
            argv=list(VERIFIER_ARGV),
            timeout_seconds=120,
        )
    assert excinfo.value.code == BENCHMARK_CONTAINER_RUN_FAILED
    assert calls == []


def test_run_verifier_rejects_bad_tag(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake(
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return _completed(argv)

    containers = ContainerRunner(runner=fake)
    with pytest.raises(BenchmarkContainerError) as excinfo:
        containers.run_verifier(
            "BAD TAG",
            work_dir=tmp_path,
            argv=list(VERIFIER_ARGV),
            timeout_seconds=120,
        )
    assert excinfo.value.code == BENCHMARK_CONTAINER_RUN_FAILED
    assert calls == []
