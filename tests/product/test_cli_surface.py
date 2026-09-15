from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from apps.cli import __main__ as cli


@dataclass
class FakeTask:
    task_id: str


class FakeApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def signal_task(self, task_id: str, payload: dict[str, object]) -> FakeTask:
        self.calls.append(("signal", (task_id, payload)))
        return FakeTask(task_id)

    def replan_task(self, task_id: str, payload: dict[str, object]) -> FakeTask:
        self.calls.append(("replan", (task_id, payload)))
        return FakeTask(task_id)

    def resume_correction(self, task_id: str, reason: str) -> FakeTask:
        self.calls.append(("correction-resume", (task_id, reason)))
        return FakeTask(task_id)

    def compensate_task(self, task_id: str) -> FakeTask:
        self.calls.append(("compensate", task_id))
        return FakeTask(task_id)

    def recovery_json(self, task_id: str) -> dict[str, object]:
        self.calls.append(("recovery", task_id))
        return {"task_id": task_id, "event_sequence": 7}

    def task_json(self, task_id: str) -> dict[str, object]:
        return {"task_id": task_id, "status": "OK"}


def test_cli_routes_long_horizon_commands_to_application(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    fake = FakeApplication()
    monkeypatch.setattr(cli, "AgentOSApplication", lambda **kwargs: fake)
    signal_path = tmp_path / "signal.json"
    signal_path.write_text(
        json.dumps(
            {
                "signal_id": "signal:cli",
                "signal_name": "build.finished",
                "correlation_key": "build:cli",
                "payload_json": '{"status":"passed"}',
            }
        ),
        encoding="utf-8",
    )
    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text(json.dumps({"version": 2}), encoding="utf-8")

    invocations = (
        ["agent-os", "task-signal", "task:cli", str(signal_path)],
        [
            "agent-os",
            "task-replan",
            "task:cli",
            str(workflow_path),
            "--reason",
            "replace wait",
        ],
        [
            "agent-os",
            "correction-resume",
            "task:cli",
            "--reason",
            "principal reviewed",
        ],
        ["agent-os", "task-compensate", "task:cli"],
        ["agent-os", "task-recovery", "task:cli"],
    )
    for argv in invocations:
        monkeypatch.setattr(sys, "argv", argv)
        cli.main()
        assert json.loads(capsys.readouterr().out)["task_id"] == "task:cli"

    assert [name for name, _ in fake.calls] == [
        "signal",
        "replan",
        "correction-resume",
        "compensate",
        "recovery",
    ]
    assert fake.calls[1][1] == (
        "task:cli",
        {"workflow": {"version": 2}, "reason": "replace wait"},
    )


class FakeSession:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id


class FakeSnapshot:
    def __init__(
        self,
        session_id: str,
        status: str = "ACTIVE",
        event_sequence: int = 1,
        message_count: int = 2,
        pending_approval: object | None = None,
    ) -> None:
        self.session = FakeSession(session_id)
        self.status = status
        self.event_sequence = event_sequence
        self.message_count = message_count
        self.pending_approval = pending_approval


class FakePendingApproval:
    def __init__(self) -> None:
        self.action_digest = "d" * 64
        self.capability_id = "workspace.edit"
        self.preview = "exact diff preview"


class FakeResponse:
    def __init__(
        self,
        text: str = "completed",
        stop_reason: str = "completed",
        snapshot: FakeSnapshot | None = None,
    ) -> None:
        self.text = text
        self.stop_reason = stop_reason
        self.snapshot = snapshot or FakeSnapshot("session:1")


class FakeSurfaceClient:
    def __init__(
        self,
        *,
        turn_responses: list[FakeResponse] | None = None,
        approve_response: FakeResponse | None = None,
    ) -> None:
        self.calls: list[tuple] = []
        self.turn_responses = list(turn_responses or [])
        self.approve_response = approve_response or FakeResponse()

    def open_session(self, statement: str) -> FakeSnapshot:
        self.calls.append(("open", statement))
        return FakeSnapshot("session:1")

    def get_session(self, session_id: str) -> FakeSnapshot:
        self.calls.append(("get_session", session_id))
        return FakeSnapshot(session_id)

    def run_turn(self, session_id: str, text: str) -> FakeResponse:
        self.calls.append(("turn", session_id, text))
        if self.turn_responses:
            return self.turn_responses.pop(0)
        return FakeResponse()

    def decide_approval(
        self,
        session_id: str,
        action_digest: str,
        disposition: object,
        reason: str,
    ) -> FakeResponse:
        self.calls.append(
            ("approve", session_id, action_digest, disposition, reason)
        )
        return self.approve_response

    def pause(self, session_id: str, reason: str) -> FakeSnapshot:
        self.calls.append(("pause", session_id, reason))
        return FakeSnapshot(session_id, status="PAUSED")

    def resume(self, session_id: str, reason: str) -> FakeSnapshot:
        self.calls.append(("resume", session_id, reason))
        return FakeSnapshot(session_id)

    def correct(self, session_id: str, reason: str) -> FakeSnapshot:
        self.calls.append(("correct", session_id, reason))
        return FakeSnapshot(session_id, status="CORRECTION_HALTED")


def test_session_show_pause_resume_correct_commands(
    monkeypatch,
    capsys,
) -> None:
    fake = FakeSurfaceClient()
    monkeypatch.setattr(cli, "load_surface_client", lambda args: fake)
    monkeypatch.setattr(
        cli,
        "AgentOSApplication",
        lambda **kwargs: pytest.fail("CLI must not open daemon SQLite"),
    )
    for argv in (
        ["agent-os", "session-show", "session:1"],
        ["agent-os", "session-pause", "session:1"],
        ["agent-os", "session-resume", "session:1"],
        ["agent-os", "session-correct", "session:1", "operator review"],
    ):
        monkeypatch.setattr(sys, "argv", argv)
        cli.main()

    assert ("get_session", "session:1") in fake.calls
    assert ("pause", "session:1", "paused by user") in fake.calls
    assert ("resume", "session:1", "resumed by user") in fake.calls
    assert ("correct", "session:1", "operator review") in fake.calls
