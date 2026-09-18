"""End-to-end: a runtime killed mid-turn leaves a session that recovers.

Measured defect (operator dead-end sweep F4, reproduced here through the real
daemon): a turn in flight, `SIGKILL` on the daemon, restart against the same
database. `noem session show` answers `ACTIVE`; every later turn is refused with
`a prior turn is still uncommitted for this session`; `pause`/`resume` cannot
touch the turn; the session is unusable for the rest of its life.

This drives the whole cycle through the real Surface HTTP protocol on an
ephemeral port with an explicit temp descriptor/database/workspace: kill,
restart, refusal, the operator's recovery declaration, and a new turn that
completes. The durable event list is asserted at each step.
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    SurfaceBeginTurnCommand,
    SurfaceStreamBinding,
    TaskEventType,
)

from apps.cli.surface_client import SurfaceClient, SurfaceHttpError
from apps.runtime_daemon.descriptor import load_runtime_descriptor

# Every daemon this module starts is terminated at interpreter exit: they run in
# their own session (`start_new_session=True`), so a killed pytest would leave
# them holding a port and a database.
_ACTIVE_DAEMONS: list[subprocess.Popen] = []


@atexit.register
def _terminate_active_daemons() -> None:
    BlockingProviderHandler.gate.set()
    for process in _ACTIVE_DAEMONS:
        if process.poll() is not None:
            continue
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class BlockingProviderHandler(BaseHTTPRequestHandler):
    """A provider whose first call blocks until the test releases it."""

    gate: threading.Event = threading.Event()
    entered: threading.Event = threading.Event()
    requests_seen: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests_seen.append(body)
        type(self).entered.set()
        # Bounded: a test that dies must not park a daemon thread forever.
        type(self).gate.wait(timeout=120)
        if body.get("stream"):
            self._send_sse("the answer after the restart")
            return
        payload = {
            "id": f"cmpl-{len(type(self).requests_seen)}",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "the answer after the restart",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
        }
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_sse(self, text: str) -> None:
        chunks: list[dict] = [
            {
                "id": "cmpl-stub",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}],
            }
        ]
        for index in range(0, len(text), 4):
            chunks.append(
                {"choices": [{"index": 0, "delta": {"content": text[index : index + 4]}}]}
            )
        chunks.append(
            {
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            }
        )
        lines = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
        lines += "data: [DONE]\n\n"
        encoded = lines.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


class ProviderStub:
    def __init__(self) -> None:
        BlockingProviderHandler.requests_seen = []
        BlockingProviderHandler.gate.clear()
        BlockingProviderHandler.entered.clear()
        self.server = HTTPServer(("127.0.0.1", 0), BlockingProviderHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def release(self) -> None:
        BlockingProviderHandler.gate.set()

    def close(self) -> None:
        BlockingProviderHandler.gate.set()
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

    def kill(self) -> None:
        """`SIGKILL`: the process cannot clean up - the state a crash leaves."""
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGKILL)
        self.process.wait(timeout=10)


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
    # Never the operator's default state: every path below is a temp path, and
    # the daemon binds port 0 (ephemeral).
    env["AGENT_OS_PROVIDER_CONFIG"] = str(Path(env["PYTHONPATH"].split(os.pathsep)[0]) / "unused-provider.json")
    env["AGENT_OS_DISABLE_KEYCHAIN"] = "1"
    return env


def _start_daemon(
    tmp_path: Path, workspace: Path, provider: ProviderStub, index: int
) -> DaemonProcess:
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
        cwd=str(tmp_path),
    )
    daemon = DaemonProcess(process, descriptor_path)
    _ACTIVE_DAEMONS.append(process)
    deadline = time.monotonic() + 30.0
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


def _event_payloads(client: SurfaceClient, task_id: str, event_type) -> list[dict]:
    batch = client.events(task_id, after_sequence=0, wait_ms=0)
    return [
        json.loads(event.payload_json)
        for event in batch.events
        if event.event_type is event_type
    ]


def _event_types(client: SurfaceClient, task_id: str) -> list[str]:
    batch = client.events(task_id, after_sequence=0, wait_ms=0)
    return [event.event_type.value for event in batch.events]


def _open_turn_ids(client: SurfaceClient, task_id: str) -> set[str]:
    """`SESSION_TURN_STARTED` minus `SESSION_TURN_COMPLETED`.

    Only those two events say anything about open turns: a
    `SESSION_MESSAGE_RECORDED` also carries the turn id it belongs to, and
    counting it as a completion would report every in-flight turn as committed.
    """

    batch = client.events(task_id, after_sequence=0, wait_ms=0)
    started: set[str] = set()
    completed: set[str] = set()
    for event in batch.events:
        if event.event_type not in {
            TaskEventType.SESSION_TURN_STARTED,
            TaskEventType.SESSION_TURN_COMPLETED,
        }:
            continue
        payload = json.loads(event.payload_json)
        turn_id = payload.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            continue
        if event.event_type is TaskEventType.SESSION_TURN_STARTED:
            started.add(turn_id)
        else:
            completed.add(turn_id)
    return started - completed


def test_a_runtime_killed_mid_turn_recovers_by_operator_declaration(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    provider = ProviderStub()
    daemon: DaemonProcess | None = None
    try:
        daemon = _start_daemon(tmp_path, workspace, provider, 1)
        client = SurfaceClient(load_runtime_descriptor(daemon.descriptor_path))
        opened = client.open_session("a long repair turn")
        session_id = opened.session.session_id
        task_id = opened.session.task_id

        # Subscription-first, then begin-turn: the provider call blocks, so the
        # turn is in flight when the daemon dies.
        subscription = client.subscribe_stream(session_id)
        begin = client.begin_turn(
            SurfaceBeginTurnCommand(
                protocol_version=SURFACE_PROTOCOL_VERSION,
                client=client._client_ref(),
                session_id=session_id,
                text="inspect everything",
                stream=SurfaceStreamBinding(
                    runtime_boot_id=subscription.runtime_boot_id,
                    stream_id=subscription.stream_id,
                ),
                expected_event_sequence=client.get_session(session_id).event_sequence,
                idempotency_key="e2e:dead-turn:begin",
                requested_at=opened.updated_at,
            )
        )
        assert BlockingProviderHandler.entered.wait(timeout=30)
        turn_id = begin.turn_id
        assert _open_turn_ids(client, task_id) == {turn_id}

        daemon.kill()
        daemon = None

        # Restart against the same database: a new runtime generation.
        daemon = _start_daemon(tmp_path, workspace, provider, 2)
        restarted = SurfaceClient(load_runtime_descriptor(daemon.descriptor_path))
        snapshot = restarted.get_session(session_id)
        assert snapshot.status.value == "ACTIVE"
        assert _open_turn_ids(restarted, task_id) == {turn_id}

        # Every route is refused, and the refusal names the turn and the way out.
        second_stream = restarted.subscribe_stream(session_id)
        with pytest.raises(SurfaceHttpError) as refused:
            restarted.begin_turn(
                SurfaceBeginTurnCommand(
                    protocol_version=SURFACE_PROTOCOL_VERSION,
                    client=restarted._client_ref(),
                    session_id=session_id,
                    text="carry on",
                    stream=SurfaceStreamBinding(
                        runtime_boot_id=second_stream.runtime_boot_id,
                        stream_id=second_stream.stream_id,
                    ),
                    expected_event_sequence=restarted.get_session(
                        session_id
                    ).event_sequence,
                    idempotency_key="e2e:dead-turn:refused-begin",
                    requested_at=snapshot.updated_at,
                )
            )
        assert refused.value.status_code == 409
        assert turn_id in str(refused.value)
        assert "recover-turn" in str(refused.value)

        # The operator declares the dead turn and says why.
        recovery = restarted.recover_turn(
            session_id,
            turn_id,
            "I killed the runtime mid-turn and restarted it",
        )
        assert recovery.recovery.turn_id == turn_id
        assert recovery.recovery.reason_code == "TURN_OWNER_PROCESS_GONE"
        assert recovery.recovery.declared_by == "user:local"
        assert recovery.recovery.owner_runtime_boot_id is not None
        assert recovery.recovery.owner_runtime_boot_id != recovery.recovery.recovered_by_runtime_boot_id
        assert recovery.recovery.counters_recorded is False
        assert "unknown_requires_review" in recovery.notice
        assert recovery.snapshot.status.value == "ACTIVE"

        # Durable truth: the turn is closed, never as a success, with the record.
        completions = _event_payloads(
            restarted, task_id, TaskEventType.SESSION_TURN_COMPLETED
        )
        assert len(completions) == 1
        assert completions[0]["turn_id"] == turn_id
        assert completions[0]["stop_reason"] == "unknown_requires_review"
        block = completions[0]["dead_turn_recovery"]
        assert block["started_event_id"]
        assert block["recovered_by_runtime_boot_id"] == recovery.recovery.recovered_by_runtime_boot_id
        assert _open_turn_ids(restarted, task_id) == set()

        # The session works again: a fresh turn starts and completes normally.
        provider.release()
        turn = restarted.run_turn(session_id, "carry on now")
        assert turn.stop_reason == "completed"
        assert _open_turn_ids(restarted, task_id) == set()
        assert [
            payload["turn_id"]
            for payload in _event_payloads(
                restarted, task_id, TaskEventType.SESSION_TURN_STARTED
            )
        ] == [turn_id, turn.turn_id]
        assert [
            payload["stop_reason"]
            for payload in _event_payloads(
                restarted, task_id, TaskEventType.SESSION_TURN_COMPLETED
            )
        ] == ["unknown_requires_review", "completed"]
        # The recovery wrote no receipt and dispatched nothing: an effect that was
        # in flight when the process died is never recorded as succeeded.
        assert (
            _event_payloads(restarted, task_id, TaskEventType.ACTION_RECEIPT_RECORDED)
            == []
        )
        assert "ACTION_PROPOSED" not in _event_types(restarted, task_id)
    finally:
        provider.close()
        if daemon is not None:
            daemon.stop()
