from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from agent_os_contracts import WorkflowGraph
from apps.cli import __main__ as cli
from agent_os_core import INVALID_SELFDEV_TARGET, SelfDevelopmentValidationError


@dataclass
class FakeTask:
    task_id: str


class FakeApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def create_task(self, payload: dict[str, object]) -> FakeTask:
        self.calls.append(("create", payload))
        return FakeTask("task:selfdev-created")

    def commit_task(self, task_id: str, payload: dict[str, object]) -> FakeTask:
        self.calls.append(("commit", (task_id, payload)))
        return FakeTask(task_id)

    def run_task(self, task_id: str, inputs: dict[str, object]) -> FakeTask:
        self.calls.append(("run", (task_id, inputs)))
        return FakeTask(task_id)

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


def test_cli_selfdev_prepare_outputs_commit_payload_and_run_inputs(
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
                "isolated_branch": "codex/selfdev-s2-cli",
                "target_path": "packages/os_core/src/agent_os_core/recovery.py",
                "verifier_commands": ["python -m pytest"],
                "expected_outcome_id": "expected:selfdev-s2-cli",
                "rollback_strategy": "compensate_task",
                "operator_intervention_count": 1,
                "hcw_minutes": 0.25,
                "baseline_assignment_id": "baseline:selfdev-s2-cli",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "selfdev-prepare",
            str(spec_path),
            "--task-id",
            "task:selfdev-s2-cli",
            "--created-at",
            "2026-07-22T00:00:00+00:00",
        ],
    )
    cli.main()

    package = json.loads(capsys.readouterr().out)
    receipt = package["admission_receipt"]
    commit_payload = package["task_commit_payload"]
    run_inputs = package["run_inputs"]
    assert receipt["target_path"] == "packages/os_core/src/agent_os_core/recovery.py"
    assert commit_payload["commitment"]["task_id"] == "task:selfdev-s2-cli"
    assert commit_payload["expected_outcome"]["task_id"] == "task:selfdev-s2-cli"
    assert (
        commit_payload["expected_outcome"]["expected_outcome_id"]
        == "expected:selfdev-s2-cli"
    )
    assert (
        commit_payload["selfdev_admission_receipt"]["receipt_digest"]
        == receipt["receipt_digest"]
    )
    WorkflowGraph.model_validate(commit_payload["workflow"])
    assert run_inputs == {
        "target_path": "packages/os_core/src/agent_os_core/recovery.py",
        "test_command": "python -m pytest",
    }


def test_cli_selfdev_create_commits_prepared_package_without_running(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    fake = FakeApplication()
    monkeypatch.setattr(cli, "AgentOSApplication", lambda **kwargs: fake)
    spec_path = _write_selfdev_spec(tmp_path, branch="codex/selfdev-s3-cli")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "--database",
            str(tmp_path / "agent.sqlite3"),
            "--workspace",
            str(tmp_path),
            "selfdev-create",
            str(spec_path),
            "--created-at",
            "2026-07-22T00:00:00+00:00",
        ],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert [name for name, _ in fake.calls] == ["create", "commit"]
    assert output["task"]["task_id"] == "task:selfdev-created"
    commit_call = fake.calls[1][1]
    assert isinstance(commit_call, tuple)
    commit_task_id, commit_payload = commit_call
    assert isinstance(commit_payload, dict)
    assert commit_task_id == "task:selfdev-created"
    assert commit_payload["commitment"]["task_id"] == "task:selfdev-created"
    assert output["package"]["run_inputs"] == {
        "target_path": "packages/os_core/src/agent_os_core/recovery.py",
        "test_command": "python -m pytest",
    }


def test_cli_selfdev_create_can_delegate_to_existing_run_gate(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    fake = FakeApplication()
    monkeypatch.setattr(cli, "AgentOSApplication", lambda **kwargs: fake)
    spec_path = _write_selfdev_spec(tmp_path, branch="codex/selfdev-s3-run-cli")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "selfdev-create",
            str(spec_path),
            "--created-at",
            "2026-07-22T00:00:00+00:00",
            "--run-until-approval",
        ],
    )
    cli.main()

    json.loads(capsys.readouterr().out)
    assert [name for name, _ in fake.calls] == ["create", "commit", "run"]
    run_call = fake.calls[2][1]
    assert isinstance(run_call, tuple)
    run_task_id, run_inputs = run_call
    assert run_task_id == "task:selfdev-created"
    assert run_inputs == {
        "target_path": "packages/os_core/src/agent_os_core/recovery.py",
        "test_command": "python -m pytest",
    }


def _write_selfdev_spec(tmp_path: Path, *, branch: str) -> Path:
    spec_path = tmp_path / f"{branch.replace('/', '-')}.json"
    spec_path.write_text(
        json.dumps(
            {
                "mandate_id": "META-SHADOW-MANDATE-0",
                "repository_id": "autonomous-agent-core",
                "repository_head": "0123456789abcdef",
                "isolated_workspace": str(tmp_path),
                "isolated_branch": branch,
                "target_path": "packages/os_core/src/agent_os_core/recovery.py",
                "verifier_commands": ["python -m pytest"],
                "expected_outcome_id": f"expected:{branch}",
                "rollback_strategy": "compensate_task",
                "operator_intervention_count": 1,
                "hcw_minutes": 0.25,
                "baseline_assignment_id": f"baseline:{branch}",
            }
        ),
        encoding="utf-8",
    )
    return spec_path
