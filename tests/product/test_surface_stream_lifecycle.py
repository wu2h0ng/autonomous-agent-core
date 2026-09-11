"""E1 stream lifecycle invariants (M2, test-first).

Frozen source: GC §E1 — `stream_end` (transient) never finalizes a turn; a
turn completes only from the durable projection; a stream ending without a
durable commit renders the single typed `STALLED_PENDING_DURABLE_STATE`
(transient client state, never a durable Task event, never inferred
completion; threshold configurable and test-injectable, 30s default); daemon
crash kills transient state (typed STREAM_GONE/410 for stale cursors) and
recovery comes only from durable session state — no frames are back-filled or
fabricated.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    ApprovalDisposition,
    SurfaceBeginTurnCommand,
    SurfaceClientRef,
    SurfaceEventBatch,
    SurfaceStreamBinding,
    SurfaceStreamFrameKind,
    TaskEvent,
    TaskEventType,
)
from agent_os_core import (
    STALL_THRESHOLD_DEFAULT_SECONDS,
    DeferredApprovalGateway,
    DeterministicProvider,
    StreamCursor,
)

from apps.api_server.app import AgentOSApplication
from apps.cli.surface_client import (
    SurfaceClient,
    SurfaceStreamStaleError,
)
from apps.cli.turn_commit import (
    STALLED_PENDING_DURABLE_STATE,
    await_turn_commit,
)
from apps.runtime_daemon.descriptor import (
    load_runtime_descriptor,
)


# ---------------------------------------------------------------------------
# In-process: stream_end vs durable commit ordering
# ---------------------------------------------------------------------------


def proposal(call_id: str, capability_id: str, arguments: dict[str, Any]) -> Any:
    from agent_os_core.provider import ProviderToolProposal

    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


def chat_app(root: Path, scripted: tuple = ()) -> AgentOSApplication:
    app = AgentOSApplication(
        database=root / "agent-os.sqlite3",
        workspace=root,
    )
    app.provider = DeterministicProvider(
        scripted=scripted,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _client_ref() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="tui-1",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:local",
    )


def _begin_turn_command(
    app: AgentOSApplication,
    session_id: str,
    text: str,
    *,
    key: str,
    stream_id: str,
) -> SurfaceBeginTurnCommand:
    return SurfaceBeginTurnCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client_ref(),
        session_id=session_id,
        text=text,
        stream=SurfaceStreamBinding(
            runtime_boot_id=app.runtime_boot_id, stream_id=stream_id
        ),
        expected_event_sequence=app.surface_current_sequence(
            app.surface_task_for_session(session_id)
        ),
        idempotency_key=key,
        requested_at=datetime.now(timezone.utc),
    )


def _wait_until(predicate: Any, timeout: float = 5.0, interval: float = 0.01) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition was not met before the deadline")


def _turn_commit_payload(app: AgentOSApplication, task_id: str, turn_id: str) -> Any:
    for event in app.store.read(task_id):
        if event.event_type is not TaskEventType.SESSION_TURN_COMPLETED:
            continue
        payload = json.loads(event.payload_json)
        if payload.get("turn_id") == turn_id:
            return payload
    return None


def test_stream_end_never_finalizes_turn_pending_approval(tmp_path: Path) -> None:
    app = chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    proposal(
                        "call-edit",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable\n",
                            "new_string": "fixed\n",
                        },
                    ),
                ),
            ),
            ("edited reply", ()),
        ),
    )
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    session, _loop = app.open_chat_session("edit", DeferredApprovalGateway())
    stream_id = app.subscribe_stream(session.session_id)
    response = app.surface.begin_turn(
        _begin_turn_command(
            app, session.session_id, "edit fixture", key="key-1", stream_id=stream_id
        )
    )

    # The durable WAITING_APPROVAL marker: provider call is done, turn open.
    _wait_until(
        lambda: (
            app.tasks.project_session(
                session.task_id, session.session_id
            ).pending_continuation
        )
    )

    def _stream_ended() -> bool:
        frames = app.stream_registry.read(
            session.session_id, StreamCursor(app.runtime_boot_id, stream_id, 0)
        )
        return any(f.kind is SurfaceStreamFrameKind.STREAM_END for f in frames)

    # The transient provider stream has closed: stream_end is display truth.
    _wait_until(_stream_ended)
    # Frozen invariant: stream_end did NOT finalize the durable turn.
    assert _turn_commit_payload(app, session.task_id, response.turn_id) is None
    assert app.surface_has_uncommitted_turn(session.session_id) is True

    projected = app.tasks.project_session(session.task_id, session.session_id)
    pending = projected.pending_continuation
    assert pending is not None
    app.decide_session_approval(
        session.session_id,
        action_digest=pending.action.action_digest(),
        disposition=ApprovalDisposition.APPROVE,
        reason="reviewed exact edit",
    )
    commit = _wait_until(
        lambda: _turn_commit_payload(app, session.task_id, response.turn_id)
    )
    assert commit["stop_reason"] == "completed"


# ---------------------------------------------------------------------------
# Stall detection: single typed transient state, injectable threshold
# ---------------------------------------------------------------------------


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _FakeClient:
    """Duck-typed SurfaceClient: durable events are the only truth source."""

    def __init__(self, task_id: str, events: list[TaskEvent]) -> None:
        self._task_id = task_id
        self._events = events

    def get_session(self, session_id: str) -> Any:
        session = type("_Session", (), {"task_id": self._task_id})()
        return type("_Snap", (), {"session": session})()

    def events(self, task_id: str, **kwargs: Any) -> SurfaceEventBatch:
        return SurfaceEventBatch(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            task_id=task_id,
            after_sequence=0,
            next_sequence=self._events[-1].sequence,
            events=tuple(self._events),
        )


def _event(
    event_type: TaskEventType, payload: dict[str, Any], sequence: int
) -> TaskEvent:
    return TaskEvent(
        event_id=f"evt-{event_type.value}-{sequence}",
        task_id="task-1",
        event_type=event_type,
        payload_json=json.dumps(payload),
        occurred_at=datetime.now(timezone.utc),
        correlation_id=None,
        causation_id=None,
        sequence=sequence,
    )


def test_stall_renders_single_typed_state_when_commit_never_arrives() -> None:
    clock = _FakeClock()
    events = [
        _event(TaskEventType.SESSION_TURN_STARTED, {"turn_id": "t-1"}, sequence=1)
    ]
    client = _FakeClient("task-1", events)
    result = await_turn_commit(
        client,  # type: ignore[arg-type]
        "session-1",
        stall_threshold_seconds=STALL_THRESHOLD_DEFAULT_SECONDS,
        clock=clock.monotonic,
        sleeper=clock.sleep,
    )
    assert result == STALLED_PENDING_DURABLE_STATE
    assert clock.now >= STALL_THRESHOLD_DEFAULT_SECONDS


def test_stall_state_is_overruled_by_durable_commit() -> None:
    clock = _FakeClock()
    events = [
        _event(TaskEventType.SESSION_TURN_STARTED, {"turn_id": "t-1"}, sequence=1),
        _event(TaskEventType.SESSION_TURN_COMPLETED, {"turn_id": "t-1"}, sequence=2),
    ]
    client = _FakeClient("task-1", events)
    result = await_turn_commit(
        client,  # type: ignore[arg-type]
        "session-1",
        stall_threshold_seconds=STALL_THRESHOLD_DEFAULT_SECONDS,
        clock=clock.monotonic,
        sleeper=clock.sleep,
    )
    assert result == "COMMITTED"
    assert clock.now == 0.0


def test_stall_watcher_polls_until_commit_after_interval() -> None:
    clock = _FakeClock()
    started = [
        _event(TaskEventType.SESSION_TURN_STARTED, {"turn_id": "t-1"}, sequence=1)
    ]
    client = _FakeClient("task-1", started)
    calls = {"n": 0}

    def flaky_events(task_id: str, **kwargs: Any) -> SurfaceEventBatch:
        calls["n"] += 1
        events = started
        if calls["n"] >= 3:
            events = started + [
                _event(
                    TaskEventType.SESSION_TURN_COMPLETED,
                    {"turn_id": "t-1"},
                    sequence=2,
                )
            ]
        return SurfaceEventBatch(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            task_id=task_id,
            after_sequence=0,
            next_sequence=events[-1].sequence,
            events=tuple(events),
        )

    client.events = flaky_events  # type: ignore[method-assign]
    result = await_turn_commit(
        client,  # type: ignore[arg-type]
        "session-1",
        stall_threshold_seconds=STALL_THRESHOLD_DEFAULT_SECONDS,
        poll_interval_seconds=5.0,
        clock=clock.monotonic,
        sleeper=clock.sleep,
    )
    assert result == "COMMITTED"
    assert 0.0 < clock.now < STALL_THRESHOLD_DEFAULT_SECONDS


# ---------------------------------------------------------------------------
# Daemon crash recovery: transient dies, durable boundary only
# ---------------------------------------------------------------------------


class ScriptedProviderHandler(BaseHTTPRequestHandler):
    script: list[dict] = []
    requests_seen: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests_seen.append(body)
        step = min(len(type(self).requests_seen) - 1, len(type(self).script) - 1)
        entry = type(self).script[max(step, 0)]
        time.sleep(float(entry.get("delay_seconds", 0)))
        message: dict = {"role": "assistant", "content": entry.get("text", "")}
        payload = {
            "id": f"cmpl-{len(type(self).requests_seen)}",
            "choices": [
                {"message": message, "finish_reason": "stop"},
            ],
            "usage": {
                "prompt_tokens": 2,
                "completion_tokens": 2,
                "total_tokens": 4,
            },
        }
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


class ProviderStub:
    def __init__(self) -> None:
        ScriptedProviderHandler.requests_seen = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedProviderHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def set_script(self, script: list[dict]) -> None:
        ScriptedProviderHandler.requests_seen = []
        ScriptedProviderHandler.script = script

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class DaemonProcess:
    def __init__(self, process: subprocess.Popen, descriptor_path: Path) -> None:
        self.process = process
        self.descriptor_path = descriptor_path

    def stop(self, timeout: float = 20.0) -> None:
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def crash(self) -> None:
        """Unclean kill: transient state must die with the process."""
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _daemon_env(provider_url: str) -> dict[str, str]:
    env = dict(os.environ)
    env["AGENT_OS_PROVIDER_BASE_URL"] = provider_url
    env["AGENT_OS_PROVIDER_MODEL"] = "stub-model"
    env["OPENAI_API_KEY"] = "stub-key"
    root = _repo_root()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(root),
            str(root / "packages" / "contracts" / "src"),
            str(root / "packages" / "os_core" / "src"),
        ]
    )
    return env


def start_runtime_process(
    tmp_path: Path,
    workspace: Path,
    provider: ProviderStub,
    script: list[dict],
    *,
    index: int,
) -> DaemonProcess:
    provider.set_script(script)
    descriptor_path = tmp_path / f"runtime-{index}.json"
    database = tmp_path / "agent-os.sqlite3"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "apps.runtime_daemon",
            "--database",
            str(database),
            "--workspace",
            str(workspace),
            "--descriptor",
            str(descriptor_path),
            "--host",
            "127.0.0.1",
            "--port",
            "0",
        ],
        start_new_session=True,
        env=_daemon_env(provider.url),
        cwd=tmp_path,
    )
    daemon = DaemonProcess(process, descriptor_path)
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            daemon.stop()
            raise RuntimeError("runtime daemon exited before becoming healthy")
        try:
            load_runtime_descriptor(descriptor_path)
            return daemon
        except Exception:
            time.sleep(0.05)
    daemon.stop()
    raise RuntimeError("runtime daemon did not publish a descriptor in time")


def _begin_turn_via_client(
    client: SurfaceClient,
    session_id: str,
    sequence: int,
    subscription: Any,
    *,
    key: str,
) -> Any:
    return client.begin_turn(
        SurfaceBeginTurnCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=SurfaceClientRef(
                client_id="tui-1",
                client_type="CLI",
                principal_id="user:local",
                tenant_id="tenant:local",
                workspace_id="workspace:local",
                device_id="device:local",
            ),
            session_id=session_id,
            text="slow reply",
            stream=SurfaceStreamBinding(
                runtime_boot_id=subscription.runtime_boot_id,
                stream_id=subscription.stream_id,
            ),
            expected_event_sequence=sequence,
            idempotency_key=key,
            requested_at=datetime.now(timezone.utc),
        )
    )


def _task_events(client: SurfaceClient, task_id: str) -> list[TaskEvent]:
    return list(client.events(task_id, wait_ms=0).events)


def test_daemon_crash_recovers_from_durable_boundary_only(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "fixture.txt").write_text("stable\n", encoding="utf-8")
    provider = ProviderStub()
    first = start_runtime_process(
        tmp_path,
        workspace,
        provider,
        [{"text": "slow", "delay_seconds": 30.0}],
        index=1,
    )
    crashed_boot = ""
    try:
        client = SurfaceClient(load_runtime_descriptor(first.descriptor_path))
        session = client.open_session(
            statement="crash recovery session",
            idempotency_key="idem:crash:open:1",
        )
        session_id = session.session.session_id
        task_id = session.session.task_id
        sequence = session.event_sequence
        subscription = client.subscribe_stream(session_id)
        crashed_boot = subscription.runtime_boot_id
        crashed_stream = subscription.stream_id
        _begin_turn_via_client(
            client,
            session_id,
            sequence,
            subscription,
            key="idem:crash:begin:1",
        )
        _wait_until(
            lambda: any(
                event.event_type is TaskEventType.SESSION_TURN_STARTED
                for event in _task_events(client, task_id)
            ),
            timeout=10.0,
        )
        first.crash()

        second = start_runtime_process(
            tmp_path,
            workspace,
            provider,
            [{"text": "recovered reply"}],
            index=2,
        )
        try:
            recovered = SurfaceClient(load_runtime_descriptor(second.descriptor_path))
            # Session resumes at the last durable boundary.
            snapshot = recovered.get_session(session_id)
            assert snapshot.session.session_id == session_id

            # Stale generation cursor fails typed STREAM_GONE/410.
            with pytest.raises(SurfaceStreamStaleError):
                recovered.stream_frames(
                    session_id,
                    stream_id=crashed_stream,
                    runtime_boot_id=crashed_boot,
                )

            # The in-flight turn shows as not completed; durable truth only.
            all_events = _task_events(recovered, task_id)
            started_ids = {
                json.loads(event.payload_json)["turn_id"]
                for event in all_events
                if event.event_type is TaskEventType.SESSION_TURN_STARTED
            }
            completed_ids = {
                json.loads(event.payload_json)["turn_id"]
                for event in all_events
                if event.event_type is TaskEventType.SESSION_TURN_COMPLETED
            }
            assert started_ids
            assert started_ids.isdisjoint(completed_ids)

            # Fresh subscription: no frames of the dead turn are fabricated.
            fresh = recovered.subscribe_stream(session_id)
            assert fresh.runtime_boot_id != crashed_boot
            first_batch = recovered.stream_frames(
                session_id,
                stream_id=fresh.stream_id,
                runtime_boot_id=fresh.runtime_boot_id,
                wait_ms=0,
            )
            assert first_batch.frames == ()
        finally:
            second.stop()
    finally:
        if first.process.poll() is None:
            first.stop()
        provider.close()
