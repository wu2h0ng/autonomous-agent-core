from __future__ import annotations

from pathlib import Path
import json
import os
import socket
import sqlite3
import subprocess

import pytest
from agent_os_contracts import (
    CapabilityGrantStatus,
    MandateTaskLinkCommand,
    MandateTaskLinkRevocationCommand,
    OutcomePortfolioCreateCommand,
    PrincipalIdentity,
    PrincipalRole,
    ResponsibilityWorkRoute,
    SelfDevelopmentAdmissionCommand,
    SelfDevelopmentWorkSpec,
    RunStatus,
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


def _setup(tmp_path: Path, *, database_in_workspace: bool = False):
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
    database, owner, admin = _apps(isolated if database_in_workspace else tmp_path)
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
            target_path=("packages/os_core/src/agent_os_core/selfdev_fixture.py"),
            edit_mode="agent_loop_precise",
            verifier_command="pytest",
        ),
    )
    return database, isolated, authority, execution, command


def _commitment_count(authority: AgentOSApplication) -> int:
    return len(
        authority.mandate_outcome_portfolio_store.get_view(
            "mandate:build-agent-os",
            authority.principal,
            include_resolved_help=True,
        ).commitments
    )


def _interrupt_after_link(
    *,
    authority: AgentOSApplication,
    execution: AgentOSApplication,
    workspace: Path,
    database: Path,
    command: SelfDevelopmentAdmissionCommand,
) -> str:
    with pytest.raises(RuntimeError, match="AFTER_LINKED"):
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command,
            phase_hook=lambda phase: (
                (_ for _ in ()).throw(RuntimeError(phase))
                if phase == "AFTER_LINKED"
                else None
            ),
        )
    links = authority.mandate_responsibility_store.list_links(
        "mandate:build-agent-os", authority.principal
    )
    assert len(links) == 1
    assert _commitment_count(authority) == 0
    return links[0].task_id


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
    assert (
        len(
            authority.mandate_responsibility_store.list_links(
                first.mandate_id, authority.principal
            )
        )
        == 1
    )
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
            assert (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            )
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
    assert (
        len(
            authority.mandate_outcome_portfolio_store.get_view(
                first.mandate_id, authority.principal
            ).commitments
        )
        == 1
    )


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

    (workspace / "outside\nwrite-set.py").write_text(
        "outside write set\n", encoding="utf-8"
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


def test_git_marker_symlink_is_not_an_isolated_worktree(tmp_path: Path) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    marker = workspace / ".git"
    real_marker = workspace / ".git-real"
    marker.rename(real_marker)
    marker.symlink_to(real_marker.name)

    with pytest.raises(SelfDevelopmentAdmissionError) as excinfo:
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command,
        )
    assert excinfo.value.code == "ADMISSION_WORKTREE_INVALID"
    assert "SELFDEV_WORKTREE_NOT_ISOLATED" in excinfo.value.details


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


@pytest.mark.parametrize(
    "drift",
    ("grant_budget", "grant_status", "grant_version", "policy", "provider", "correction"),
)
def test_authority_or_correction_drift_before_attach_leaves_no_commitment(
    tmp_path: Path,
    drift: str,
) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    task_id = _interrupt_after_link(
        authority=authority,
        execution=execution,
        workspace=workspace,
        database=database,
        command=command,
    )
    grant = execution.grants["workspace.run_tests"]
    if drift == "grant_budget":
        execution.grants["workspace.run_tests"] = grant.model_copy(
            update={
                "budget_limit": grant.budget_limit.model_copy(
                    update={"max_tool_calls": grant.budget_limit.max_tool_calls + 1}
                )
            }
        )
    elif drift == "grant_status":
        execution.grants["workspace.run_tests"] = grant.model_copy(
            update={"status": CapabilityGrantStatus.REVOKED}
        )
    elif drift == "grant_version":
        execution.grants["workspace.run_tests"] = grant.model_copy(
            update={"capability_version": "drifted-version"}
        )
    elif drift == "policy":
        execution.policy.policy_version = "policy-drift"
    elif drift == "provider":
        execution.provider_profile = execution.provider_profile.model_copy(
            update={"model_id": "drifted-model"}
        )
    else:
        execution.correction.correct("task", task_id, "operator correction")

    with pytest.raises(SelfDevelopmentAdmissionError) as excinfo:
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command,
        )
    assert excinfo.value.code == "ADMISSION_STATE_DRIFT"
    assert _commitment_count(authority) == 0


@pytest.mark.parametrize("target", ("workflow", "snapshot", "run"))
def test_preattach_rejects_exact_event_payload_tamper_without_commitment(
    tmp_path: Path,
    target: str,
) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    task_id = _interrupt_after_link(
        authority=authority,
        execution=execution,
        workspace=workspace,
        database=database,
        command=command,
    )
    sequence = {"workflow": 2, "snapshot": 3, "run": 4}[target]
    connection = sqlite3.connect(str(database))
    try:
        raw = connection.execute(
            "SELECT payload_json FROM task_events WHERE task_id = ? AND sequence = ?",
            (task_id, sequence),
        ).fetchone()
        assert raw is not None
        payload = json.loads(str(raw[0]))
        if target == "workflow":
            payload["workflow"]["policy_version"] = "policy-tampered"
        elif target == "snapshot":
            payload["configuration_snapshot"]["policy_version"] = "policy-tampered"
        else:
            payload["run"]["status"] = RunStatus.RUNNING.value
        connection.execute(
            "UPDATE task_events SET payload_json = ? WHERE task_id = ? AND sequence = ?",
            (json.dumps(payload), task_id, sequence),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SelfDevelopmentAdmissionError) as excinfo:
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command,
        )
    assert excinfo.value.code == "ADMISSION_STATE_DRIFT"
    assert _commitment_count(authority) == 0


def test_preattach_rejects_run_progress_without_commitment(tmp_path: Path) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    task_id = _interrupt_after_link(
        authority=authority,
        execution=execution,
        workspace=workspace,
        database=database,
        command=command,
    )
    execution.tasks.update_run_status(
        task_id,
        RunStatus.RUNNING,
        event_type=TaskEventType.RUN_RESUMED,
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
    assert _commitment_count(authority) == 0


def test_preattach_rejects_revoked_and_relinked_task_without_commitment(
    tmp_path: Path,
) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    task_id = _interrupt_after_link(
        authority=authority,
        execution=execution,
        workspace=workspace,
        database=database,
        command=command,
    )
    link = authority.mandate_responsibility_store.list_links(
        "mandate:build-agent-os", authority.principal
    )[0]
    authority.mandate_responsibility_store.revoke_link(
        MandateTaskLinkRevocationCommand(
            expected_link_digest=link.record_digest,
            reason="adversarial relink",
        ),
        "mandate:build-agent-os",
        link.link_id,
        authority.principal,
    )
    authority.mandate_responsibility_store.create_link(
        MandateTaskLinkCommand(
            task_id=task_id,
            reason=f"SELFDEV admission {command.admission_id}",
            work_route=ResponsibilityWorkRoute.SELFDEV,
            selfdev_spec=command.selfdev_spec,
        ),
        "mandate:build-agent-os",
        authority.principal,
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
    assert _commitment_count(authority) == 0
    assert execution.tasks.get_task(task_id).run is not None


@pytest.mark.parametrize("special_kind", ("fifo", "socket"))
def test_workspace_special_nodes_are_rejected(
    tmp_path: Path,
    special_kind: str,
) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    special_path = workspace / f"adversarial-{special_kind}"
    bound_socket: socket.socket | None = None
    if special_kind == "fifo":
        os.mkfifo(special_path)
    else:
        bound_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        previous_cwd = Path.cwd()
        try:
            os.chdir(workspace)
            bound_socket.bind(special_path.name)
        finally:
            os.chdir(previous_cwd)
    try:
        with pytest.raises(SelfDevelopmentAdmissionError) as excinfo:
            admit_self_development(
                app=authority,
                execution_app=execution,
                workspace=workspace,
                database=database,
                command=command,
            )
        assert excinfo.value.code == "ADMISSION_WORKTREE_INVALID"
        assert "SELFDEV_WORKSPACE_SPECIAL_NODE" in excinfo.value.details
    finally:
        if bound_socket is not None:
            bound_socket.close()


def test_real_cli_default_local_database_first_admission_and_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database, workspace, _authority, _execution, command = _setup(
        tmp_path, database_in_workspace=True
    )
    assert database == workspace / "agent-os.sqlite3"
    command_path = tmp_path / "default-local-admission.json"
    command_path.write_text(command.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("AGENT_OS_AUTHORITY_BEARER", AUTHORITY_BEARER)
    monkeypatch.setenv("AGENT_OS_PROVIDER_BASE_URL", "https://provider.invalid/v1")
    argv = [
        "agent-os",
        "--workspace",
        ".",
        "agent",
        "admit-selfdev",
        str(command_path),
    ]

    with pytest.raises(SystemExit) as first_exit:
        cli_module.main(argv)
    assert first_exit.value.code == 0
    first = json.loads(capsys.readouterr().out)
    with pytest.raises(SystemExit) as replay_exit:
        cli_module.main(argv)
    assert replay_exit.value.code == 0
    replay = json.loads(capsys.readouterr().out)
    assert first["replayed"] is False
    assert replay["replayed"] is True
    assert replay["task_id"] == first["task_id"]
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "lock" not in status
    assert {
        line[3:] for line in status.splitlines()
    } <= {"agent-os.sqlite3", "agent-os.sqlite3-shm", "agent-os.sqlite3-wal"}
