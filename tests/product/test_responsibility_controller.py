from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import subprocess

import pytest
from agent_os_contracts import (
    Commitment,
    ExpectedOutcome,
    MandateTaskLinkCommand,
    OutcomePortfolioCreateCommand,
    OutcomePortfolioHelpGap,
    OutcomePortfolioHelpRespondCommand,
    OutcomeStatus,
    PersistentCommitmentAttachCommand,
    PersistentCommitmentState,
    SrlHelpResponseKind,
    TaskEventType,
    content_digest,
)
from agent_os_core.errors import RunExecutionError
from agent_os_core.responsibility_controller import (
    ResponsibilityControllerState,
    ResponsibilityLoopController,
)
from agent_os_core.responsibility_loop import (
    ResponsibilityLoopBinding,
    ResponsibilityLoopStaleFence,
    SQLiteResponsibilityLoopStore,
)
from agent_os_core.mandate_terminal import attach_mandate
from apps.cli.__main__ import main as cli_main
from tests.product.test_long_horizon_execution import (
    _inputs,
    _post_test_read_workflow,
    _prepare_workspace,
    _simple_workflow,
)
from tests.product.test_mandate_observation_authorization import NOW, _apps, _command
from tests.product.test_mandate_outcome_portfolio import _budget


def _verified_responsibility(tmp_path: Path, *, workflow=None):
    _prepare_workspace(tmp_path)
    database, owner, admin = _apps(tmp_path)
    owner.provider_configured = True
    admin.authorize_mandate_observation_binding(
        "mandate:build-agent-os",
        _command(),
    )
    task = owner.create_task(
        {
            "goal_id": "goal:controller",
            "tenant_id": owner.principal.tenant_id,
            "workspace_id": owner.principal.workspace_id,
            "created_by": owner.principal.principal_id,
            "created_at": NOW,
            "statement": "Verify the linked repository responsibility",
        }
    )
    commitment = Commitment(
        commitment_id="commitment:controller",
        task_id=task.task_id,
        goal_id="goal:controller",
        tenant_id=owner.principal.tenant_id,
        workspace_id=owner.principal.workspace_id,
        accepted_by=owner.principal.principal_id,
        accepted_at=NOW,
        deliverables=("verified repository state",),
        acceptance_criteria=("pytest passes",),
        budget=_budget(),
        risk_tier=0,
        exit_conditions=("verified",),
        expires_at=NOW + timedelta(days=25),
    )
    expected = ExpectedOutcome(
        expected_outcome_id="expected:controller",
        task_id=task.task_id,
        tenant_id=owner.principal.tenant_id,
        workspace_id=owner.principal.workspace_id,
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=25 * 24 * 60 * 60,
        frozen_at=NOW,
    )
    owner.tasks.commit_task(
        task.task_id,
        commitment,
        workflow or _post_test_read_workflow(NOW),
        expected,
    )
    admin.mandate_outcome_portfolio_store.create_portfolio(
        OutcomePortfolioCreateCommand(reason="controller truth"),
        "mandate:build-agent-os",
        admin.principal,
    )
    admin.mandate_responsibility_store.create_link(
        MandateTaskLinkCommand(task_id=task.task_id, reason="controller work"),
        "mandate:build-agent-os",
        admin.principal,
    )
    attached = admin.mandate_outcome_portfolio_store.attach_commitment(
        PersistentCommitmentAttachCommand(
            task_id=task.task_id,
            commitment_digest=content_digest(commitment),
            expected_outcome_digest=content_digest(expected),
            reason="persist until verified",
        ),
        "mandate:build-agent-os",
        admin.principal,
    )
    return database, owner, admin, task.task_id, attached


def _controller(database, owner, admin, tmp_path: Path):
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

    def execute_task(selected_task_id: str, assert_current) -> None:
        assert_current("before_existing_task")
        owner.run_task(selected_task_id, _inputs())
        assert_current("after_existing_task")

    controller = ResponsibilityLoopController(
        responsibility_projector=admin.mandate_responsibility,
        portfolio_store=admin.mandate_outcome_portfolio_store,
        task_reader=admin.tasks,
        loop_store=loop_store,
        actor=admin.principal,
        execute_task=execute_task,
        clock=lambda: NOW,
    )
    return binding, loop_store, controller


def _attach_git_workspace(tmp_path: Path, database, owner) -> Path:
    attach_mandate(
        workspace=tmp_path,
        database=database,
        mandate_id="mandate:build-agent-os",
        environment_binding_id="binding:data-agent-report:v1",
        principal_id=owner.principal.principal_id,
        tenant_id=owner.principal.tenant_id,
        workspace_id=owner.principal.workspace_id,
        evaluated_at=NOW,
    )
    inputs_path = tmp_path / "responsibility-inputs.json"
    inputs_path.write_text(json.dumps(_inputs()), encoding="utf-8")
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "agent@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Agent Test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "add",
            "fixture.txt",
            "test_fixture.py",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "fixture"],
        check=True,
        capture_output=True,
    )
    return inputs_path


def test_controller_executes_selected_linked_task_without_opening_chat_task(
    tmp_path: Path,
) -> None:
    database, owner, admin, task_id, attached = _verified_responsibility(tmp_path)
    task_count = len(owner.list_tasks())

    def forbidden_chat(*_args, **_kwargs):
        raise AssertionError("responsibility work must not create a chat Task")

    owner.open_chat_session = forbidden_chat  # type: ignore[method-assign]
    binding, loop_store, controller = _controller(
        database, owner, admin, tmp_path
    )
    result = controller.run_once(
        binding,
        process_instance_id="process:controller-A",
    )

    assert result.state is ResponsibilityControllerState.SETTLED
    assert result.task_id == task_id
    assert result.commitment_record_id == attached.commitment_record_id
    assert result.settlement_id is not None
    assert result.cycle_receipt_digest is not None
    assert len(owner.list_tasks()) == task_count
    outcome = owner.tasks.current_outcome(task_id)
    assert outcome is not None
    assert outcome.status is OutcomeStatus.VERIFIED
    portfolio = admin.mandate_outcome_portfolio_store.get_view(
        binding.mandate_id,
        admin.principal,
    )
    settled = next(
        item
        for item in portfolio.commitments
        if item.commitment_record_id == attached.commitment_record_id
    )
    assert settled.state is PersistentCommitmentState.SETTLED_MET
    checkpoint = loop_store.latest_checkpoint(binding)
    assert checkpoint is not None
    assert checkpoint.active_cycle_id == result.cycle_id
    assert checkpoint.active_commitment_record_id == attached.commitment_record_id

    restarted = controller.run_once(
        binding,
        process_instance_id="process:controller-B",
    )
    assert restarted.state is ResponsibilityControllerState.WAITING_EVENT
    assert restarted.cycle_id is None
    restarted_checkpoint = loop_store.latest_checkpoint(binding)
    assert restarted_checkpoint is not None
    assert restarted_checkpoint.checkpoint_digest == restarted.checkpoint_digest


def test_controller_records_not_met_without_promoting_it_to_met(
    tmp_path: Path,
) -> None:
    database, owner, admin, task_id, attached = _verified_responsibility(tmp_path)
    (tmp_path / "test_fixture.py").write_text(
        "def test_fixture():\n    assert False, 'frozen failure'\n",
        encoding="utf-8",
    )
    binding, _, controller = _controller(database, owner, admin, tmp_path)

    result = controller.run_once(
        binding,
        process_instance_id="process:not-met",
    )

    assert result.state is ResponsibilityControllerState.SETTLED
    outcome = owner.tasks.current_outcome(task_id)
    assert outcome is not None
    assert outcome.status is OutcomeStatus.NOT_MET
    portfolio = admin.mandate_outcome_portfolio_store.get_view(
        binding.mandate_id,
        admin.principal,
    )
    settled = next(
        item
        for item in portfolio.commitments
        if item.commitment_record_id == attached.commitment_record_id
    )
    assert settled.state is PersistentCommitmentState.SETTLED_NOT_MET


def test_run_coordinator_stale_responsibility_fence_blocks_tool_effect(
    tmp_path: Path,
) -> None:
    database, owner, _, task_id, _ = _verified_responsibility(
        tmp_path,
        workflow=_simple_workflow(NOW),
    )
    phases: list[str] = []

    def assert_current(phase: str) -> None:
        phases.append(phase)
        if phase == "before_tool_effect":
            raise ResponsibilityLoopStaleFence("Process B owns the loop")

    with pytest.raises(RunExecutionError, match="ResponsibilityLoopStaleFence"):
        owner.run_task(
            task_id,
            _inputs(),
            execution_fence=assert_current,
        )

    assert "before_run_execution" in phases
    assert "before_tool_effect" in phases
    events = owner.tasks._event_store.read(task_id)
    assert not any(
        event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED
        for event in events
    )
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    assert database.exists()


def test_missing_outcome_emits_typed_help_without_unauthorized_work(
    tmp_path: Path,
) -> None:
    database, owner, admin, task_id, _ = _verified_responsibility(tmp_path)
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
    execution_calls: list[str] = []

    def no_outcome(selected_task_id: str, assert_current) -> None:
        assert_current("before_no_outcome")
        execution_calls.append(selected_task_id)

    controller = ResponsibilityLoopController(
        responsibility_projector=admin.mandate_responsibility,
        portfolio_store=admin.mandate_outcome_portfolio_store,
        task_reader=admin.tasks,
        loop_store=loop_store,
        actor=admin.principal,
        execute_task=no_outcome,
        clock=lambda: NOW,
    )

    result = controller.run_once(
        binding,
        process_instance_id="process:missing-outcome",
    )

    assert result.state is ResponsibilityControllerState.WAITING_EVENT
    assert result.help_request_id is not None
    waiting_checkpoint = loop_store.latest_checkpoint(binding)
    assert waiting_checkpoint is not None
    assert waiting_checkpoint.active_help_request_id == result.help_request_id
    assert execution_calls == [task_id]
    aggregate = owner.tasks.get_task(task_id)
    assert aggregate.run is None
    assert aggregate.observed_outcome is None
    help_requests = admin.mandate_outcome_portfolio_store.list_help_requests(
        binding.mandate_id,
        admin.principal,
    )
    assert len(help_requests) == 1
    assert help_requests[0].help_request_id == result.help_request_id
    assert (
        help_requests[0].gap_kind
        is OutcomePortfolioHelpGap.MISSING_OBSERVED_OUTCOME
    )

    still_waiting = controller.run_once(
        binding,
        process_instance_id="process:still-waiting",
    )
    assert still_waiting.state is ResponsibilityControllerState.WAITING_EVENT
    assert still_waiting.cycle_id == result.cycle_id
    assert execution_calls == [task_id]

    admin.mandate_outcome_portfolio_store.respond_help_request(
        OutcomePortfolioHelpRespondCommand(
            response_kind=SrlHelpResponseKind.OPERATOR_DECISION,
            decision="APPROVE",
            notes="run the already committed verifier",
        ),
        binding.mandate_id,
        result.help_request_id,
        admin.principal,
    )
    _, _, resumed_controller = _controller(database, owner, admin, tmp_path)
    resumed = resumed_controller.run_once(
        binding,
        process_instance_id="process:help-resumed",
    )
    assert resumed.state is ResponsibilityControllerState.SETTLED
    assert resumed.cycle_id == result.cycle_id
    outcome = owner.tasks.current_outcome(task_id)
    assert outcome is not None
    assert outcome.status is OutcomeStatus.VERIFIED


def test_agent_run_uses_canonical_responsibility_instead_of_chat_task(
    tmp_path: Path,
) -> None:
    database, owner, admin, task_id, attached = _verified_responsibility(tmp_path)
    inputs_path = _attach_git_workspace(tmp_path, database, owner)
    task_count = len(owner.list_tasks())

    with pytest.raises(SystemExit) as exited:
        cli_main(
            [
                "agent-os",
                "--database",
                str(database),
                "--workspace",
                str(tmp_path),
                "agent",
                "run",
                "--inputs-json",
                str(inputs_path),
                "--offline",
            ]
        )

    assert exited.value.code == 0
    assert len(owner.list_tasks()) == task_count
    portfolio = admin.mandate_outcome_portfolio_store.get_view(
        "mandate:build-agent-os",
        admin.principal,
    )
    settled = next(
        item
        for item in portfolio.commitments
        if item.commitment_record_id == attached.commitment_record_id
    )
    assert settled.task_id == task_id
    assert settled.state is PersistentCommitmentState.SETTLED_MET

    with pytest.raises(SystemExit) as status_exit:
        cli_main(
            [
                "agent-os",
                "--database",
                str(database),
                "--workspace",
                str(tmp_path),
                "agent",
                "status",
            ]
        )
    assert status_exit.value.code == 0

    with pytest.raises(SystemExit) as resume_exit:
        cli_main(
            [
                "agent-os",
                "--database",
                str(database),
                "--workspace",
                str(tmp_path),
                "agent",
                "resume",
                "--inputs-json",
                str(inputs_path),
                "--offline",
            ]
        )
    assert resume_exit.value.code == 0
    assert len(owner.list_tasks()) == task_count


def test_agent_answer_and_correct_use_the_same_checkpointed_cycle(
    tmp_path: Path,
) -> None:
    database, owner, admin, task_id, _ = _verified_responsibility(
        tmp_path,
        workflow=_simple_workflow(NOW),
    )
    inputs_path = _attach_git_workspace(tmp_path, database, owner)

    with pytest.raises(SystemExit) as run_exit:
        cli_main(
            [
                "agent-os",
                "--database",
                str(database),
                "--workspace",
                str(tmp_path),
                "agent",
                "run",
                "--inputs-json",
                str(inputs_path),
                "--offline",
            ]
        )
    assert run_exit.value.code == 0
    open_help = admin.mandate_outcome_portfolio_store.list_help_requests(
        "mandate:build-agent-os",
        admin.principal,
    )
    assert len(open_help) == 1
    help_request_id = open_help[0].help_request_id

    with pytest.raises(SystemExit) as answer_exit:
        cli_main(
            [
                "agent-os",
                "--database",
                str(database),
                "--workspace",
                str(tmp_path),
                "agent",
                "answer",
                help_request_id,
                "--decision",
                "MORE_INFO",
                "--notes",
                "wait for the external build signal",
            ]
        )
    assert answer_exit.value.code == 0
    resolved = admin.mandate_outcome_portfolio_store.list_help_requests(
        "mandate:build-agent-os",
        admin.principal,
        include_resolved=True,
    )
    assert resolved[0].response is not None
    assert resolved[0].response.decision == "MORE_INFO"

    with pytest.raises(SystemExit) as correct_exit:
        cli_main(
            [
                "agent-os",
                "--database",
                str(database),
                "--workspace",
                str(tmp_path),
                "agent",
                "correct",
                "founder stopped the active responsibility",
            ]
        )
    assert correct_exit.value.code == 0
    aggregate = owner.tasks.get_task(task_id)
    assert aggregate.run is not None
    assert owner.correction.halted(task_id, aggregate.run.run_id, "provider")
