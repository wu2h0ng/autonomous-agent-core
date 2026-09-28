from __future__ import annotations

import json
import sys
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from apps.cli import __main__ as cli


@dataclass
class FakeTask:
    task_id: str


class FakeApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.provider_configured = True

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
        return {
            "task_id": task_id,
            "status": "WAITING",
            "run": {"run_id": "run:cli", "status": "WAITING_APPROVAL"},
            "configuration_snapshot": {
                "snapshot_id": "task-configuration:cli",
            },
            "observed_outcome": None,
            "proposed_action": {
                "capability_id": "workspace.apply_patch",
                "action_digest": "a" * 64,
                "arguments": {"path": "fixture.txt", "content": "after\n"},
            },
        }

    def create_task(self, payload: dict[str, object]) -> FakeTask:
        self.calls.append(("create", payload))
        return FakeTask("task:daily")

    def commit_task(self, task_id: str, payload: dict[str, object]) -> FakeTask:
        self.calls.append(("commit", (task_id, payload)))
        return FakeTask(task_id)

    def seal_task_configuration(
        self,
        task_id: str,
        payload: dict[str, object],
    ) -> object:
        self.calls.append(("seal", (task_id, payload)))

        class Snapshot:
            snapshot_id = "task-configuration:cli"

        return Snapshot()

    def run_task(
        self,
        task_id: str,
        inputs: dict[str, object],
        **kwargs,
    ) -> FakeTask:
        self.calls.append(("run", (task_id, inputs, kwargs)))
        return FakeTask(task_id)

    def record_approval(self, task_id: str, payload: dict[str, object]) -> FakeTask:
        self.calls.append(("approval", (task_id, payload)))
        return FakeTask(task_id)


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


def test_cli_routes_live_provider_outcome_smoke(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-os", "live-provider-outcome-smoke", "--model-id", "model:test"],
    )
    monkeypatch.setattr(
        cli,
        "run_live_provider_outcome_smoke",
        lambda **kwargs: {
            "model_id": kwargs["model_id"],
            "outcome_status": "VERIFIED",
            "task_status": "COMPLETED",
        },
    )

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 0

    assert json.loads(capsys.readouterr().out) == {
        "model_id": "model:test",
        "outcome_status": "VERIFIED",
        "task_status": "COMPLETED",
    }


def test_work_run_commits_seals_and_starts_daily_outcome_task(
    monkeypatch,
    capsys,
) -> None:
    fake = FakeApplication()
    monkeypatch.setattr(cli, "AgentOSApplication", lambda **kwargs: fake)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "--workspace",
            ".",
            "work",
            "change fixture to after newline",
            "--run",
            "--target-path",
            "fixture.txt",
            "--test-command",
            "python3 -m pytest",
        ],
    )

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["task_id"] == "task:daily"
    assert output["snapshot_id"] == "task-configuration:cli"
    assert output["run_status"] == "WAITING_APPROVAL"
    assert output["proposed_action"]["arguments"]["path"] == "fixture.txt"
    assert [name for name, _ in fake.calls] == ["create", "commit", "seal", "run"]
    commit_call = cast(tuple[str, object], fake.calls[1][1])
    commitment_payload = cast(tuple[str, dict[str, object]], commit_call)[1]
    assert isinstance(commitment_payload, dict)
    commitment = cast(dict[str, object], commitment_payload["commitment"])
    assert isinstance(commitment, dict)
    expires_at = cast(datetime, commitment["expires_at"])
    accepted_at = cast(datetime, commitment["accepted_at"])
    assert expires_at > accepted_at
    run_call = cast(tuple[str, dict[str, object], dict[str, object]], fake.calls[3][1])
    assert run_call[2] == {
        "configuration_snapshot_id": "task-configuration:cli",
        "recover_stale_lease": True,
    }


def test_approve_records_approval_and_resumes_bound_snapshot(
    monkeypatch,
    capsys,
) -> None:
    fake = FakeApplication()
    monkeypatch.setattr(cli, "AgentOSApplication", lambda **kwargs: fake)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "approve",
            "task:daily",
            "--reason",
            "reviewed exact patch",
            "--target-path",
            "fixture.txt",
            "--test-command",
            "python3 -m pytest",
        ],
    )

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["task_id"] == "task:daily"
    assert [name for name, _ in fake.calls] == ["approval", "run"]
    assert fake.calls[0][1] == (
        "task:daily",
        {"disposition": "APPROVE", "reason": "reviewed exact patch"},
    )
    assert fake.calls[1][1] == (
        "task:daily",
        {
            "target_path": "fixture.txt",
            "test_command": "python3 -m pytest",
            "recover_stale_lease": True,
        },
        {
            "configuration_snapshot_id": "task-configuration:cli",
            "recover_stale_lease": True,
        },
    )
