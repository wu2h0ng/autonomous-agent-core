from __future__ import annotations

from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

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
    ResponsibilityControllerBlockReason,
    ResponsibilityControllerState,
    ResponsibilityLoopController,
    ResponsibilityOrganRoute,
)
from agent_os_core.responsibility_loop import (
    HcwEvaluatorRoot,
    ResponsibilityCycleState,
    ResponsibilityLoopBinding,
    ResponsibilityLoopEffectUnknown,
    ResponsibilityLoopStaleFence,
    SQLiteResponsibilityLoopStore,
)
from agent_os_core.mandate_terminal import attach_mandate
from apps.cli.__main__ import main as cli_main
from tests.product.test_long_horizon_execution import (
    _inputs,
    _post_test_read_workflow,
    _prepare_workspace,
    _signal,
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
    loop_store.ensure_hcw_evaluator_root(
        HcwEvaluatorRoot(
            evaluator_root_id="hcw-evaluator:agent-work:v1",
            measurement_policy_digest="c" * 64,
            capture_surface="agent-cli",
            idle_cutoff_seconds=60,
        )
    )

    def execute_task(
        selected_task_id: str,
        assert_current,
        execute_effect,
    ) -> None:
        assert_current("before_existing_task")

        def effect_custody(operation_slot, intent_digest, effect):
            captured = []

            def invoke_with_receipt():
                result = effect()
                captured.append(result)
                return {
                    "receipt_id": result.receipt.receipt_id,
                    "resource_ref": (
                        f"{result.receipt.connector_id}:"
                        f"{result.receipt.idempotency_key}"
                    ),
                    "evidence_digest": content_digest(result.receipt),
                }

            execute_effect(
                operation_slot,
                intent_digest,
                invoke_with_receipt,
            )
            if not captured:
                raise ResponsibilityLoopEffectUnknown(
                    "effect requires reconciliation"
                )
            return captured[0]

        owner.run_task(
            selected_task_id,
            _inputs(),
            execution_fence=assert_current,
            effect_custody=effect_custody,
        )
        assert_current("after_existing_task")

    controller = ResponsibilityLoopController(
        responsibility_projector=admin.mandate_responsibility,
        portfolio_store=admin.mandate_outcome_portfolio_store,
        task_reader=admin.tasks,
        loop_store=loop_store,
        actor=admin.principal,
        execute_task=execute_task,
        select_route=lambda _item, _commitment: (
            ResponsibilityOrganRoute.ORDINARY_TASK
        ),
        hcw_evaluator_root_id="hcw-evaluator:agent-work:v1",
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
    assert result.hcw_receipt_digest is not None
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
    replayed_hcw = SQLiteResponsibilityLoopStore(
        database,
        clock=lambda: NOW + timedelta(seconds=1),
    ).measure_hcw(
        binding,
        cycle_id=result.cycle_id,
        evaluator_root_id="hcw-evaluator:agent-work:v1",
        measured_at=NOW + timedelta(seconds=1),
    )
    assert replayed_hcw.receipt_digest == result.hcw_receipt_digest

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


def test_selfdev_responsibility_is_typed_blocked_without_task_execution(
    tmp_path: Path,
) -> None:
    database, owner, admin, task_id, attached = _verified_responsibility(tmp_path)
    binding, loop_store, _ = _controller(database, owner, admin, tmp_path)
    execution_calls: list[str] = []
    controller = ResponsibilityLoopController(
        responsibility_projector=admin.mandate_responsibility,
        portfolio_store=admin.mandate_outcome_portfolio_store,
        task_reader=admin.tasks,
        loop_store=loop_store,
        actor=admin.principal,
        execute_task=lambda selected_task_id, *_args: execution_calls.append(
            selected_task_id
        ),
        select_route=lambda _item, _commitment: ResponsibilityOrganRoute.SELFDEV,
        hcw_evaluator_root_id="hcw-evaluator:agent-work:v1",
        clock=lambda: NOW,
    )

    result = controller.run_once(
        binding,
        process_instance_id="process:selfdev-denied",
    )

    assert result.state is ResponsibilityControllerState.BLOCKED
    assert result.organ_route is ResponsibilityOrganRoute.SELFDEV
    assert (
        result.block_reason
        is ResponsibilityControllerBlockReason.SELFDEV_ROUTE_NOT_BOUND
    )
    assert result.task_id == task_id
    assert result.commitment_record_id == attached.commitment_record_id
    assert execution_calls == []
    assert owner.tasks.current_outcome(task_id) is None
    checkpoint = loop_store.latest_checkpoint(binding)
    assert checkpoint is not None
    assert checkpoint.state is ResponsibilityCycleState.BLOCKED
    assert checkpoint.next_transition == "BIND_SELFDEV_ORGAN"


def test_process_b_finishes_cycle_after_crash_following_settlement(
    tmp_path: Path,
) -> None:
    database, owner, admin, task_id, attached = _verified_responsibility(tmp_path)
    binding, loop_store, controller = _controller(
        database,
        owner,
        admin,
        tmp_path,
    )
    original_write_checkpoint = loop_store.write_checkpoint

    class SimulatedProcessCrash(RuntimeError):
        pass

    def crash_after_settlement(*args, **kwargs):
        if kwargs.get("next_transition") == "PROJECT_RESPONSIBILITIES":
            raise SimulatedProcessCrash("process died after canonical settlement")
        return original_write_checkpoint(*args, **kwargs)

    loop_store.write_checkpoint = crash_after_settlement  # type: ignore[method-assign]
    with pytest.raises(SimulatedProcessCrash):
        controller.run_once(
            binding,
            process_instance_id="process:settle-crash-A",
        )

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
    prior = loop_store.latest_checkpoint(binding)
    assert prior is not None
    assert prior.active_commitment_record_id == attached.commitment_record_id

    recovered_store = SQLiteResponsibilityLoopStore(database, clock=lambda: NOW)
    recovered = ResponsibilityLoopController(
        responsibility_projector=admin.mandate_responsibility,
        portfolio_store=admin.mandate_outcome_portfolio_store,
        task_reader=admin.tasks,
        loop_store=recovered_store,
        actor=admin.principal,
        execute_task=lambda *_args: pytest.fail(
            "settled responsibility must not execute twice"
        ),
        select_route=lambda _item, _commitment: (
            ResponsibilityOrganRoute.ORDINARY_TASK
        ),
        hcw_evaluator_root_id="hcw-evaluator:agent-work:v1",
        clock=lambda: NOW,
    ).run_once(
        binding,
        process_instance_id="process:settle-crash-B",
    )

    assert recovered.state is ResponsibilityControllerState.SETTLED
    assert recovered.cycle_id == prior.active_cycle_id
    assert recovered.settlement_id is not None
    assert recovered.cycle_receipt_digest is not None


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


def test_run_coordinator_routes_tool_effect_through_responsibility_custody(
    tmp_path: Path,
) -> None:
    _, owner, _, task_id, _ = _verified_responsibility(
        tmp_path,
        workflow=_simple_workflow(NOW),
    )
    custody_calls: list[tuple[str, str]] = []

    def custody(operation_slot, intent_digest, effect):
        custody_calls.append((operation_slot, intent_digest))
        effect()
        raise ResponsibilityLoopEffectUnknown(
            "effect completed after responsibility takeover"
        )

    with pytest.raises(RunExecutionError, match="ResponsibilityLoopEffectUnknown"):
        owner.run_task(
            task_id,
            _inputs(),
            effect_custody=custody,
        )

    assert len(custody_calls) == 1
    assert custody_calls[0][0] == "read"
    assert len(custody_calls[0][1]) == 64
    events = owner.tasks._event_store.read(task_id)
    assert not any(
        event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED
        for event in events
    )


def test_takeover_does_not_repeat_effect_that_became_unknown_after_ttl(
    tmp_path: Path,
) -> None:
    database, owner, admin, task_id, _ = _verified_responsibility(tmp_path)

    class MutableClock:
        def __init__(self):
            self.value = NOW

        def __call__(self):
            return self.value

    clock = MutableClock()
    binding = ResponsibilityLoopBinding(
        mandate_id="mandate:build-agent-os",
        principal_id=owner.principal.principal_id,
        tenant_id=admin.principal.tenant_id,
        workspace_id=admin.principal.workspace_id,
        repository_root=str(tmp_path.resolve()),
        repository_head="a" * 40,
        correction_epoch=0,
        configuration_digest="b" * 64,
        lease_ttl_seconds=1,
    )
    loop_store = SQLiteResponsibilityLoopStore(database, clock=clock)
    effect_calls: list[str] = []

    def execute_task(selected_task_id, assert_current, execute_effect):
        assert_current("before_external_effect")

        def external_effect():
            effect_calls.append(selected_task_id)
            clock.value += timedelta(seconds=2)
            return {
                "receipt_id": "receipt:external:1",
                "resource_ref": "workspace:fixture",
                "evidence_digest": "e" * 64,
            }

        execute_effect(
            "workflow-node:external-effect",
            "d" * 64,
            external_effect,
        )

    controller = ResponsibilityLoopController(
        responsibility_projector=admin.mandate_responsibility,
        portfolio_store=admin.mandate_outcome_portfolio_store,
        task_reader=admin.tasks,
        loop_store=loop_store,
        actor=admin.principal,
        execute_task=execute_task,
        select_route=lambda _item, _commitment: (
            ResponsibilityOrganRoute.ORDINARY_TASK
        ),
        hcw_evaluator_root_id="hcw-evaluator:agent-work:v1",
        clock=clock,
    )

    with pytest.raises(ResponsibilityLoopEffectUnknown):
        controller.run_once(binding, process_instance_id="process:A")
    with pytest.raises(ResponsibilityLoopEffectUnknown):
        controller.run_once(binding, process_instance_id="process:B")

    assert effect_calls == [task_id]


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

    def no_outcome(selected_task_id: str, assert_current, _execute_effect) -> None:
        assert_current("before_no_outcome")
        execution_calls.append(selected_task_id)

    controller = ResponsibilityLoopController(
        responsibility_projector=admin.mandate_responsibility,
        portfolio_store=admin.mandate_outcome_portfolio_store,
        task_reader=admin.tasks,
        loop_store=loop_store,
        actor=admin.principal,
        execute_task=no_outcome,
        select_route=lambda _item, _commitment: (
            ResponsibilityOrganRoute.ORDINARY_TASK
        ),
        hcw_evaluator_root_id="hcw-evaluator:agent-work:v1",
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
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database, owner, admin, task_id, attached = _verified_responsibility(tmp_path)
    inputs_path = _attach_git_workspace(tmp_path, database, owner)
    task_count = len(owner.list_tasks())
    monkeypatch.setenv(
        "AGENT_OS_AUTHORITY_PRINCIPAL_ID",
        admin.principal.principal_id,
    )

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
    capsys.readouterr()

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
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["runtime"]["lease"]["owned"] is False
    assert status_payload["runtime"]["unknown_effect_count"] == 0
    assert status_payload["runtime"]["last_hcw_receipt"] is not None
    assert status_payload["wake_sources"] == [
        "HELP_RESPONSE",
        "DUE_SCHEDULE",
        "EXTERNAL_CORRECTION",
        "TYPED_OPERATOR_COMMAND",
    ]

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


def test_real_process_a_to_b_to_a_restores_one_cycle_without_terminal_json(
    tmp_path: Path,
) -> None:
    database, owner, admin, task_id, _ = _verified_responsibility(
        tmp_path,
        workflow=_simple_workflow(NOW),
    )
    inputs_path = _attach_git_workspace(tmp_path, database, owner)
    terminal_projection = tmp_path / ".agent_os" / "terminal_session.json"
    terminal_projection.unlink(missing_ok=True)
    repo_root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["AGENT_OS_AUTHORITY_PRINCIPAL_ID"] = (
        admin.principal.principal_id
    )
    environment["PYTHONPATH"] = os.pathsep.join(
        (
            str(repo_root),
            str(repo_root / "src"),
            str(repo_root / "packages" / "contracts" / "src"),
            str(repo_root / "packages" / "os_core" / "src"),
        )
    )

    def run_process(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "apps.cli",
                "--database",
                str(database),
                "--workspace",
                str(tmp_path),
                *arguments,
            ],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    process_a = run_process(
        "agent",
        "run",
        "--inputs-json",
        str(inputs_path),
        "--offline",
    )
    assert process_a.returncode == 0, process_a.stderr
    first_payload = json.loads(process_a.stdout)
    assert first_payload["terminal_state"] == "WAITING_EVENT"
    cycle_id = first_payload["cycles"][0]["cycle_id"]
    assert cycle_id is not None
    assert not terminal_projection.exists()
    help_request = (
        admin.mandate_outcome_portfolio_store.list_help_requests(
            "mandate:build-agent-os",
            admin.principal,
        )[0]
    )

    process_b = run_process(
        "agent",
        "answer",
        help_request.help_request_id,
        "--decision",
        "APPROVE",
        "--notes",
        "typed external build evidence is now available",
    )
    assert process_b.returncode == 0, process_b.stderr
    waiting_task = owner.tasks.get_task(task_id)
    assert waiting_task.run is not None
    assert waiting_task.run.wait_condition is not None
    signal = _signal(owner, task_id).model_copy(
        update={"occurred_at": waiting_task.run.wait_condition.registered_at}
    )
    owner.tasks.record_signal(task_id, signal)

    process_a_resumed = run_process(
        "agent",
        "resume",
        "--inputs-json",
        str(inputs_path),
        "--offline",
    )
    assert process_a_resumed.returncode == 0, process_a_resumed.stderr
    resumed_payload = json.loads(process_a_resumed.stdout)
    settled = next(
        cycle
        for cycle in resumed_payload["cycles"]
        if cycle["state"] == "SETTLED"
    )
    assert settled["cycle_id"] == cycle_id
    assert settled["settlement_id"] is not None
    assert settled["hcw_receipt_digest"] is not None
    assert owner.tasks.current_outcome(task_id) is not None
    assert not terminal_projection.exists()


def test_agent_run_rejects_attach_session_as_admin_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, owner, _, task_id, _ = _verified_responsibility(tmp_path)
    inputs_path = _attach_git_workspace(tmp_path, database, owner)
    monkeypatch.delenv("AGENT_OS_AUTHORITY_PRINCIPAL_ID", raising=False)

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

    assert exited.value.code == 2
    assert owner.tasks.current_outcome(task_id) is None


def test_agent_answer_and_correct_use_the_same_checkpointed_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, owner, admin, task_id, _ = _verified_responsibility(
        tmp_path,
        workflow=_simple_workflow(NOW),
    )
    inputs_path = _attach_git_workspace(tmp_path, database, owner)
    monkeypatch.setenv(
        "AGENT_OS_AUTHORITY_PRINCIPAL_ID",
        admin.principal.principal_id,
    )

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


def test_agent_run_interrupt_halts_task_checkpoints_and_exits_130(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, owner, admin, task_id, _ = _verified_responsibility(tmp_path)
    inputs_path = _attach_git_workspace(tmp_path, database, owner)
    monkeypatch.setenv(
        "AGENT_OS_AUTHORITY_PRINCIPAL_ID",
        admin.principal.principal_id,
    )

    def interrupt_run(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "agent_os_core.execution.RunCoordinator.run",
        interrupt_run,
    )
    try:
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
    except KeyboardInterrupt:
        pytest.fail("Agent Work leaked KeyboardInterrupt without recovery")
    except SystemExit as exited:
        assert exited.code == 130
    else:
        pytest.fail("Agent Work interrupt did not terminate with exit 130")

    aggregate = owner.tasks.get_task(task_id)
    assert aggregate.run is not None
    assert owner.correction.halted(
        task_id,
        aggregate.run.run_id,
        "provider",
    )
