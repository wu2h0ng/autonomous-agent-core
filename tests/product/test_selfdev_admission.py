from __future__ import annotations

from pathlib import Path
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
