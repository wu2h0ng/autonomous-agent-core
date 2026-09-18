"""Form B child agents end-to-end against a real daemon process.

Real daemon (``python -m apps.runtime_daemon``), explicit temp
``--descriptor``/``--database``/``--workspace``, stub provider bound to an
ephemeral port (port 0). Nothing here touches ``~/.agent-os/``.

The three scenarios are the ones the adversarial review demanded evidence for:

* a parent turn really spawns a child session and the operator can read the
  attribution (including the child's own session in the session listing);
* with the feature switched off the same attempt is refused durably and creates
  nothing;
* an operator's C7 correction on the parent stops the child's pending dispatch;
* a runtime killed mid-child leaves a child with no owner, and the operator's
  reconciliation closes it as an unknown outcome - never as ``completed``.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import ApprovalDisposition, SurfaceSessionStatus
from apps.cli.surface_client import SurfaceClient
from apps.runtime_daemon.descriptor import load_runtime_descriptor


# ---------------------------------------------------------------------------
# Stub provider (ephemeral port, scripted, optional per-step stall)
# ---------------------------------------------------------------------------


class ScriptedStubHandler(BaseHTTPRequestHandler):
    script: list[dict[str, Any]] = []
    requests_seen: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests_seen.append(body)
        index = min(len(type(self).requests_seen) - 1, len(type(self).script) - 1)
        entry = type(self).script[max(index, 0)]
        delay = float(entry.get("delay_seconds", 0.0))
        if delay > 0:
            time.sleep(delay)
        if body.get("stream"):
            self._send_sse(entry)
            return
        self._send_json(entry)

    def _send_json(self, entry: dict[str, Any]) -> None:
        message: dict[str, Any] = {"role": "assistant", "content": entry.get("text", "")}
        tool_calls = entry.get("tool_calls")
        if tool_calls:
            message["tool_calls"] = [
                {
                    "id": tool["id"],
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "arguments": json.dumps(tool["arguments"]),
                    },
                }
                for tool in tool_calls
            ]
        payload = {
            "id": "cmpl-stub",
            "choices": [
                {
                    "message": message,
                    "finish_reason": "tool_calls" if tool_calls else "stop",
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

    def _send_sse(self, entry: dict[str, Any]) -> None:
        text = entry.get("text", "")
        tool_calls = entry.get("tool_calls")
        chunks: list[dict[str, Any]] = [
            {"id": "cmpl-stub", "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}]}
        ]
        for index in range(0, len(text), 4):
            chunks.append(
                {"choices": [{"index": 0, "delta": {"content": text[index : index + 4]}}]}
            )
        for position, tool in enumerate(tool_calls or []):
            chunks.append(
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": position,
                                        "id": tool["id"],
                                        "type": "function",
                                        "function": {"name": tool["name"], "arguments": ""},
                                    }
                                ]
                            },
                        }
                    ]
                }
            )
            arguments = json.dumps(tool["arguments"])
            for index in range(0, len(arguments), 8):
                chunks.append(
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": position,
                                            "function": {
                                                "arguments": arguments[index : index + 8]
                                            },
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                )
        chunks.append(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "tool_calls" if tool_calls else "stop",
                    }
                ],
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

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


class ProviderStub:
    def __init__(self) -> None:
        ScriptedStubHandler.requests_seen = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedStubHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def set_script(self, script: list[dict[str, Any]]) -> None:
        ScriptedStubHandler.requests_seen = []
        ScriptedStubHandler.script = script

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class Daemon:
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
        self.process.send_signal(signal.SIGKILL)
        self.process.wait(timeout=10)


_ACTIVE: list[subprocess.Popen] = []


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _daemon_env(provider_url: str, *, child_agents: str | None) -> dict[str, str]:
    env = dict(os.environ)
    env["AGENT_OS_PROVIDER_BASE_URL"] = provider_url
    env["AGENT_OS_PROVIDER_MODEL"] = "stub-model"
    env["OPENAI_API_KEY"] = "stub-key"
    env.pop("AGENT_OS_CHILD_AGENTS", None)
    env.pop("AGENT_OS_MAX_CHILD_AGENTS", None)
    if child_agents is not None:
        env["AGENT_OS_CHILD_AGENTS"] = child_agents
    root = _repo_root()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(root),
            str(root / "packages" / "contracts" / "src"),
            str(root / "packages" / "os_core" / "src"),
        ]
    )
    return env


def start_daemon(
    tmp_path: Path,
    workspace: Path,
    provider: ProviderStub,
    script: list[dict[str, Any]],
    *,
    index: int = 1,
    child_agents: str | None = "on",
) -> Daemon:
    provider.set_script(script)
    descriptor_path = tmp_path / f"runtime-{index}.json"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "apps.runtime_daemon",
            "--database",
            str(tmp_path / "agent-os.sqlite3"),
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
        env=_daemon_env(provider.url, child_agents=child_agents),
        cwd=tmp_path,
    )
    daemon = Daemon(process, descriptor_path)
    _ACTIVE.append(process)
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


def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")
    return root


def get_json(daemon: Daemon, path: str) -> dict[str, Any]:
    descriptor = load_runtime_descriptor(daemon.descriptor_path)
    request = urllib.request.Request(
        f"{descriptor.base_url}{path}",
        headers={
            "Authorization": f"Bearer {descriptor.bearer_token}",
            "X-Agent-OS-Protocol": "1.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise AssertionError(f"{path} -> {exc.code}: {exc.read().decode()}") from exc


def post_json(daemon: Daemon, path: str, body: dict[str, Any]) -> dict[str, Any]:
    descriptor = load_runtime_descriptor(daemon.descriptor_path)
    request = urllib.request.Request(
        f"{descriptor.base_url}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {descriptor.bearer_token}",
            "Content-Type": "application/json",
            "X-Agent-OS-Protocol": "1.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise AssertionError(f"{path} -> {exc.code}: {exc.read().decode()}") from exc


def durable_events(database: Path, task_id: str) -> list[tuple[str, dict[str, Any]]]:
    connection = sqlite3.connect(str(database))
    try:
        rows = connection.execute(
            "SELECT event_type, payload_json FROM task_events WHERE task_id = ? "
            "ORDER BY sequence",
            (task_id,),
        ).fetchall()
    finally:
        connection.close()
    return [(row[0], json.loads(row[1])) for row in rows]


def wait_for(condition: Any, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


def spawn_call(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"id": "call-spawn", "name": "agent__spawn", "arguments": arguments}


def begin_turn(client: SurfaceClient, session_id: str, text: str, key: str) -> None:
    from agent_os_contracts import SurfaceStreamBinding

    subscription = client.subscribe_stream(session_id)
    client.submit_turn(
        session_id,
        text,
        SurfaceStreamBinding(
            runtime_boot_id=subscription.runtime_boot_id,
            stream_id=subscription.stream_id,
        ),
    )


def set_accept_in_workspace(daemon: Daemon, client: SurfaceClient, session_id: str) -> None:
    """Operator mode change so tier-2 spawns are auto-allowed with provenance."""

    client.set_permission_mode(session_id, "ACCEPT_IN_WORKSPACE")
    assert (
        client.get_session(session_id).permission_mode.value
        if hasattr(client.get_session(session_id).permission_mode, "value")
        else str(client.get_session(session_id).permission_mode)
    ) == "ACCEPT_IN_WORKSPACE"


def child_spawn_records(database: Path, parent_task_id: str) -> list[dict[str, Any]]:
    return [
        payload
        for event_type, payload in durable_events(database, parent_task_id)
        if event_type == "CHILD_AGENT_SPAWNED"
    ]


# ---------------------------------------------------------------------------
# Scenario 1: a real spawn, read back through the operator surface
# ---------------------------------------------------------------------------


def test_daemon_spawns_a_child_session_and_exposes_the_attribution(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    provider = ProviderStub()
    daemon: Daemon | None = None
    try:
        daemon = start_daemon(
            tmp_path,
            root,
            provider,
            [
                {
                    "text": "",
                    "tool_calls": [
                        spawn_call(
                            {
                                "prompt": "read the fixture and report",
                                "description": "read-only recon",
                                "agent_type": "explore",
                            }
                        )
                    ],
                },
                {
                    "text": "",
                    "tool_calls": [
                        {
                            "id": "call-read",
                            "name": "workspace__read",
                            "arguments": {"path": "fixture.txt"},
                        }
                    ],
                },
                {"text": "CHILD-READ-finished"},
                {"text": "parent finished"},
            ],
            index=1,
        )
        client = SurfaceClient(load_runtime_descriptor(daemon.descriptor_path))
        opened = client.open_session("parent statement")
        set_accept_in_workspace(daemon, client, opened.session.session_id)
        turn = client.run_turn(opened.session.session_id, "spawn an explore child")

        assert turn.stop_reason == "completed", turn.text
        spawns = child_spawn_records(
            tmp_path / "agent-os.sqlite3", opened.session.task_id
        )
        assert len(spawns) == 1
        child_session_id = spawns[0]["child_session_id"]

        children = get_json(
            daemon, f"/v1/surface/sessions/{opened.session.session_id}/children"
        )
        assert children["children_included_in_totals"] is True
        assert children["turns"]
        rows = [
            row
            for turn_row in children["turns"]
            for row in turn_row["children"]
        ]
        assert [row["child_session_id"] for row in rows] == [child_session_id]
        assert rows[0]["status"] == "completed"
        assert rows[0]["agent_type"] == "explore"
        # The digest-only rule holds for the child-agent records: neither the
        # prompt nor the child's completion text appears in the projection.
        serialized = json.dumps(children)
        assert "read the fixture and report" not in serialized
        assert "CHILD-READ-finished" not in serialized

        # The child is a real session: it is listed and readable, and it has its
        # own task stream with its own policy decision and receipt.
        listing = get_json(daemon, "/v1/surface/sessions?limit=50")
        assert child_session_id in {
            entry["session_id"] for entry in listing["sessions"]
        }
        child_events = durable_events(
            tmp_path / "agent-os.sqlite3", spawns[0]["child_task_id"]
        )
        kinds = [event_type for event_type, _ in child_events]
        assert "POLICY_DECIDED" in kinds
        assert "ACTION_RECEIPT_RECORDED" in kinds
        # The child's own session messages are recorded as any session's are.
        assert any(
            "CHILD-READ-finished" in json.dumps(payload)
            for event_type, payload in child_events
            if event_type == "SESSION_MESSAGE_RECORDED"
        )
    finally:
        if daemon is not None:
            daemon.stop()
        provider.close()


# ---------------------------------------------------------------------------
# Scenario 2: the switch is off by default and refuses durably
# ---------------------------------------------------------------------------


def test_daemon_with_the_switch_off_refuses_the_same_spawn(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    provider = ProviderStub()
    daemon: Daemon | None = None
    try:
        daemon = start_daemon(
            tmp_path,
            root,
            provider,
            [
                {
                    "text": "",
                    "tool_calls": [
                        spawn_call(
                            {
                                "prompt": "read the fixture",
                                "description": "child under a disabled switch",
                            }
                        )
                    ],
                },
                {"text": "parent done"},
            ],
            index=1,
            child_agents=None,
        )
        client = SurfaceClient(load_runtime_descriptor(daemon.descriptor_path))
        opened = client.open_session("parent statement")
        turn = client.run_turn(opened.session.session_id, "try to spawn")

        assert turn.stop_reason == "unauthorized_proposal"
        events = durable_events(
            tmp_path / "agent-os.sqlite3", opened.session.task_id
        )
        assert not [event for event in events if event[0].startswith("CHILD_AGENT")]
        denials = [
            payload
            for event_type, payload in events
            if event_type == "POLICY_VERDICT_RECORDED"
        ]
        assert any(
            denial.get("capability_id") == "agent.spawn"
            and denial.get("basis") == "out_of_allowlist"
            for denial in denials
        )
    finally:
        if daemon is not None:
            daemon.stop()
        provider.close()


# ---------------------------------------------------------------------------
# Scenario 3: the operator's correction on the parent stops the child
# ---------------------------------------------------------------------------


def test_daemon_parent_correction_stops_the_children_pending_dispatch(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    provider = ProviderStub()
    daemon: Daemon | None = None
    try:
        daemon = start_daemon(
            tmp_path,
            root,
            provider,
            [
                {
                    "text": "",
                    "tool_calls": [
                        spawn_call(
                            {
                                "prompt": "edit the fixture",
                                "description": "child that needs a write",
                                "agent_type": "general",
                            }
                        )
                    ],
                },
                {
                    "text": "",
                    "tool_calls": [
                        {
                            "id": "call-edit",
                            "name": "workspace__edit",
                            "arguments": {
                                "path": "fixture.txt",
                                "old_string": "stable\n",
                                "new_string": "changed\n",
                            },
                        }
                    ],
                },
                {"text": "parent finished"},
            ],
            index=1,
        )
        descriptor = load_runtime_descriptor(daemon.descriptor_path)
        client = SurfaceClient(descriptor)
        opened = client.open_session("parent statement")
        parent_session_id = opened.session.session_id
        set_accept_in_workspace(daemon, client, parent_session_id)
        turn = client.run_turn(parent_session_id, "spawn a child that edits")
        assert turn.stop_reason == "completed", turn.text

        database = tmp_path / "agent-os.sqlite3"
        spawns = child_spawn_records(database, opened.session.task_id)
        assert len(spawns) == 1
        child_session_id = spawns[0]["child_session_id"]
        # The child parked on its own permission prompt: the operator sees it.
        child_snapshot = client.get_session(child_session_id)
        assert child_snapshot.pending_approval is not None
        assert child_snapshot.status is SurfaceSessionStatus.WAITING_APPROVAL

        # The operator stops the parent through the existing C7 path.
        client.correct(parent_session_id, "operator stopped the parent")

        # Approving the child's parked action must not dispatch it any more.
        with pytest.raises(Exception) as failure:
            client.decide_approval(
                child_session_id,
                child_snapshot.pending_approval.action_digest,
                ApprovalDisposition.APPROVE,
                "operator approved, then the parent was stopped",
            )
        assert "correction" in str(failure.value).lower()
        assert (root / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
        child_events = durable_events(database, spawns[0]["child_task_id"])
        assert not [
            payload
            for event_type, payload in child_events
            if event_type == "ACTION_RECEIPT_RECORDED"
        ]
        # An operator stop is recorded where the parent's correction is.
        parent_events = durable_events(database, opened.session.task_id)
        assert any(
            event_type == "CORRECTION_WRITTEN" for event_type, _ in parent_events
        )
    finally:
        if daemon is not None:
            daemon.stop()
        provider.close()


# ---------------------------------------------------------------------------
# Scenario 4: a runtime killed mid-child leaves an ownerless child, buried by
# the operator as an unknown outcome
# ---------------------------------------------------------------------------


def test_daemon_crash_mid_child_is_buried_as_an_unknown_outcome(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    provider = ProviderStub()
    first: Daemon | None = None
    second: Daemon | None = None
    database = tmp_path / "agent-os.sqlite3"
    try:
        first = start_daemon(
            tmp_path,
            root,
            provider,
            [
                {
                    "text": "",
                    "tool_calls": [
                        spawn_call(
                            {
                                "prompt": "slow child work",
                                "description": "child the runtime dies inside",
                            }
                        )
                    ],
                },
                {"text": "child would have finished", "delay_seconds": 60.0},
            ],
            index=1,
        )
        client = SurfaceClient(load_runtime_descriptor(first.descriptor_path))
        opened = client.open_session("parent statement")
        # The generation id this runtime stamps on what it owns (the same one a
        # stream subscription carries), not the descriptor's bookkeeping id.
        first_boot = client.subscribe_stream(opened.session.session_id).runtime_boot_id
        set_accept_in_workspace(first, client, opened.session.session_id)
        begin_turn(client, opened.session.session_id, "spawn a slow child", "idem:begin:1")

        def child_started() -> bool:
            records = child_spawn_records(database, opened.session.task_id)
            if not records:
                return False
            child_task = records[0]["child_task_id"]
            return any(
                event_type == "SESSION_TURN_STARTED"
                for event_type, _ in durable_events(database, child_task)
            )

        assert wait_for(child_started, timeout=30.0), "the child turn never started"
        first.crash()
        first = None

        second = start_daemon(
            tmp_path,
            root,
            provider,
            [{"text": "unused"}],
            index=2,
        )
        children = get_json(
            second, f"/v1/surface/sessions/{opened.session.session_id}/children"
        )
        assert len(children["orphaned"]) == 1
        orphan = children["orphaned"][0]
        assert orphan["spawned_by_current_generation"] is False
        assert orphan["spawn_runtime_boot_id"] == first_boot

        buried = post_json(
            second,
            f"/v1/surface/sessions/{opened.session.session_id}/children/reconcile",
            {
                "protocol_version": "1.1",
                "client": {
                    "client_id": "tui-1",
                    "client_type": "CLI",
                    "principal_id": "user:local",
                    "tenant_id": "tenant:local",
                    "workspace_id": "workspace:local",
                    "device_id": "device:local",
                },
                "session_id": opened.session.session_id,
                "reason": "the runtime died mid-child",
                "idempotency_key": "idem:reconcile:1",
                "requested_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        assert len(buried["buried"]) == 1
        record = buried["buried"][0]
        assert record["reason_code"] == "CHILD_RUNTIME_GENERATION_GONE"
        assert record["outcome"] == "UNKNOWN"
        assert record["declared_by"] == "user:local"

        events = durable_events(database, opened.session.task_id)
        finishes = [
            payload for event_type, payload in events if event_type == "CHILD_AGENT_FINISHED"
        ]
        assert finishes
        assert finishes[-1]["status"] == "failed"
        assert finishes[-1]["status"] != "completed"
        assert finishes[-1]["stop_reason"] == "unknown_requires_review"
        assert any(
            event_type == "CHILD_AGENT_RECONCILED" for event_type, _ in events
        )

        # No component resurrects the dead child, and the parent's turn is
        # exactly the dead turn it was: started, never completed.
        after = get_json(
            second, f"/v1/surface/sessions/{opened.session.session_id}/children"
        )
        assert after["orphaned"] == []
        started = {
            payload["turn_id"]
            for event_type, payload in events
            if event_type == "SESSION_TURN_STARTED"
        }
        completed = {
            payload["turn_id"]
            for event_type, payload in events
            if event_type == "SESSION_TURN_COMPLETED"
        }
        assert started
        assert started.isdisjoint(completed)
    finally:
        for daemon in (first, second):
            if daemon is not None:
                daemon.stop()
        provider.close()
