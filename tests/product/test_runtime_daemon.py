from __future__ import annotations

import os
import signal
import stat
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import pytest

from apps.runtime_daemon import (
    RuntimeAlreadyRunning,
    RuntimeConfig,
    RunningRuntime,
    start_runtime,
    stop_runtime,
)
from apps.runtime_daemon.descriptor import (
    RuntimeDescriptor,
    RuntimeDescriptorError,
    generate_boot_id,
    generate_runtime_token,
    load_runtime_descriptor,
    write_descriptor,
)


def _descriptor(tmp_path: Path, port: int = 18787) -> RuntimeDescriptor:
    return RuntimeDescriptor(
        protocol_version="1.0",
        pid=123,
        boot_id="boot:1",
        host="127.0.0.1",
        port=port,
        bearer_token="local-token",
        database_path=str(tmp_path / "agent-os.sqlite3"),
        workspace_path=str(tmp_path / "workspace"),
        created_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )


def test_descriptor_is_private_and_contains_no_provider_secret(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.json"
    write_descriptor(path, _descriptor(tmp_path))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    serialized = path.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in serialized
    assert "sk-" not in serialized


def test_write_descriptor_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "runtime.json"
    link.symlink_to(target)

    with pytest.raises(RuntimeDescriptorError, match="symlink"):
        write_descriptor(link, _descriptor(tmp_path))


def test_write_descriptor_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / ".agent-os" / "runtime.json"
    write_descriptor(path, _descriptor(tmp_path))
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert path.exists()


def test_load_descriptor_wraps_invalid_schema(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    path.write_text('{"protocol_version": "1.0", "port": 99999}', encoding="utf-8")

    with pytest.raises(RuntimeDescriptorError):
        load_runtime_descriptor(path)


def test_generated_token_and_boot_id_are_unique_and_long() -> None:
    tokens = {generate_runtime_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(token) >= 32 for token in tokens)
    boots = {generate_boot_id() for _ in range(50)}
    assert len(boots) == 50


def test_load_runtime_descriptor_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    write_descriptor(path, _descriptor(tmp_path))

    loaded = load_runtime_descriptor(path)

    assert loaded.boot_id == "boot:1"
    assert loaded.base_url == "http://127.0.0.1:18787"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for(
    condition, timeout: float = 10.0, interval: float = 0.05
) -> bool:
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
def running(tmp_path: Path, runtime_config: RuntimeConfig) -> Generator[RunningRuntime, None, None]:
    runtime = start_runtime(runtime_config)
    try:
        yield runtime
    finally:
        stop_runtime(runtime)


def test_start_runtime_writes_live_descriptor(running: RunningRuntime) -> None:
    path = running.config.descriptor_path
    assert path.exists()
    descriptor = load_runtime_descriptor(path)
    assert descriptor.pid == os.getpid()
    assert descriptor.boot_id == running.descriptor.boot_id
    assert _pid_alive(descriptor.pid)


def test_second_daemon_refuses_live_descriptor(
    tmp_path: Path,
    running: RunningRuntime,
) -> None:
    with pytest.raises(RuntimeAlreadyRunning):
        start_runtime(running.config)


def test_stale_descriptor_is_replaced(
    tmp_path: Path,
    runtime_config: RuntimeConfig,
) -> None:
    stale = _descriptor(tmp_path, port=19999).model_copy(
        update={"pid": 999999}
    )
    write_descriptor(runtime_config.descriptor_path, stale)
    assert not _pid_alive(stale.pid)

    running = start_runtime(runtime_config)
    try:
        loaded = load_runtime_descriptor(runtime_config.descriptor_path)
        assert loaded.pid == os.getpid()
        assert loaded.boot_id != stale.boot_id
    finally:
        stop_runtime(running)


def test_stop_runtime_removes_only_owned_descriptor(
    tmp_path: Path,
    running: RunningRuntime,
) -> None:
    stop_runtime(running)
    assert not running.config.descriptor_path.exists()


def test_stop_runtime_does_not_remove_replaced_descriptor(
    tmp_path: Path,
    running: RunningRuntime,
) -> None:
    replacement = _descriptor(tmp_path, port=18888)
    write_descriptor(running.config.descriptor_path, replacement)

    stop_runtime(running)

    assert running.config.descriptor_path.exists()
    loaded = load_runtime_descriptor(running.config.descriptor_path)
    assert loaded.boot_id == replacement.boot_id


def test_start_runtime_rejects_non_loopback_host(
    tmp_path: Path,
) -> None:
    config = RuntimeConfig(
        database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
        descriptor_path=tmp_path / "runtime.json",
        host="0.0.0.0",
        port=0,
    )
    with pytest.raises(ValueError, match="loopback"):
        start_runtime(config)


def test_runtime_health_route_is_authenticated(
    running: RunningRuntime,
) -> None:

    descriptor = load_runtime_descriptor(running.config.descriptor_path)
    assert _wait_for(
        lambda: _health_status(descriptor, authenticated=False) == 401
    )
    assert _health_status(descriptor, authenticated=True) == 200


def _health_status(descriptor: RuntimeDescriptor, *, authenticated: bool) -> int:
    headers = {}
    if authenticated:
        headers["Authorization"] = f"Bearer {descriptor.bearer_token}"
    request = urllib.request.Request(
        descriptor.base_url + "/v1/health",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_runtime_descriptor_excludes_provider_environment(
    running: RunningRuntime,
) -> None:
    raw = running.config.descriptor_path.read_text(encoding="utf-8")
    assert "AGENT_OS_PROVIDER_BASE_URL" not in raw
    assert "OPENAI_API_KEY" not in raw


def test_stop_verifies_database_and_workspace_identity(
    tmp_path: Path,
    running: RunningRuntime,
) -> None:
    from apps.runtime_daemon import daemon_stop

    with pytest.raises(RuntimeDescriptorError, match="database path"):
        daemon_stop(
            running.config.descriptor_path,
            expected_database=tmp_path / "other.sqlite3",
        )
    with pytest.raises(RuntimeDescriptorError, match="workspace path"):
        daemon_stop(
            running.config.descriptor_path,
            expected_workspace=tmp_path / "other-workspace",
        )


def test_stop_absent_descriptor_raises(tmp_path: Path) -> None:
    from apps.runtime_daemon import daemon_stop

    with pytest.raises(RuntimeDescriptorError, match="descriptor is absent"):
        daemon_stop(tmp_path / "missing.json")


def test_daemon_status_state_machine(tmp_path: Path) -> None:
    from apps.runtime_daemon import daemon_status

    assert daemon_status(tmp_path / "missing.json")["status"] == "absent"

    stale = _descriptor(tmp_path, port=19777).model_copy(
        update={"pid": 999999}
    )
    write_descriptor(tmp_path / "runtime.json", stale)
    assert daemon_status(tmp_path / "runtime.json")["status"] == "stale"

    invalid = tmp_path / "invalid.json"
    invalid.write_text("not json", encoding="utf-8")
    assert daemon_status(invalid)["status"] == "invalid"


def test_serve_foreground_sigterm_removes_descriptor(
    tmp_path: Path,
) -> None:
    import subprocess
    import sys

    descriptor_path = tmp_path / "runtime.json"
    repo_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(repo_root),
            str(repo_root / "packages" / "contracts" / "src"),
            str(repo_root / "packages" / "os_core" / "src"),
        ]
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; "
            "from apps.runtime_daemon import serve_foreground, RuntimeConfig; "
            "from pathlib import Path; "
            "config = RuntimeConfig("
            "database=Path(sys.argv[1]), "
            "workspace=Path(sys.argv[2]), "
            "descriptor_path=Path(sys.argv[3]), "
            "port=0); "
            "raise SystemExit(serve_foreground(config))",
            str(tmp_path / "agent-os.sqlite3"),
            str(tmp_path),
            str(descriptor_path),
        ],
        start_new_session=True,
        env=env,
    )
    try:
        assert _wait_for(lambda: descriptor_path.exists(), timeout=15)
        os.kill(process.pid, signal.SIGTERM)
        process.wait(timeout=20)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    assert process.returncode == 0
    assert _wait_for(lambda: not descriptor_path.exists(), timeout=10)
    assert not list(tmp_path.glob("runtime.json.*.tmp"))
