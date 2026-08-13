"""Wave 1 end-to-end gate: CLI and protocol client share one restartable coding session."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


from agent_os_contracts import (
    ApprovalDisposition,
    SurfaceSessionStatus,
    TaskEventType,
)

from apps.cli.surface_client import SurfaceClient
from apps.runtime_daemon.descriptor import load_runtime_descriptor


class ScriptedProviderHandler(BaseHTTPRequestHandler):
    script: list[dict] = []
    requests_seen: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests_seen.append(body)
        step = min(len(type(self).requests_seen) - 1, len(type(self).script) - 1)
        entry = type(self).script[max(step, 0)]
        message: dict = {"role": "assistant", "content": entry.get("text", "")}
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
            "id": f"cmpl-{len(type(self).requests_seen)}",
            "choices": [
                {
                    "message": message,
                    "finish_reason": "tool_calls" if tool_calls else "stop",
                }
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
        self.server = HTTPServer(("127.0.0.1", 0), ScriptedProviderHandler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
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
    def __init__(
        self,
        process: subprocess.Popen,
        descriptor_path: Path,
    ) -> None:
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
    index: int = 1,
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


def prepare_failing_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "fixture.txt").write_text("stable\n", encoding="utf-8")
    return workspace


def repair_script() -> list[dict]:
    return [
        {
            "text": "",
            "tool_calls": [
                {
                    "id": "call-edit",
                    "name": "workspace__edit",
                    "arguments": {
                        "path": "fixture.txt",
                        "old_string": "stable\n",
                        "new_string": "fixed\n",
                    },
                }
            ],
        },
        {"text": "fixed complete"},
    ]


def finish_script() -> list[dict]:
    return [{"text": "done"}]


def exactly_one_effect_receipt(client: SurfaceClient, task_id: str) -> bool:
    batch = client.events(task_id, after_sequence=0, wait_ms=0)
    receipts = [
        event
        for event in batch.events
        if event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED
    ]
    return len(receipts) == 1


def cli_session_show(
    daemon: DaemonProcess,
    session_id: str,
) -> dict:
    root = _repo_root()
    env = _daemon_env("http://127.0.0.1:1")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "apps.cli",
            "--descriptor",
            str(daemon.descriptor_path),
            "session-show",
            session_id,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=root,
    )
    assert completed.returncode == 0, completed.stderr
    value = json.loads(completed.stdout)
    assert isinstance(value, dict)
    return value


def test_cli_and_protocol_client_share_one_restartable_coding_session(
    tmp_path: Path,
) -> None:
    workspace = prepare_failing_workspace(tmp_path)
    provider = ProviderStub()
    try:
        daemon = start_runtime_process(
            tmp_path, workspace, provider, repair_script(), index=1
        )
        client = SurfaceClient(
            load_runtime_descriptor(daemon.descriptor_path)
        )

        opened = client.open_session("repair the failing fixture")
        first = client.run_turn(
            opened.session.session_id, "inspect and repair"
        )
        assert first.snapshot.status is SurfaceSessionStatus.WAITING_APPROVAL
        assert first.snapshot.pending_approval is not None

        daemon.stop()
        daemon = start_runtime_process(
            tmp_path, workspace, provider, finish_script(), index=2
        )
        restored_client = SurfaceClient(
            load_runtime_descriptor(daemon.descriptor_path)
        )
        restored = restored_client.get_session(opened.session.session_id)
        assert restored.pending_approval is not None
        assert restored.status is SurfaceSessionStatus.WAITING_APPROVAL

        completed = restored_client.decide_approval(
            restored.session.session_id,
            restored.pending_approval.action_digest,
            ApprovalDisposition.APPROVE,
            "reviewed exact edit",
        )

        assert completed.stop_reason == "completed"
        assert (workspace / "fixture.txt").read_text(encoding="utf-8") == (
            "fixed\n"
        )
        assert exactly_one_effect_receipt(
            restored_client, opened.session.task_id
        )
        assert cli_session_show(
            daemon, opened.session.session_id
        )["event_sequence"] == completed.snapshot.event_sequence
    finally:
        provider.close()
