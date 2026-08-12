"""Wave 2a supervision contract: the Rust daemon supervisor relies on these
Wave 1 daemon semantics. Test-first; RED before the contract is satisfied."""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Generator

import pytest

from apps.runtime_daemon import (
    RuntimeConfig,
    RuntimeAlreadyRunning,
    start_runtime,
    stop_runtime,
)
from apps.runtime_daemon.descriptor import (
    RuntimeDescriptorError,
    load_runtime_descriptor,
)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for(condition, timeout: float = 15.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return condition()


@pytest.fixture
def runtime_config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
        descriptor_path=tmp_path / "runtime.json",
        port=0,
    )


@pytest.fixture
def running(
    tmp_path: Path, runtime_config: RuntimeConfig
) -> Generator[object, None, None]:
    runtime = start_runtime(runtime_config)
    try:
        yield runtime
    finally:
        stop_runtime(runtime)


def test_supervisor_can_spawn_daemon_and_read_private_descriptor(
    tmp_path: Path,
) -> None:
    config = RuntimeConfig(
        database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
        descriptor_path=tmp_path / "runtime.json",
        port=0,
    )
    running = start_runtime(config)
    try:
        descriptor = load_runtime_descriptor(config.descriptor_path)
        assert descriptor.pid == os.getpid()
        assert stat.S_IMODE(config.descriptor_path.stat().st_mode) == 0o600
        assert descriptor.base_url.startswith("http://127.0.0.1:")
    finally:
        stop_runtime(running)


def test_supervisor_health_probe_requires_bearer_token(
    running: object,
) -> None:
    from apps.runtime_daemon import RunningRuntime

    assert isinstance(running, RunningRuntime)
    descriptor = load_runtime_descriptor(running.config.descriptor_path)

    def status(authenticated: bool) -> int:
        headers = {}
        if authenticated:
            headers["Authorization"] = f"Bearer {descriptor.bearer_token}"
        request = urllib.request.Request(
            descriptor.base_url + "/v1/health", headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code

    assert _wait_for(lambda: status(False) == 401)
    assert status(True) == 200


def test_supervisor_kills_and_restarts_daemon_same_session(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(repo_root),
            str(repo_root / "packages" / "contracts" / "src"),
            str(repo_root / "packages" / "os_core" / "src"),
        ]
    )
    descriptor_path = tmp_path / "runtime.json"
    database = tmp_path / "agent-os.sqlite3"

    def spawn() -> subprocess.Popen:
        previous_boot: str | None = None
        try:
            previous_boot = load_runtime_descriptor(descriptor_path).boot_id
        except RuntimeDescriptorError:
            pass
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "apps.runtime_daemon",
                "--database",
                str(database),
                "--workspace",
                str(tmp_path),
                "--descriptor",
                str(descriptor_path),
                "--host",
                "127.0.0.1",
                "--port",
                "0",
            ],
            start_new_session=True,
            env=env,
        )
        assert _wait_for(
            lambda: (
                descriptor_path.exists()
                and _pid_alive(process.pid)
                and (
                    previous_boot is None
                    or load_runtime_descriptor(descriptor_path).boot_id
                    != previous_boot
                )
            ),
            timeout=20,
        )
        return process

    first = spawn()
    first_boot = load_runtime_descriptor(descriptor_path).boot_id
    first.send_signal(signal.SIGKILL)
    first.wait(timeout=10)
    assert _wait_for(lambda: not _pid_alive(first.pid), timeout=10)

    second = spawn()
    second_boot = load_runtime_descriptor(descriptor_path).boot_id
    assert second_boot != first_boot
    second.send_signal(signal.SIGTERM)
    second.wait(timeout=20)
    assert _wait_for(lambda: not descriptor_path.exists(), timeout=10)


def test_supervisor_refuses_second_live_daemon(
    tmp_path: Path,
    running: object,
) -> None:
    from apps.runtime_daemon import RunningRuntime

    assert isinstance(running, RunningRuntime)
    with pytest.raises(RuntimeAlreadyRunning):
        start_runtime(running.config)


def test_descriptor_parse_failures_are_typed(
    tmp_path: Path,
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("not json", encoding="utf-8")
    with pytest.raises(RuntimeDescriptorError):
        load_runtime_descriptor(broken)

    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        json.dumps({"protocol_version": "1.0", "port": 99999}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeDescriptorError):
        load_runtime_descriptor(invalid)
