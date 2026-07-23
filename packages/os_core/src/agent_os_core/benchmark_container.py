"""Containerized per-task benchmark runner (ADR-0056 decision 2).

Untrusted third-party historic code (SWE-bench style tasks) executes inside
a locked-down docker container: no network, no host environment, read-only
root filesystem and bounded cpu/memory/pids. Only the per-task workspace
bind mount is writable. Host credentials never enter the container; the
absence of a docker daemon is an infrastructure failure (round INVALID per
the design packet kill criteria), never a capability signal.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


BENCHMARK_CONTAINER_UNAVAILABLE = "BENCHMARK_CONTAINER_UNAVAILABLE"
BENCHMARK_CONTAINER_BUILD_FAILED = "BENCHMARK_CONTAINER_BUILD_FAILED"
BENCHMARK_CONTAINER_RUN_FAILED = "BENCHMARK_CONTAINER_RUN_FAILED"
BENCHMARK_VERIFIER_TIMEOUT = "BENCHMARK_VERIFIER_TIMEOUT"

CONTAINER_WORK_DIR = "/work"
CONTAINER_TMPFS_SPEC = "/tmp:rw,noexec,size=256m"
CONTAINER_MEMORY_LIMIT = "2g"
CONTAINER_CPU_LIMIT = "2"
CONTAINER_PIDS_LIMIT = "512"

_DOCKER_INFO_TIMEOUT_SECONDS = 30
_DOCKER_START_FAILURE_EXIT_CODES = frozenset({125, 126, 127})
"""docker run exits 125/126/127 when the container never ran the command.

pytest itself only ever exits 0-5, so these codes unambiguously separate
infrastructure failure (image missing, daemon error, command not
invocable) from verifier evidence.
"""

_IMAGE_TAG_PATTERN = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}")
_ENV_NAME_PATTERN = re.compile(r"[A-Z_][A-Z0-9_]{0,63}")


class BenchmarkContainerError(ValueError):
    """Raised when containerized benchmark execution fails (fail closed)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ContainerResult:
    """Captured outcome of one completed containerized verifier run.

    A non-zero exit_code here means the verifier itself ran and failed;
    that is evidence for the verdict, not an infrastructure error.
    """

    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


class DockerRunner(Protocol):
    """subprocess.run-compatible callable injected for docker invocations."""

    def __call__(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


def _run_docker(
    argv: list[str],
    *,
    cwd: Path | None = None,
    input: str | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        input=input,
        timeout=timeout,
        capture_output=True,
        text=True,
        check=False,
    )


@dataclass(frozen=True)
class ContainerRunner:
    """Docker-backed execution boundary for benchmark tasks (no docker SDK).

    The injected runner is subprocess.run in production and a scripted fake
    in tests. Every docker invocation is materialized as an argv LIST so no
    shell ever interprets it.
    """

    runner: DockerRunner = _run_docker

    def docker_available(self) -> bool:
        """Return True iff the docker daemon answers ``docker info``."""

        try:
            result = self.runner(
                ["docker", "info"],
                timeout=_DOCKER_INFO_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def build_repo_image(
        self,
        image_tag: str,
        dockerfile_text: str,
        *,
        context_dir: Path,
    ) -> None:
        """Build the per-repo verifier image; fail closed on any failure.

        Runs ``docker build -t <tag> -`` with dockerfile_text on stdin and
        context_dir as the working directory. The tag is validated against a
        strict allowlist pattern before docker is ever invoked.
        """

        _require_image_tag(image_tag, BENCHMARK_CONTAINER_BUILD_FAILED)
        try:
            result = self.runner(
                ["docker", "build", "-t", image_tag, "-"],
                cwd=context_dir,
                input=dockerfile_text,
            )
        except OSError as exc:
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_UNAVAILABLE,
                f"docker CLI could not be executed: {exc}",
            ) from exc
        except Exception as exc:
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_BUILD_FAILED,
                f"docker build runner failed unexpectedly: {exc!r}",
            ) from exc
        if result.returncode != 0:
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_BUILD_FAILED,
                "docker build failed: " + _stderr_detail(result),
            )

    def run_verifier(
        self,
        image_tag: str,
        *,
        work_dir: Path,
        argv: list[str],
        timeout_seconds: int,
        env_allowlist: tuple[str, ...] = (),
    ) -> ContainerResult:
        """Run the verifier argv inside the locked-down container.

        Security invariants (ADR-0056 decision 2; asserted in code below):

        - argv is a LIST of literal tokens, never a shell string; it is
          appended verbatim AFTER the image tag so docker never parses it;
        - ``--network none`` and no ``--privileged``, ever;
        - ``--read-only`` root filesystem plus a small noexec /tmp tmpfs;
        - exactly ONE bind mount: the resolved work_dir at /work, rw (the
          verifier must write patch application and pytest cache there);
        - resource limits: memory 2g, cpus 2, pids 512;
        - NO host environment enters the container except variables named
          in env_allowlist; each name must match ^[A-Z_][A-Z0-9_]{0,63}$
          and be set on the host (both fail closed).

        A non-zero verifier exit code is returned as ContainerResult
        evidence. Docker-level start failures (exit 125/126/127, which
        pytest never returns) raise BENCHMARK_CONTAINER_RUN_FAILED, and a
        subprocess timeout raises BENCHMARK_VERIFIER_TIMEOUT.
        """

        _require_image_tag(image_tag, BENCHMARK_CONTAINER_RUN_FAILED)
        verifier_argv = _require_argv_list(argv)
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or timeout_seconds < 1
        ):
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_RUN_FAILED,
                "timeout_seconds must be a positive integer",
            )
        if not work_dir.is_dir():
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_RUN_FAILED,
                f"verifier work_dir is not a directory: {work_dir}",
            )
        env_flags = _env_flags(env_allowlist)
        mount = (
            f"type=bind,src={work_dir.resolve()},"
            f"dst={CONTAINER_WORK_DIR},rw=true"
        )
        docker_argv = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            CONTAINER_TMPFS_SPEC,
            "--mount",
            mount,
            "--workdir",
            CONTAINER_WORK_DIR,
            "--memory",
            CONTAINER_MEMORY_LIMIT,
            "--cpus",
            CONTAINER_CPU_LIMIT,
            "--pids-limit",
            CONTAINER_PIDS_LIMIT,
            *env_flags,
            image_tag,
            *verifier_argv,
        ]
        tag_index = len(docker_argv) - len(verifier_argv) - 1
        flags = docker_argv[:tag_index]
        # Security invariants: asserted, not assumed.
        assert docker_argv[tag_index] == image_tag
        assert docker_argv[tag_index + 1 :] == verifier_argv
        assert "--privileged" not in flags
        assert flags[flags.index("--network") + 1] == "none"
        assert flags.count("--mount") == 1
        assert not set(_env_flag_names(flags)) - set(env_allowlist)

        started = time.monotonic()
        try:
            completed = self.runner(docker_argv, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise BenchmarkContainerError(
                BENCHMARK_VERIFIER_TIMEOUT,
                f"verifier exceeded {timeout_seconds}s: {exc}",
            ) from exc
        except OSError as exc:
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_UNAVAILABLE,
                f"docker CLI could not be executed: {exc}",
            ) from exc
        except Exception as exc:
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_RUN_FAILED,
                f"docker run runner failed unexpectedly: {exc!r}",
            ) from exc
        duration = time.monotonic() - started
        if completed.returncode in _DOCKER_START_FAILURE_EXIT_CODES:
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_RUN_FAILED,
                "docker run failed before the verifier executed: "
                + _stderr_detail(completed),
            )
        return ContainerResult(
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_seconds=duration,
        )


def _require_image_tag(image_tag: str, code: str) -> None:
    if _IMAGE_TAG_PATTERN.fullmatch(image_tag) is None:
        raise BenchmarkContainerError(
            code,
            f"image tag is not allowlisted: {image_tag!r}",
        )


def _require_argv_list(argv: list[str]) -> list[str]:
    """Fail closed unless argv is a non-empty LIST, never a shell string."""

    if (
        isinstance(argv, (str, bytes))
        or not isinstance(argv, list)
        or not argv
        or any(not isinstance(token, str) or not token for token in argv)
    ):
        raise BenchmarkContainerError(
            BENCHMARK_CONTAINER_RUN_FAILED,
            "verifier argv must be a non-empty list of tokens, "
            "never a shell string",
        )
    return list(argv)


def _env_flags(env_allowlist: tuple[str, ...]) -> list[str]:
    """Materialize --env NAME=value pairs for allowlisted host variables."""

    flags: list[str] = []
    for name in env_allowlist:
        if _ENV_NAME_PATTERN.fullmatch(name) is None:
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_RUN_FAILED,
                f"env allowlist name is not allowlisted: {name!r}",
            )
        value = os.environ.get(name)
        if value is None:
            raise BenchmarkContainerError(
                BENCHMARK_CONTAINER_RUN_FAILED,
                f"allowlisted env var is not set on the host: {name}",
            )
        flags.extend(["--env", f"{name}={value}"])
    return flags


def _env_flag_names(flags: list[str]) -> list[str]:
    return [
        flags[index + 1].split("=", 1)[0]
        for index, token in enumerate(flags)
        if token == "--env"
    ]


def _stderr_detail(result: subprocess.CompletedProcess[str]) -> str:
    detail = (result.stderr or "").strip()
    return detail if detail else f"exit code {result.returncode}"
