from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from agent_os_contracts import WorkflowGraph
from apps.cli import __main__ as cli
from agent_os_core import (
    INVALID_SELFDEV_TARGET,
    RUN_DENIED,
    SelfDevelopmentValidationError,
)


@dataclass
class FakeTask:
    task_id: str


class FakeApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.provider_configured = True
        self.provider_profile = SimpleNamespace(
            profile_id="provider-profile:fake",
            provider_id="openai-compatible",
            model_id="frontier-model",
            model_revision_digest=None,
            endpoint_class="openai-compatible",
        )

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


def test_cli_selfdev_run_provider_fails_closed_before_task_create_without_readiness(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for key in (
        "AGENT_OS_PROVIDER_BASE_URL",
        "AGENT_OS_PROVIDER_MODEL",
        "AGENT_OS_PROVIDER_API_KEY_ENV",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    fake = FakeApplication()
    monkeypatch.setattr(cli, "AgentOSApplication", lambda **kwargs: fake)
    spec_path = _write_selfdev_spec(tmp_path, branch="codex/selfdev-provider-denied")
    baseline_path = _write_selfdev_baseline_record(
        tmp_path,
        branch="codex/selfdev-provider-denied",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "selfdev-run-provider",
            str(spec_path),
            "--baseline-record",
            str(baseline_path),
        ],
    )
    try:
        cli.main()
    except SelfDevelopmentValidationError as exc:
        assert exc.code == RUN_DENIED
        assert "REAL_PROVIDER_NOT_CONFIGURED" in exc.detail
    else:
        raise AssertionError("provider SELFDEV should fail closed before task create")
    assert fake.calls == []


def test_cli_selfdev_run_provider_fails_closed_when_runtime_provider_not_bound(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_OS_PROVIDER_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("AGENT_OS_PROVIDER_MODEL", "frontier-model")
    monkeypatch.setenv("AGENT_OS_PROVIDER_API_KEY_ENV", "AGENT_OS_TEST_PROVIDER_KEY")
    monkeypatch.setenv("AGENT_OS_TEST_PROVIDER_KEY", "redacted-test-key")
    fake = FakeApplication()
    fake.provider_configured = False
    monkeypatch.setattr(cli, "AgentOSApplication", lambda **kwargs: fake)
    spec_path = _write_selfdev_spec(
        tmp_path,
        branch="codex/selfdev-provider-runtime-denied",
    )
    baseline_path = _write_selfdev_baseline_record(
        tmp_path,
        branch="codex/selfdev-provider-runtime-denied",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "selfdev-run-provider",
            str(spec_path),
            "--baseline-record",
            str(baseline_path),
        ],
    )
    try:
        cli.main()
    except SelfDevelopmentValidationError as exc:
        assert exc.code == RUN_DENIED
        assert "runtime provider is not configured" in exc.detail
    else:
        raise AssertionError("provider SELFDEV should require runtime binding")
    assert fake.calls == []


def test_cli_selfdev_run_provider_requires_readiness_then_delegates_to_run_gate(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("AGENT_OS_PROVIDER_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("AGENT_OS_PROVIDER_MODEL", "frontier-model")
    monkeypatch.setenv("AGENT_OS_PROVIDER_API_KEY_ENV", "AGENT_OS_TEST_PROVIDER_KEY")
    monkeypatch.setenv("AGENT_OS_TEST_PROVIDER_KEY", "redacted-test-key")
    fake = FakeApplication()
    monkeypatch.setattr(cli, "AgentOSApplication", lambda **kwargs: fake)
    spec_path = _write_selfdev_spec(tmp_path, branch="codex/selfdev-provider-ready")
    baseline_path = _write_selfdev_baseline_record(
        tmp_path,
        branch="codex/selfdev-provider-ready",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "selfdev-run-provider",
            str(spec_path),
            "--baseline-record",
            str(baseline_path),
            "--created-at",
            "2026-07-22T00:00:00+00:00",
        ],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "REAL_PROVIDER_READY_UNTIL_APPROVAL"
    assert output["readiness"]["ready"] is True
    assert output["runtime_provider"] == {
        "configured": True,
        "profile_id": "provider-profile:fake",
        "provider_id": "openai-compatible",
        "model_id": "frontier-model",
        "model_revision_digest": None,
        "endpoint_class": "openai-compatible",
    }
    assert output["task"]["task_id"] == "task:selfdev-created"
    assert [name for name, _ in fake.calls] == ["create", "commit", "run"]
    run_call = fake.calls[2][1]
    assert isinstance(run_call, tuple)
    assert run_call[1] == {
        "target_path": "packages/os_core/src/agent_os_core/recovery.py",
        "test_command": "python -m pytest",
    }
    assert "redacted-test-key" not in json.dumps(output)


def test_cli_selfdev_run_local_executes_existing_spine_with_explicit_patch(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    workspace = tmp_path / "workspace"
    target = workspace / "packages/os_core/src/agent_os_core/recovery.py"
    target.parent.mkdir(parents=True)
    original = "def marker():\n    return 'before'\n"
    patched = "def marker():\n    return 'after'\n"
    target.write_text(original, encoding="utf-8")
    tests = workspace / "tests"
    tests.mkdir()
    (tests / "test_marker.py").write_text(
        "from pathlib import Path\n\n"
        "def test_marker():\n"
        "    text = Path('packages/os_core/src/agent_os_core/recovery.py')"
        ".read_text(encoding='utf-8')\n"
        "    assert \"return 'after'\" in text\n",
        encoding="utf-8",
    )
    patch_path = tmp_path / "patch.txt"
    patch_path.write_text(patched, encoding="utf-8")
    spec_path = _write_selfdev_spec(workspace, branch="codex/selfdev-local-run")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "--database",
            str(tmp_path / "agent.sqlite3"),
            "--workspace",
            str(workspace),
            "selfdev-run-local",
            str(spec_path),
            "--patch-content-file",
            str(patch_path),
            "--approve",
        ],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "LOCAL_CONTROLLED_DETERMINISTIC_PROVIDER"
    assert output["task"]["status"] == "COMPLETED"
    assert output["task"]["observed_outcome"]["status"] == "VERIFIED"
    assert target.read_text(encoding="utf-8") == patched


def test_cli_selfdev_readiness_fails_closed_without_real_provider(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    for key in (
        "AGENT_OS_PROVIDER_BASE_URL",
        "AGENT_OS_PROVIDER_MODEL",
        "AGENT_OS_PROVIDER_API_KEY_ENV",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    spec_path = _write_selfdev_spec(tmp_path, branch="codex/selfdev-readiness")

    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-os", "selfdev-readiness", str(spec_path)],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["ready"] is False
    assert output["provider"] == {
        "base_url_configured": False,
        "model_configured": False,
        "credential_env": "OPENAI_API_KEY",
        "credential_available": False,
    }
    assert output["blockers"] == [
        "REAL_PROVIDER_NOT_CONFIGURED",
        "PROVIDER_CREDENTIAL_UNAVAILABLE",
        "PROVIDER_MODEL_UNSPECIFIED",
        "BASELINE_RECORD_MISSING",
    ]


def test_cli_selfdev_baseline_record_outputs_content_bound_telemetry(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    baseline_path = _write_selfdev_baseline_record(
        tmp_path,
        branch="codex/selfdev-baseline-record",
        evidence_refs=["run:2", "run:1"],
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-os", "selfdev-baseline-record", str(baseline_path)],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["baseline_assignment_id"] == "baseline:codex/selfdev-baseline-record"
    assert output["target_path"] == "packages/os_core/src/agent_os_core/recovery.py"
    assert output["outcome_status"] == "VERIFIED"
    assert output["evidence_refs"] == ["run:1", "run:2"]
    assert len(output["record_digest"]) == 64


def test_cli_selfdev_baseline_capture_runs_verifier_and_emits_digest_only_evidence(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    workspace = tmp_path / "workspace"
    target = workspace / "packages/os_core/src/agent_os_core/recovery.py"
    target.parent.mkdir(parents=True)
    target.write_text("def marker():\n    return 'baseline'\n", encoding="utf-8")
    tests = workspace / "tests"
    tests.mkdir()
    (tests / "test_marker.py").write_text(
        "from pathlib import Path\n\n"
        "def test_marker():\n"
        "    text = Path('packages/os_core/src/agent_os_core/recovery.py')"
        ".read_text(encoding='utf-8')\n"
        "    assert \"baseline\" in text\n"
        "    print('baseline-secret-output')\n",
        encoding="utf-8",
    )
    spec_path = _write_selfdev_spec(workspace, branch="codex/selfdev-baseline-capture")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "selfdev-baseline-capture",
            str(spec_path),
            "--operator-intervention-count",
            "3",
            "--hcw-minutes",
            "4.5",
            "--evidence-ref",
            "session:founder-baseline",
        ],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    baseline_record = output["baseline_record"]
    verifier = output["verifier"]
    assert baseline_record["baseline_assignment_id"] == (
        "baseline:codex/selfdev-baseline-capture"
    )
    assert baseline_record["operator_intervention_count"] == 3
    assert baseline_record["hcw_minutes"] == 4.5
    assert baseline_record["outcome_status"] == "VERIFIED"
    assert verifier["exit_code"] == 0
    assert verifier["evidence_ref"] in baseline_record["evidence_refs"]
    assert "session:founder-baseline" in baseline_record["evidence_refs"]
    assert "baseline-secret-output" not in json.dumps(output)


def test_cli_selfdev_baseline_capture_records_not_met_for_failed_verifier(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    workspace = tmp_path / "workspace"
    target = workspace / "packages/os_core/src/agent_os_core/recovery.py"
    target.parent.mkdir(parents=True)
    target.write_text("def marker():\n    return 'baseline'\n", encoding="utf-8")
    tests = workspace / "tests"
    tests.mkdir()
    (tests / "test_marker.py").write_text(
        "def test_marker():\n"
        "    assert False\n",
        encoding="utf-8",
    )
    spec_path = _write_selfdev_spec(
        workspace,
        branch="codex/selfdev-baseline-capture-fail",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "selfdev-baseline-capture",
            str(spec_path),
            "--operator-intervention-count",
            "1",
            "--hcw-minutes",
            "2",
        ],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["verifier"]["exit_code"] == 1
    assert output["baseline_record"]["outcome_status"] == "NOT_MET"


def test_cli_selfdev_readiness_fails_closed_without_baseline_record(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("AGENT_OS_PROVIDER_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("AGENT_OS_PROVIDER_MODEL", "frontier-model")
    monkeypatch.setenv("AGENT_OS_PROVIDER_API_KEY_ENV", "AGENT_OS_TEST_PROVIDER_KEY")
    monkeypatch.setenv("AGENT_OS_TEST_PROVIDER_KEY", "redacted-test-key")
    spec_path = _write_selfdev_spec(tmp_path, branch="codex/selfdev-ready-no-baseline")

    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-os", "selfdev-readiness", str(spec_path)],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["ready"] is False
    assert output["blockers"] == ["BASELINE_RECORD_MISSING"]
    assert "redacted-test-key" not in json.dumps(output)


def test_cli_selfdev_compare_outputs_hcw_verdict_receipt(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    spec_path = _write_selfdev_spec(tmp_path, branch="codex/selfdev-compare")
    baseline_path = _write_selfdev_baseline_record(
        tmp_path,
        branch="codex/selfdev-compare",
        operator_intervention_count=3,
        hcw_minutes=5.5,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "selfdev-compare",
            str(spec_path),
            str(baseline_path),
            "--selfdev-outcome-status",
            "VERIFIED",
            "--selfdev-evidence-ref",
            "selfdev:run",
        ],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["verdict"] == "SELFDEV_HCW_LOWER"
    assert output["baseline_hcw_minutes"] == 5.5
    assert output["selfdev_hcw_minutes"] == 0.25
    assert output["hcw_delta_minutes"] == -5.25
    assert output["operator_intervention_delta"] == -2
    assert output["selfdev_evidence_refs"] == ["selfdev:run"]
    assert len(output["receipt_digest"]) == 64


def test_cli_selfdev_compare_does_not_claim_win_when_outcome_not_verified(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    spec_path = _write_selfdev_spec(tmp_path, branch="codex/selfdev-compare-not-met")
    baseline_path = _write_selfdev_baseline_record(
        tmp_path,
        branch="codex/selfdev-compare-not-met",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "selfdev-compare",
            str(spec_path),
            str(baseline_path),
            "--selfdev-outcome-status",
            "NOT_MET",
            "--selfdev-evidence-ref",
            "selfdev:run",
        ],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["verdict"] == "INCOMPARABLE_OUTCOME_NOT_VERIFIED"


def test_cli_selfdev_readiness_passes_with_provider_and_matched_baseline_record(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("AGENT_OS_PROVIDER_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("AGENT_OS_PROVIDER_MODEL", "frontier-model")
    monkeypatch.setenv("AGENT_OS_PROVIDER_API_KEY_ENV", "AGENT_OS_TEST_PROVIDER_KEY")
    monkeypatch.setenv("AGENT_OS_TEST_PROVIDER_KEY", "redacted-test-key")
    spec_path = _write_selfdev_spec(tmp_path, branch="codex/selfdev-ready")
    baseline_path = _write_selfdev_baseline_record(tmp_path, branch="codex/selfdev-ready")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "selfdev-readiness",
            str(spec_path),
            "--baseline-record",
            str(baseline_path),
        ],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["ready"] is True
    assert output["blockers"] == []
    assert output["provider"] == {
        "base_url_configured": True,
        "model_configured": True,
        "credential_env": "AGENT_OS_TEST_PROVIDER_KEY",
        "credential_available": True,
    }
    assert "redacted-test-key" not in json.dumps(output)


def test_cli_selfdev_readiness_rejects_mismatched_baseline_target(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("AGENT_OS_PROVIDER_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("AGENT_OS_PROVIDER_MODEL", "frontier-model")
    monkeypatch.setenv("AGENT_OS_PROVIDER_API_KEY_ENV", "AGENT_OS_TEST_PROVIDER_KEY")
    monkeypatch.setenv("AGENT_OS_TEST_PROVIDER_KEY", "redacted-test-key")
    spec_path = _write_selfdev_spec(tmp_path, branch="codex/selfdev-mismatch")
    baseline_path = _write_selfdev_baseline_record(
        tmp_path,
        branch="codex/selfdev-mismatch",
        target_path="packages/os_core/src/agent_os_core/provider.py",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "selfdev-readiness",
            str(spec_path),
            "--baseline-record",
            str(baseline_path),
        ],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["ready"] is False
    assert output["blockers"] == ["BASELINE_TARGET_MISMATCH"]
    assert "redacted-test-key" not in json.dumps(output)


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


def _write_selfdev_baseline_record(
    tmp_path: Path,
    *,
    branch: str,
    target_path: str = "packages/os_core/src/agent_os_core/recovery.py",
    operator_intervention_count: int = 2,
    hcw_minutes: float = 3.5,
    evidence_refs: list[str] | None = None,
) -> Path:
    baseline_path = tmp_path / f"{branch.replace('/', '-')}-baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "baseline_assignment_id": f"baseline:{branch}",
                "repository_id": "autonomous-agent-core",
                "target_path": target_path,
                "operator_intervention_count": operator_intervention_count,
                "hcw_minutes": hcw_minutes,
                "outcome_status": "VERIFIED",
                "evidence_refs": evidence_refs or ["run:baseline"],
            }
        ),
        encoding="utf-8",
    )
    return baseline_path
