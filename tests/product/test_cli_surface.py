from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from apps.cli import __main__ as cli
from agent_os_core import INVALID_SELFDEV_TARGET, SelfDevelopmentValidationError


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


def test_cli_selfdev_validate_outputs_admission_receipt(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(cli, "AgentOSApplication", lambda **kwargs: FakeApplication())
    spec_path = tmp_path / "selfdev.json"
    spec_path.write_text(
        json.dumps(
            {
                "mandate_id": "META-SHADOW-MANDATE-0",
                "repository_id": "autonomous-agent-core",
                "repository_head": "0123456789abcdef",
                "isolated_workspace": str(tmp_path),
                "isolated_branch": "codex/selfdev-s1-cli",
                "target_path": "packages/os_core/src/agent_os_core/recovery.py",
                "verifier_commands": ["python -m pytest"],
                "expected_outcome_id": "expected:selfdev-s1-cli",
                "rollback_strategy": "compensate_task",
                "operator_intervention_count": 1,
                "hcw_minutes": 0.25,
                "baseline_assignment_id": "baseline:selfdev-s1-cli",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-os", "selfdev-validate", str(spec_path)],
    )
    cli.main()

    receipt = json.loads(capsys.readouterr().out)
    assert receipt["target_path"] == "packages/os_core/src/agent_os_core/recovery.py"
    assert receipt["verifier_commands"] == ["python -m pytest"]
    assert len(receipt["receipt_digest"]) == 64


def test_cli_selfdev_validate_rejects_generic_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(cli, "AgentOSApplication", lambda **kwargs: FakeApplication())
    spec_path = tmp_path / "selfdev-invalid.json"
    spec_path.write_text(
        json.dumps(
            {
                "mandate_id": "META-SHADOW-MANDATE-0",
                "repository_id": "autonomous-agent-core",
                "repository_head": "0123456789abcdef",
                "isolated_workspace": str(tmp_path),
                "isolated_branch": "codex/selfdev-s1-cli",
                "target_path": "fixture.txt",
                "verifier_commands": ["python -m pytest"],
                "expected_outcome_id": "expected:selfdev-s1-cli",
                "rollback_strategy": "compensate_task",
                "operator_intervention_count": 1,
                "hcw_minutes": 0.25,
                "baseline_assignment_id": "baseline:selfdev-s1-cli",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-os", "selfdev-validate", str(spec_path)],
    )
    try:
        cli.main()
    except SelfDevelopmentValidationError as exc:
        assert exc.code == INVALID_SELFDEV_TARGET
    else:
        raise AssertionError("generic target should fail closed")
