from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from agent_os_contracts import (
    ObservedOutcome,
    OutcomePortfolioCreateCommand,
    OutcomePortfolioHelpGap,
    OutcomeStatus,
    PersistentCommitmentState,
    PrincipalRole,
    ProviderToolProposal,
    ResponsibilityWorkRoute,
    SelfDevelopmentWorkSpec,
    SrlHelpResponseKind,
    content_digest,
)
from agent_os_contracts.outcome_portfolio import help_class_for_gap
from agent_os_contracts.srl_help import HelpClass
from agent_os_core import (
    DeterministicProvider,
    MandateOutcomePortfolioConflict,
)
from agent_os_core.mandate_terminal import (
    MandateTerminalError,
    attach_mandate,
    load_attach_session,
)
from agent_os_core.responsibility_surface import (
    ResponsibilitySurfaceError,
    answer_responsibility_help,
    resolve_agent_work_authority,
    run_responsibility_work,
)
from agent_os_core.selfdev_admission import (
    SelfDevelopmentAdmissionError,
    admit_self_development,
)
from apps.api_server.app import AgentOSApplication
from tests.product.test_mandate_observation_authorization import (
    NOW,
    _apps,
    _command,
)
from tests.product.test_responsibility_controller import (
    AUTHORITY_BEARER,
    _linked_worktree,
    _selfdev_patch_workflow,
    _verified_responsibility,
)
from tests.product.test_selfdev_admission import (
    _commitment_count,
    _setup,
)


def _authority_resolution_setup(tmp_path: Path):
    isolated, _branch, _head = _linked_worktree(tmp_path)
    database, owner, admin = _apps(tmp_path)
    admin.authorize_mandate_observation_binding(
        "mandate:build-agent-os",
        _command(),
    )
    admin.mandate_outcome_portfolio_store.create_portfolio(
        OutcomePortfolioCreateCommand(
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
    return database, isolated, owner, admin


def test_resolve_agent_work_authority_roundtrips_portfolio_without_reason(
    tmp_path: Path,
) -> None:
    database, isolated, _owner, admin = _authority_resolution_setup(tmp_path)
    session = load_attach_session(isolated)

    identity = resolve_agent_work_authority(
        database=database,
        session=session,
        bearer=AUTHORITY_BEARER,
    )

    assert identity.principal_id == admin.principal.principal_id
    assert identity.role is PrincipalRole.TENANT_ADMIN
    assert identity.tenant_id == session.tenant_id
    assert identity.workspace_id == session.workspace_id


def test_resolve_agent_work_authority_rejects_tampered_portfolio_record(
    tmp_path: Path,
) -> None:
    database, isolated, _owner, _admin = _authority_resolution_setup(tmp_path)
    session = load_attach_session(isolated)

    resolve_agent_work_authority(
        database=database,
        session=session,
        bearer=AUTHORITY_BEARER,
    )

    connection = sqlite3.connect(str(database))
    try:
        connection.execute(
            "UPDATE mandate_outcome_portfolios SET record_digest = ? "
            "WHERE mandate_id = ?",
            ("0" * 64, "mandate:build-agent-os"),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ResponsibilitySurfaceError, match="binding is invalid"):
        resolve_agent_work_authority(
            database=database,
            session=session,
            bearer=AUTHORITY_BEARER,
        )


# --- F2 (A1): atomic admission semantics -------------------------------------


@pytest.mark.parametrize("branch", ("main", "master", "release", "release/1.0"))
def test_admission_contract_rejects_main_and_release_branches(branch: str) -> None:
    with pytest.raises(ValueError, match="main/master/release"):
        SelfDevelopmentWorkSpec.model_validate(
            {
                "repository_head": "a" * 40,
                "isolated_branch": branch,
                "target_path": "packages/os_core/src/agent_os_core/selfdev_fixture.py",
                "edit_mode": "agent_loop_precise",
                "verifier_command": "pytest",
            }
        )


def test_admit_selfdev_rejects_paused_mandate_with_zero_side_effects(
    tmp_path: Path,
) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore

    SQLiteSituatedAssessmentStore(database).pause(
        "mandate:build-agent-os",
        expected_epoch=0,
        principal_id="principal:owner",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
    )

    with pytest.raises(MandateTerminalError):
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command,
        )
    assert (
        authority.mandate_responsibility_store.list_links(
            "mandate:build-agent-os", authority.principal
        )
        == ()
    )
    assert _commitment_count(authority) == 0


def test_admit_selfdev_rejects_primary_checkout_worktree(
    tmp_path: Path,
) -> None:
    database, _isolated, authority, execution, command = _setup(tmp_path)
    source = tmp_path / "source"
    attach_mandate(
        workspace=source,
        database=database,
        mandate_id="mandate:build-agent-os",
        environment_binding_id="binding:data-agent-report:v1",
        principal_id="principal:owner",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluated_at=NOW,
    )
    head = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source_command = command.model_copy(
        update={
            "selfdev_spec": command.selfdev_spec.model_copy(
                update={
                    "repository_head": head,
                    "isolated_branch": "codex/primary-checkout-rejected",
                }
            )
        }
    )
    with pytest.raises(SelfDevelopmentAdmissionError) as excinfo:
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=source,
            database=database,
            command=source_command,
        )
    assert excinfo.value.code == "ADMISSION_WORKTREE_INVALID"


# --- F3 (A3): HelpRequest generator wiring -----------------------------------


def test_help_class_for_gap_covers_all_three_triggers() -> None:
    assert (
        help_class_for_gap(OutcomePortfolioHelpGap.PENDING_ACTION_APPROVAL)
        is HelpClass.PERMISSION
    )
    assert (
        help_class_for_gap(OutcomePortfolioHelpGap.MISSING_OBSERVED_OUTCOME)
        is HelpClass.INFORMATION
    )
    assert (
        help_class_for_gap(OutcomePortfolioHelpGap.UNDECIDABLE_OUTCOME)
        is HelpClass.INFORMATION
    )


def test_undecidable_outcome_help_fails_closed_without_unresolved_outcome(
    tmp_path: Path,
) -> None:
    database, owner, admin, task_id, attached = _verified_responsibility(tmp_path)
    store = admin.mandate_outcome_portfolio_store
    with pytest.raises(MandateOutcomePortfolioConflict, match="UNRESOLVED"):
        store.request_undecidable_outcome_help(
            attached.commitment_record_id,
            "mandate:build-agent-os",
            admin.principal,
        )
    assert owner.tasks.current_outcome(task_id) is None


def test_undecidable_outcome_help_emits_typed_help_via_shared_generator(
    tmp_path: Path,
) -> None:
    database, owner, admin, task_id, attached = _verified_responsibility(tmp_path)
    run = owner.tasks.start_run(task_id)
    assert run.run is not None
    expected = run.expected_outcome
    assert expected is not None
    owner.tasks.record_outcome(
        task_id,
        ObservedOutcome(
            observed_outcome_id="observed:undecidable",
            expected_outcome_id=expected.expected_outcome_id,
            task_id=task_id,
            run_id=run.run.run_id,
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            evaluator_type="pytest",
            evaluator_version="1",
            status=OutcomeStatus.UNRESOLVED,
            score=None,
            confidence=0.0,
            evidence_refs=(),
            unresolved_gaps=("verifier produced no decisive result",),
            observed_at=NOW,
        ),
    )
    help_request = admin.mandate_outcome_portfolio_store.request_undecidable_outcome_help(
        attached.commitment_record_id,
        "mandate:build-agent-os",
        admin.principal,
    )
    assert help_request.gap_kind is OutcomePortfolioHelpGap.UNDECIDABLE_OUTCOME
    assert help_request.srl_help.help_class is HelpClass.INFORMATION
    assert help_request.task_id == task_id
    assert help_request.is_open
    assert help_request.srl_help.unknowns == (
        "Task ObservedOutcome is UNRESOLVED and cannot be settled without "
        "an external decision",
    )


def test_controller_emits_undecidable_help_instead_of_settling_unresolved(
    tmp_path: Path,
) -> None:
    from agent_os_core.responsibility_controller import (
        ResponsibilityControllerState,
        ResponsibilityOrganRoute,
    )
    from agent_os_core.responsibility_loop import (
        HcwEvaluatorRoot,
        ResponsibilityLoopBinding,
        SQLiteResponsibilityLoopStore,
    )

    database, owner, admin, task_id, attached = _verified_responsibility(tmp_path)
    run = owner.tasks.start_run(task_id)
    assert run.run is not None
    expected = run.expected_outcome
    assert expected is not None
    owner.tasks.record_outcome(
        task_id,
        ObservedOutcome(
            observed_outcome_id="observed:undecidable",
            expected_outcome_id=expected.expected_outcome_id,
            task_id=task_id,
            run_id=run.run.run_id,
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            evaluator_type="pytest",
            evaluator_version="1",
            status=OutcomeStatus.UNRESOLVED,
            score=None,
            confidence=0.0,
            evidence_refs=(),
            unresolved_gaps=("no decisive result",),
            observed_at=NOW,
        ),
    )
    binding = ResponsibilityLoopBinding(
        mandate_id="mandate:build-agent-os",
        principal_id=owner.principal.principal_id,
        tenant_id=admin.principal.tenant_id,
        workspace_id=admin.principal.workspace_id,
        repository_root=str(tmp_path.resolve()),
        repository_head="a" * 40,
        correction_epoch=0,
        configuration_digest="b" * 64,
        lease_ttl_seconds=30,
    )
    loop_store = SQLiteResponsibilityLoopStore(database, clock=lambda: NOW)
    loop_store.ensure_hcw_evaluator_root(
        HcwEvaluatorRoot(
            evaluator_root_id="hcw-evaluator:agent-work:v1",
            measurement_policy_digest="c" * 64,
            capture_surface="agent-cli",
            idle_cutoff_seconds=60,
        )
    )
    from agent_os_core.responsibility_controller import ResponsibilityLoopController

    controller = ResponsibilityLoopController(
        responsibility_projector=admin.mandate_responsibility,
        portfolio_store=admin.mandate_outcome_portfolio_store,
        task_reader=admin.tasks,
        loop_store=loop_store,
        actor=admin.principal,
        execute_task=lambda *_args: pytest.fail("undecidable outcome must not execute"),
        select_route=lambda _item, _commitment: ResponsibilityOrganRoute.ORDINARY_TASK,
        hcw_evaluator_root_id="hcw-evaluator:agent-work:v1",
        clock=lambda: NOW,
    )

    result = controller.run_once(binding, process_instance_id="process:undecidable")

    assert result.state is ResponsibilityControllerState.WAITING_EVENT
    assert result.help_request_id is not None
    assert result.task_id == task_id
    assert result.settlement_id is None
    help_request = next(
        item
        for item in admin.mandate_outcome_portfolio_store.list_help_requests(
            "mandate:build-agent-os",
            admin.principal,
        )
        if item.help_request_id == result.help_request_id
    )
    assert help_request.gap_kind is OutcomePortfolioHelpGap.UNDECIDABLE_OUTCOME
    portfolio = admin.mandate_outcome_portfolio_store.get_view(
        "mandate:build-agent-os", admin.principal
    )
    assert all(
        item.state is PersistentCommitmentState.OPEN
        for item in portfolio.commitments
    )


# --- F4 (A8): restart recovery / resume --------------------------------------


def test_process_restart_preserves_responsibility_chain_and_resumes(
    tmp_path: Path,
) -> None:
    isolated, branch, head = _linked_worktree(tmp_path)
    target = (
        isolated
        / "packages"
        / "os_core"
        / "src"
        / "agent_os_core"
        / "selfdev_fixture.py"
    )
    preimage = target.read_text(encoding="utf-8")
    spec = SelfDevelopmentWorkSpec(
        repository_head=head,
        isolated_branch=branch,
        target_path="packages/os_core/src/agent_os_core/selfdev_fixture.py",
        verifier_command="pytest",
    )
    database, owner, admin, task_id, _ = _verified_responsibility(
        isolated,
        workflow=_selfdev_patch_workflow(),
        work_route=ResponsibilityWorkRoute.SELFDEV,
        selfdev_spec=spec,
    )
    owner.provider = DeterministicProvider(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:restart-not-met",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {"path": spec.target_path, "content": "VALUE = False\n"}
                ),
            ),
        )
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

    waiting = run_responsibility_work(
        app=admin,
        execution_app=owner,
        workspace=isolated,
        database=database,
        inputs={},
        resume=False,
    )
    assert waiting["terminal_state"] == "WAITING_EVENT"
    help_id = waiting["cycles"][0]["help_request_id"]

    restarted_owner = AgentOSApplication(
        database=database,
        workspace=isolated,
        principal=owner.principal,
        clock=lambda: NOW,
    )
    restarted_owner.provider_configured = True
    restarted_admin = AgentOSApplication(
        database=database,
        workspace=isolated,
        principal=admin.principal,
        clock=lambda: NOW,
    )

    restarted_task = restarted_owner.tasks.get_task(task_id)
    assert restarted_task.run is not None
    prior_run = owner.tasks.get_task(task_id).run
    assert prior_run is not None
    assert restarted_task.run.run_id == prior_run.run_id
    portfolio = restarted_admin.mandate_outcome_portfolio_store.get_view(
        "mandate:build-agent-os", restarted_admin.principal, include_resolved_help=True
    )
    assert len(portfolio.commitments) == 1
    assert all(item.state is PersistentCommitmentState.OPEN for item in portfolio.commitments)

    answer_responsibility_help(
        app=restarted_admin,
        execution_app=restarted_owner,
        workspace=isolated,
        database=database,
        help_request_id=help_id,
        payload={
            "response_kind": SrlHelpResponseKind.OPERATOR_DECISION.value,
            "decision": "APPROVE",
            "notes": "approve after process restart",
        },
    )

    completed = run_responsibility_work(
        app=restarted_admin,
        execution_app=restarted_owner,
        workspace=isolated,
        database=database,
        inputs={},
        resume=True,
    )
    assert completed["cycles"][0]["state"] == "SETTLED"
    outcome = restarted_owner.tasks.current_outcome(task_id)
    assert outcome is not None
    assert outcome.status is OutcomeStatus.NOT_MET
    assert target.read_text(encoding="utf-8") == preimage
