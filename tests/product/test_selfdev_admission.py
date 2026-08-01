from __future__ import annotations

from pathlib import Path
import json
import sqlite3
import subprocess

import pytest
from agent_os_contracts import (
    OutcomePortfolioCreateCommand,
    PrincipalIdentity,
    PrincipalRole,
    SelfDevelopmentAdmissionCommand,
    SelfDevelopmentWorkSpec,
    TaskEventType,
    content_digest,
)
from agent_os_core.mandate_terminal import attach_mandate
from agent_os_core.provider import DeterministicProvider
from agent_os_core.selfdev_admission import admit_self_development
from agent_os_core.selfdev_admission import SelfDevelopmentAdmissionError
from apps.cli import __main__ as cli_module
from apps.api_server.app import AgentOSApplication
from tests.product.test_mandate_observation_authorization import (
    NOW,
    _apps,
    _command,
)
from tests.product.test_responsibility_controller import (
    AUTHORITY_BEARER,
    _linked_worktree,
)


def _principal(principal_id: str, role: PrincipalRole) -> PrincipalIdentity:
    return PrincipalIdentity(
        principal_id=principal_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        role=role,
        authenticated_at=NOW,
    )


def _setup(tmp_path: Path):
    isolated, branch, head = _linked_worktree(tmp_path)
    exclude_path = Path(
        subprocess.run(
            ["git", "-C", str(isolated), "rev-parse", "--git-path", "info/exclude"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    exclude_path.write_text(
        exclude_path.read_text(encoding="utf-8") + "\n.agent_os/\n",
        encoding="utf-8",
    )
    database, owner, admin = _apps(tmp_path)
    admin.authorize_mandate_observation_binding(
        "mandate:build-agent-os",
        _command(),
    )
    admin.mandate_outcome_portfolio_store.create_portfolio(
        OutcomePortfolioCreateCommand(
            reason="SELFDEV admission truth",
            authority_credential_digest=content_digest(
                {"agent_work_authority_bearer": AUTHORITY_BEARER}
            ),
        ),
        "mandate:build-agent-os",
        admin.principal,
    )
    attach_mandate(
        workspace=isolated,
        database=database,
        mandate_id="mandate:build-agent-os",
        environment_binding_id="binding:data-agent-report:v1",
        principal_id=owner.principal.principal_id,
        tenant_id=owner.principal.tenant_id,
        workspace_id=owner.principal.workspace_id,
        evaluated_at=NOW,
    )
    execution = AgentOSApplication(
        database=database,
        workspace=isolated,
        principal=_principal("principal:owner", PrincipalRole.PRINCIPAL),
        clock=lambda: NOW,
    )
    authority = AgentOSApplication(
        database=database,
        workspace=isolated,
        principal=_principal("principal:security", PrincipalRole.TENANT_ADMIN),
        clock=lambda: NOW,
    )
    execution.provider_configured = True
    command = SelfDevelopmentAdmissionCommand(
        admission_id="selfdev-admission:one",
        statement="Make the exact bounded product change",
        deliverables=("bounded implementation",),
        acceptance_criteria=("pytest passes",),
        selfdev_spec=SelfDevelopmentWorkSpec(
            repository_head=head,
            isolated_branch=branch,
            target_path=(
                "packages/os_core/src/agent_os_core/selfdev_fixture.py"
            ),
            edit_mode="agent_loop_precise",
            verifier_command="pytest",
        ),
    )
    return database, isolated, authority, execution, command


def test_exact_replay_converges_without_execution_side_effects(tmp_path: Path) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)

    first = admit_self_development(
        app=authority,
        execution_app=execution,
        workspace=workspace,
        database=database,
        command=command,
    )
    second = admit_self_development(
        app=authority,
        execution_app=execution,
        workspace=workspace,
        database=database,
        command=command,
    )

    assert first.replayed is False
    assert second.replayed is True
    assert second.model_copy(update={"replayed": False}) == first
    task = execution.tasks.get_task(first.task_id)
    assert task.run is not None and task.run.run_id == first.run_id
    assert task.configuration_snapshot is not None
    assert len(authority.mandate_responsibility_store.list_links(
        first.mandate_id, authority.principal
    )) == 1
    portfolio = authority.mandate_outcome_portfolio_store.get_view(
        first.mandate_id, authority.principal, include_resolved_help=True
    )
    assert len(portfolio.commitments) == 1
    assert portfolio.help_requests == ()
    assert task.approval is None
    assert task.observed_outcome is None
    assert isinstance(execution.provider, DeterministicProvider)
    assert execution.provider.decision_requests == []
    events = execution.tasks._event_store.read(first.task_id)
    assert not any(
        event.event_type
        in {
            TaskEventType.ACTION_PROPOSED,
            TaskEventType.APPROVAL_RECORDED,
            TaskEventType.ACTION_RECEIPT_RECORDED,
            TaskEventType.OUTCOME_OBSERVED,
        }
        for event in events
    )
    connection = sqlite3.connect(str(database))
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table in {"hcw_evaluator_roots", "hcw_measurement_receipts"} & tables:
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        connection.close()


def test_contract_rejects_non_precise_mode() -> None:
    head = "a" * 40
    try:
        SelfDevelopmentAdmissionCommand(
            admission_id="selfdev-admission:bad",
            statement="bad",
            deliverables=("bad",),
            acceptance_criteria=("bad",),
            selfdev_spec=SelfDevelopmentWorkSpec(
                repository_head=head,
                isolated_branch="codex/bad",
                target_path="packages/os_core/src/agent_os_core/fixture.py",
                verifier_command="pytest",
            ),
        )
    except ValueError as exc:
        assert "agent_loop_precise" in str(exc)
    else:
        raise AssertionError("non-precise admission must fail")


@pytest.mark.parametrize(
    "crash_point",
    (
        "AFTER_TASK_CREATED",
        "AFTER_TASK_COMMITTED",
        "AFTER_LINKED",
        "AFTER_COMMITMENT_ATTACHED",
        "AFTER_CONFIGURATION_SEALED",
        "AFTER_RUN_STARTED",
        "BEFORE_ADMITTED",
        "AFTER_ADMITTED",
    ),
)
def test_every_cross_store_response_loss_converges(
    tmp_path: Path,
    crash_point: str,
) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)

    def crash(phase: str) -> None:
        if phase == crash_point:
            raise RuntimeError(f"crash at {phase}")

    with pytest.raises(RuntimeError, match=crash_point):
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command,
            phase_hook=crash,
        )

    interrupted_view = authority.mandate_outcome_portfolio_store.get_view(
        "mandate:build-agent-os",
        authority.principal,
        include_resolved_help=True,
    )
    linearized = crash_point in {
        "AFTER_COMMITMENT_ATTACHED",
        "BEFORE_ADMITTED",
        "AFTER_ADMITTED",
    }
    assert len(interrupted_view.commitments) == (1 if linearized else 0)
    if linearized:
        interrupted_task = execution.tasks.get_task(
            interrupted_view.commitments[0].task_id
        )
        assert interrupted_task.configuration_snapshot is not None
        assert interrupted_task.run is not None
        assert (
            interrupted_task.run.run_id
            == interrupted_task.configuration_snapshot.reserved_run_id
        )

    recovered = admit_self_development(
        app=authority,
        execution_app=execution,
        workspace=workspace,
        database=database,
        command=command,
    )
    assert recovered.replayed is True
    events = execution.tasks._event_store.read(recovered.task_id)
    assert tuple(event.event_type for event in events) == (
        TaskEventType.TASK_CREATED,
        TaskEventType.TASK_COMMITTED,
        TaskEventType.TASK_CONFIGURATION_SNAPSHOT_SEALED,
        TaskEventType.RUN_STARTED,
    )
    portfolio = authority.mandate_outcome_portfolio_store.get_view(
        recovered.mandate_id,
        authority.principal,
        include_resolved_help=True,
    )
    assert len(portfolio.commitments) == 1
    assert portfolio.help_requests == ()


def test_same_id_divergent_command_fails_before_new_state(tmp_path: Path) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    admit_self_development(
        app=authority,
        execution_app=execution,
        workspace=workspace,
        database=database,
        command=command,
    )

    with pytest.raises(SelfDevelopmentAdmissionError) as excinfo:
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command.model_copy(update={"statement": "different bytes"}),
        )
    assert excinfo.value.code == "ADMISSION_COMMAND_CONFLICT"


def test_different_id_same_active_semantics_conflicts(tmp_path: Path) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    first = admit_self_development(
        app=authority,
        execution_app=execution,
        workspace=workspace,
        database=database,
        command=command,
    )

    with pytest.raises(SelfDevelopmentAdmissionError) as excinfo:
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command.model_copy(
                update={"admission_id": "selfdev-admission:duplicate"}
            ),
        )
    assert excinfo.value.code == "ADMISSION_SEMANTIC_DUPLICATE"
    assert len(
        authority.mandate_outcome_portfolio_store.get_view(
            first.mandate_id, authority.principal
        ).commitments
    ) == 1


def test_replay_detects_provider_profile_drift(tmp_path: Path) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)

    with pytest.raises(RuntimeError):
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command,
            phase_hook=lambda phase: (
                (_ for _ in ()).throw(RuntimeError("stop"))
                if phase == "AFTER_TASK_CREATED"
                else None
            ),
        )
    execution.provider_profile = execution.provider_profile.model_copy(
        update={"model_id": "drifted-model"}
    )

    with pytest.raises(SelfDevelopmentAdmissionError) as excinfo:
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command,
        )
    assert excinfo.value.code == "ADMISSION_STATE_DRIFT"
    assert "provider" in excinfo.value.details


def test_replay_detects_worktree_head_drift(tmp_path: Path) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)

    with pytest.raises(RuntimeError):
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command,
            phase_hook=lambda phase: (
                (_ for _ in ()).throw(RuntimeError("stop"))
                if phase == "AFTER_TASK_CREATED"
                else None
            ),
        )
    target = workspace / command.selfdev_spec.target_path
    target.write_text("VALUE = False\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(workspace), "add", str(target)], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "commit", "-m", "drift"],
        check=True,
        capture_output=True,
    )

    with pytest.raises(SelfDevelopmentAdmissionError) as excinfo:
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command,
        )
    assert excinfo.value.code == "ADMISSION_WORKTREE_DRIFT"


def test_typed_replay_ignores_json_formatting_provenance(tmp_path: Path) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    first = admit_self_development(
        app=authority,
        execution_app=execution,
        workspace=workspace,
        database=database,
        command=command,
        source_digest="a" * 64,
    )
    replay = admit_self_development(
        app=authority,
        execution_app=execution,
        workspace=workspace,
        database=database,
        command=command,
        source_digest="b" * 64,
    )
    assert replay.replayed is True
    assert replay.model_copy(update={"replayed": False}) == first


def test_admitted_replay_allows_only_frozen_target_dirtiness(tmp_path: Path) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    receipt = admit_self_development(
        app=authority,
        execution_app=execution,
        workspace=workspace,
        database=database,
        command=command,
    )
    target = workspace / command.selfdev_spec.target_path
    target.write_text("VALUE = False\n", encoding="utf-8")

    replay = admit_self_development(
        app=authority,
        execution_app=execution,
        workspace=workspace,
        database=database,
        command=command,
    )
    assert replay.task_id == receipt.task_id

    (workspace / "fixture.txt").write_text("outside write set\n", encoding="utf-8")
    with pytest.raises(SelfDevelopmentAdmissionError) as excinfo:
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command,
        )
    assert excinfo.value.code == "ADMISSION_WORKTREE_DRIFT"


def test_agent_cli_admits_typed_json_and_replays_reformatted_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    command_path = tmp_path / "admission.json"
    command_path.write_text(command.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(
        cli_module,
        "_work_applications",
        lambda _args: (authority, execution),
    )
    argv = [
        "agent-os",
        "--database",
        str(database),
        "--workspace",
        str(workspace),
        "agent",
        "admit-selfdev",
        str(command_path),
    ]

    with pytest.raises(SystemExit) as first_exit:
        cli_module.main(argv)
    assert first_exit.value.code == 0
    first = json.loads(capsys.readouterr().out)
    assert first["replayed"] is False

    payload = command.model_dump(mode="json")
    command_path.write_text(
        json.dumps(dict(reversed(tuple(payload.items()))), separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as replay_exit:
        cli_module.main(argv)
    assert replay_exit.value.code == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["replayed"] is True
    assert replay["task_id"] == first["task_id"]
    assert replay["run_id"] == first["run_id"]
