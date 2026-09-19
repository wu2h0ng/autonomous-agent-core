"""Safe local runtime daemon lifecycle (Wave 1).

One configured workspace per daemon process. The daemon composes one
AgentOSApplication, binds a loopback-only authenticated HTTP server, persists a
private 0600 descriptor, and removes only its own descriptor (boot-id match)
on shutdown. A second daemon refuses a live descriptor; stale descriptors
(dead PID) are replaced. A descriptor written by another surface-protocol
version is refused loudly instead of replaced: it may belong to a live daemon
for which that file is the only handle (see ``RuntimeDescriptorProtocolError``).
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from http.server import ThreadingHTTPServer
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
)

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import build_server

from .descriptor import (
    RuntimeDescriptor,
    RuntimeDescriptorError,
    RuntimeDescriptorProtocolError,
    generate_boot_id,
    generate_runtime_token,
    load_runtime_descriptor,
    write_descriptor,
)

DEFAULT_RUNTIME_DESCRIPTOR = Path.home() / ".agent-os" / "runtime.json"


class RuntimeAlreadyRunning(RuntimeError):
    """A live runtime descriptor already owns the requested identity."""


@dataclass(frozen=True)
class RuntimeConfig:
    database: Path
    workspace: Path
    descriptor_path: Path
    host: str = "127.0.0.1"
    port: int = 0
    environment: dict[str, str] = field(default_factory=dict)


@dataclass
class RunningRuntime:
    config: RuntimeConfig
    descriptor: RuntimeDescriptor
    app: AgentOSApplication
    server: ThreadingHTTPServer
    thread: threading.Thread


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_command(pid: int) -> str | None:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    command = result.stdout.strip()
    return command or None


def _require_loopback(host: str) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("runtime daemon must bind a loopback address")


def _reject_live_descriptor(descriptor_path: Path) -> None:
    """Refuse to start over a descriptor that shows this path is already taken.

    A descriptor this build cannot parse at all is not evidence that a daemon is
    alive, so it is replaced. A descriptor that names another surface protocol
    version is different: it was written by a build that may well be running, and
    replacing it would strand that daemon by removing its only handle. That case
    fails loudly and typed instead, with the remedy in the message.
    """

    if not descriptor_path.exists():
        return
    try:
        existing = load_runtime_descriptor(descriptor_path)
    except RuntimeDescriptorProtocolError:
        raise
    except RuntimeDescriptorError:
        # Unreadable is not evidence of a live daemon: this path is replaceable.
        return
    if _pid_alive(existing.pid):
        raise RuntimeAlreadyRunning(
            f"runtime {existing.boot_id} is already running "
            f"(pid {existing.pid})"
        )


def start_runtime(config: RuntimeConfig) -> RunningRuntime:
    """Start one foreground-local runtime and persist its private descriptor."""

    _require_loopback(config.host)
    _reject_live_descriptor(config.descriptor_path)
    app = AgentOSApplication(
        database=config.database,
        workspace=config.workspace,
    )
    token = generate_runtime_token()
    boot_id = generate_boot_id()
    server = build_server(app, config.host, config.port, local_token=token)
    descriptor = RuntimeDescriptor(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        pid=os.getpid(),
        boot_id=boot_id,
        host="127.0.0.1",
        port=int(server.server_address[1]),
        bearer_token=token,
        database_path=str(config.database.resolve()),
        workspace_path=str(config.workspace.resolve()),
        created_at=datetime.now(timezone.utc),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    write_descriptor(config.descriptor_path, descriptor)
    return RunningRuntime(
        config=config,
        descriptor=descriptor,
        app=app,
        server=server,
        thread=thread,
    )


def stop_runtime(running: RunningRuntime) -> None:
    """Stop one runtime and remove only its own descriptor (boot-id match)."""

    server = running.server
    try:
        server.shutdown()
    except Exception:
        pass
    running.thread.join(timeout=10)
    try:
        server.server_close()
    except Exception:
        pass
    try:
        current = load_runtime_descriptor(running.config.descriptor_path)
    except RuntimeDescriptorError:
        current = None
    if (
        current is not None
        and current.boot_id == running.descriptor.boot_id
        and current.pid == running.descriptor.pid
    ):
        try:
            running.config.descriptor_path.unlink()
        except OSError:
            pass
    try:
        running.app.store.close()
    except Exception:
        pass


def serve_foreground(config: RuntimeConfig) -> int:
    """Run the foreground daemon until SIGTERM/SIGINT."""

    _require_loopback(config.host)
    running = start_runtime(config)

    def _shutdown(signum: int, frame: object) -> None:
        try:
            running.server.shutdown()
        except Exception:
            pass

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    try:
        running.thread.join()
    finally:
        stop_runtime(running)
    return 0


def daemon_status(descriptor_path: Path) -> dict:
    """Report running/stale/absent state for one descriptor identity."""

    if not descriptor_path.exists():
        return {"status": "absent", "descriptor": str(descriptor_path)}
    try:
        descriptor = load_runtime_descriptor(descriptor_path)
    except RuntimeDescriptorError as exc:
        return {
            "status": "invalid",
            "descriptor": str(descriptor_path),
            "error": str(exc),
        }
    if _pid_alive(descriptor.pid):
        return {
            "status": "running",
            "pid": descriptor.pid,
            "boot_id": descriptor.boot_id,
            "descriptor": str(descriptor_path),
        }
    return {
        "status": "stale",
        "pid": descriptor.pid,
        "boot_id": descriptor.boot_id,
        "descriptor": str(descriptor_path),
    }


def daemon_stop(
    descriptor_path: Path,
    *,
    expected_database: Path | None = None,
    expected_workspace: Path | None = None,
) -> dict:
    """Send SIGTERM only after descriptor, PID, and executable identity checks."""

    if not descriptor_path.exists():
        raise RuntimeDescriptorError("runtime descriptor is absent")
    descriptor = load_runtime_descriptor(descriptor_path)
    if expected_database is not None and str(
        expected_database.resolve()
    ) != descriptor.database_path:
        raise RuntimeDescriptorError(
            "runtime database path does not match the descriptor"
        )
    if expected_workspace is not None and str(
        expected_workspace.resolve()
    ) != descriptor.workspace_path:
        raise RuntimeDescriptorError(
            "runtime workspace path does not match the descriptor"
        )
    if not _pid_alive(descriptor.pid):
        return {"status": "not_running", "pid": descriptor.pid}
    command = _process_command(descriptor.pid)
    if command is None or "apps.runtime_daemon" not in command:
        raise RuntimeDescriptorError(
            f"pid {descriptor.pid} is not the Agent OS runtime daemon"
        )
    try:
        os.kill(descriptor.pid, signal.SIGTERM)
    except ProcessLookupError:
        return {"status": "not_running", "pid": descriptor.pid}
    return {"status": "stopping", "pid": descriptor.pid}
