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
    EdgeSpec,
    ExpectedOutcome,
    IdempotencyMode,
    MandateTaskLinkCommand,
    OutcomePortfolioCreateCommand,
    OutcomePortfolioHelpGap,
    OutcomePortfolioHelpRespondCommand,
    OutcomeStatus,
    NodeKind,
    NodeSpec,
    PersistentCommitmentAttachCommand,
    PersistentCommitmentState,
    ResponsibilityWorkRoute,
    SelfDevelopmentWorkSpec,
    SrlHelpResponseKind,
    TaskEventType,
    ProviderToolProposal,
    WorkflowGraph,
    content_digest,
)
from agent_os_core.errors import RunExecutionError
from agent_os_core import DeterministicProvider
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
from agent_os_core.self_development_organ import SelfDevelopmentOrganBlocked
from agent_os_core.responsibility_surface import (
    ResponsibilitySurfaceError,
    answer_responsibility_help,
    build_responsibility_surface_context,
    run_responsibility_work,
)
from agent_os_core import responsibility_surface
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

AUTHORITY_BEARER = "test-only-agent-work-authority-bearer"


def _verified_responsibility(
    tmp_path: Path,
    *,
    workflow=None,
    work_route: ResponsibilityWorkRoute = ResponsibilityWorkRoute.ORDINARY_TASK,
    selfdev_spec: SelfDevelopmentWorkSpec | None = None,
):
    _prepare_workspace(tmp_path)
    if work_route is ResponsibilityWorkRoute.SELFDEV:
        product_tests = tmp_path / "tests" / "product"
        product_tests.mkdir(parents=True, exist_ok=True)
        (product_tests / "test_selfdev_fixture.py").write_text(
            "def test_selfdev_fixture():\n    assert True\n",
            encoding="utf-8",
        )
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
        OutcomePortfolioCreateCommand(
            reason="controller truth",
            authority_credential_digest=content_digest(
                {"agent_work_authority_bearer": AUTHORITY_BEARER}
            ),
        ),
        "mandate:build-agent-os",
        admin.principal,
    )
    admin.mandate_responsibility_store.create_link(
        MandateTaskLinkCommand(
            task_id=task.task_id,
            reason="controller work",
            work_route=work_route,
            selfdev_spec=(
                selfdev_spec
                or SelfDevelopmentWorkSpec(
                    repository_head="a" * 40,
                    isolated_branch="codex/selfdev-controller-test",
                    target_path="tests/product/test_selfdev_fixture.py",
                    verifier_command="pytest",
                )
                if work_route is ResponsibilityWorkRoute.SELFDEV
                else None
            ),
        ),
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
        select_route=lambda item, _commitment: ResponsibilityOrganRoute(
            item.link.work_route.value
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
    database, owner, admin, task_id, attached = _verified_responsibility(
        tmp_path,
        work_route=ResponsibilityWorkRoute.SELFDEV,
    )
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
        select_route=lambda item, _commitment: ResponsibilityOrganRoute(
            item.link.work_route.value
        ),
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


def test_bound_selfdev_route_executes_linked_task_without_ordinary_fallback(
    tmp_path: Path,
) -> None:
    database, owner, admin, task_id, attached = _verified_responsibility(
        tmp_path,
        work_route=ResponsibilityWorkRoute.SELFDEV,
    )
    binding, loop_store, _ = _controller(database, owner, admin, tmp_path)
    ordinary_calls: list[str] = []
    selfdev_calls: list[tuple[str, SelfDevelopmentWorkSpec]] = []

    def execute_selfdev(
        selected_task_id: str,
        spec: SelfDevelopmentWorkSpec,
        assert_current,
        _execute_effect,
    ) -> None:
        selfdev_calls.append((selected_task_id, spec))
        assert_current("before_selfdev_test_execution")
        owner.run_task(
            selected_task_id,
            {
                "target_path": spec.target_path,
                "test_command": spec.verifier_command,
            },
            execution_fence=assert_current,
        )

    controller = ResponsibilityLoopController(
        responsibility_projector=admin.mandate_responsibility,
        portfolio_store=admin.mandate_outcome_portfolio_store,
        task_reader=admin.tasks,
        loop_store=loop_store,
        actor=admin.principal,
        execute_task=lambda selected_task_id, *_args: ordinary_calls.append(
            selected_task_id
        ),
        execute_selfdev=execute_selfdev,
        select_route=lambda item, _commitment: ResponsibilityOrganRoute(
            item.link.work_route.value
        ),
        hcw_evaluator_root_id="hcw-evaluator:agent-work:v1",
        clock=lambda: NOW,
    )

    result = controller.run_once(
        binding,
        process_instance_id="process:selfdev-bound",
    )

    assert result.state is ResponsibilityControllerState.SETTLED
    assert result.organ_route is ResponsibilityOrganRoute.SELFDEV
    assert result.task_id == task_id
    assert result.commitment_record_id == attached.commitment_record_id
    assert ordinary_calls == []
    assert selfdev_calls == [
        (
            task_id,
            SelfDevelopmentWorkSpec(
                repository_head="a" * 40,
                isolated_branch="codex/selfdev-controller-test",
                target_path="tests/product/test_selfdev_fixture.py",
                verifier_command="pytest",
            ),
        )
    ]
    outcome = owner.tasks.current_outcome(task_id)
    assert outcome is not None
    assert outcome.status is OutcomeStatus.VERIFIED


def _linked_worktree(tmp_path: Path) -> tuple[Path, str, str]:
    source = tmp_path / "source"
    isolated = tmp_path / "isolated"
    source.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(source)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "agent@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "config", "user.name", "Agent Test"],
        check=True,
    )
    target = source / "tests" / "product" / "test_selfdev_fixture.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_selfdev_fixture():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(source), "commit", "-m", "fixture"],
        check=True,
        capture_output=True,
    )
    branch = "codex/selfdev-organ-test"
    subprocess.run(
        ["git", "-C", str(source), "worktree", "add", "-b", branch, str(isolated)],
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "-C", str(isolated), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return isolated, branch, head


def _selfdev_patch_workflow() -> WorkflowGraph:
    nodes = (
        NodeSpec(
            node_id="read",
            kind=NodeKind.TOOL,
            capability="workspace.read",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(
            node_id="provider",
            kind=NodeKind.PROVIDER,
            capability="provider.chat",
        ),
        NodeSpec(node_id="approve", kind=NodeKind.APPROVAL),
        NodeSpec(
            node_id="apply",
            kind=NodeKind.TOOL,
            capability="workspace.apply_patch",
            risk_tier=2,
            idempotency=IdempotencyMode.COMPENSATABLE,
        ),
        NodeSpec(
            node_id="tests",
            kind=NodeKind.TOOL,
            capability="workspace.run_tests",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION),
        NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
    )
    return WorkflowGraph(
        workflow_id="workflow:selfdev-organ-test",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=nodes,
        edges=tuple(
            EdgeSpec(source=source, target=target)
            for source, target in (
                ("read", "provider"),
                ("provider", "approve"),
                ("approve", "apply"),
                ("apply", "tests"),
                ("tests", "evaluate"),
                ("evaluate", "done"),
            )
        ),
    )


def test_selfdev_organ_admits_exact_linked_worktree_and_derives_inputs(
    tmp_path: Path,
) -> None:
    isolated, branch, head = _linked_worktree(tmp_path)
    calls: list[tuple[str, dict[str, object]]] = []

    def execute_task(task_id, inputs, assert_current, _execute_effect) -> None:
        assert_current("inside_selfdev_executor")
        calls.append((task_id, inputs))

    organ = responsibility_surface.SelfDevelopmentOrgan(
        workspace=isolated,
        execute_task=execute_task,
    )
    spec = SelfDevelopmentWorkSpec(
        repository_head=head,
        isolated_branch=branch,
        target_path="tests/product/test_selfdev_fixture.py",
        verifier_command="pytest",
    )

    organ(
        "task:selfdev",
        spec,
        lambda _phase: None,
        lambda *_args: None,
    )

    assert calls == [
        (
            "task:selfdev",
            {
                "target_path": "tests/product/test_selfdev_fixture.py",
                "test_command": "pytest",
                "selfdev_execution_envelope": {
                    "repository_head": head,
                    "isolated_branch": branch,
                    "allowed_write_path": "tests/product/test_selfdev_fixture.py",
                    "verifier_command": "pytest",
                    "rollback_strategy": "compensate_task",
                    "prohibited_effects": (
                        "main",
                        "master",
                        "release",
                        "commit",
                        "push",
                        "merge",
                    ),
                },
            },
        )
    ]


@pytest.mark.parametrize("drift", ["head", "branch", "primary_checkout"])
def test_selfdev_organ_rejects_unproven_isolation_before_execution(
    tmp_path: Path,
    drift: str,
) -> None:
    isolated, branch, head = _linked_worktree(tmp_path)
    workspace = isolated
    expected_branch = branch
    expected_head = head
    if drift == "head":
        expected_head = "f" * 40
    elif drift == "branch":
        expected_branch = "codex/other-selfdev-branch"
    else:
        workspace = tmp_path / "source"
        expected_branch = "codex/primary-checkout"
        subprocess.run(
            ["git", "-C", str(workspace), "branch", "-m", expected_branch],
            check=True,
        )
    calls: list[str] = []
    organ = responsibility_surface.SelfDevelopmentOrgan(
        workspace=workspace,
        execute_task=lambda task_id, *_args: calls.append(task_id),
    )
    spec = SelfDevelopmentWorkSpec(
        repository_head=expected_head,
        isolated_branch=expected_branch,
        target_path="tests/product/test_selfdev_fixture.py",
        verifier_command="pytest",
    )

    with pytest.raises(
        SelfDevelopmentOrganBlocked,
        match="SELFDEV_",
    ):
        organ("task:selfdev", spec, lambda _phase: None, lambda *_args: None)

    assert calls == []


def test_real_agent_surface_runs_bound_selfdev_organ_on_same_linked_task(
    tmp_path: Path,
) -> None:
    isolated, branch, head = _linked_worktree(tmp_path)
    spec = SelfDevelopmentWorkSpec(
        repository_head=head,
        isolated_branch=branch,
        target_path="tests/product/test_selfdev_fixture.py",
        verifier_command="pytest",
    )
    database, owner, admin, task_id, _ = _verified_responsibility(
        isolated,
        work_route=ResponsibilityWorkRoute.SELFDEV,
        selfdev_spec=spec,
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
    task_count = len(owner.list_tasks())

    payload = run_responsibility_work(
        app=admin,
        execution_app=owner,
        workspace=isolated,
        database=database,
        inputs={"target_path": "forbidden-user-override.py"},
        resume=False,
    )

    assert payload["terminal_state"] == "WAITING_EVENT"
    assert payload["cycles"][0]["organ_route"] == "SELFDEV"
    assert payload["cycles"][0]["state"] == "SETTLED"
    assert payload["cycles"][0]["task_id"] == task_id
    assert len(owner.list_tasks()) == task_count
    outcome = owner.tasks.current_outcome(task_id)
    assert outcome is not None
    assert outcome.status is OutcomeStatus.VERIFIED


def test_real_agent_surface_returns_typed_block_on_selfdev_head_drift(
    tmp_path: Path,
) -> None:
    isolated, branch, _head = _linked_worktree(tmp_path)
    spec = SelfDevelopmentWorkSpec(
        repository_head="f" * 40,
        isolated_branch=branch,
        target_path="tests/product/test_selfdev_fixture.py",
        verifier_command="pytest",
    )
    database, owner, admin, task_id, _ = _verified_responsibility(
        isolated,
        work_route=ResponsibilityWorkRoute.SELFDEV,
        selfdev_spec=spec,
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

    payload = run_responsibility_work(
        app=admin,
        execution_app=owner,
        workspace=isolated,
        database=database,
        inputs={},
        resume=False,
    )

    assert payload["terminal_state"] == "BLOCKED"
    assert payload["cycles"][0]["block_reason"] == "SELFDEV_HEAD_MISMATCH"
    assert owner.tasks.current_outcome(task_id) is None


def test_selfdev_approval_help_resumes_exact_task_and_rolls_back_not_met_patch(
    tmp_path: Path,
) -> None:
    isolated, branch, head = _linked_worktree(tmp_path)
    target = isolated / "tests" / "product" / "test_selfdev_fixture.py"
    preimage = target.read_text(encoding="utf-8")
    spec = SelfDevelopmentWorkSpec(
        repository_head=head,
        isolated_branch=branch,
        target_path="tests/product/test_selfdev_fixture.py",
        verifier_command="pytest",
    )
    database, owner, admin, task_id, _ = _verified_responsibility(
        isolated,
        workflow=_selfdev_patch_workflow(),
        work_route=ResponsibilityWorkRoute.SELFDEV,
        selfdev_spec=spec,
    )
    provider = DeterministicProvider(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:selfdev-not-met",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {
                        "path": spec.target_path,
                        "content": "def test_selfdev_fixture():\n    assert False\n",
                    }
                ),
            ),
        )
    )
    owner.provider = provider
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
    task_count = len(owner.list_tasks())

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
    help_request = next(
        item
        for item in admin.mandate_outcome_portfolio_store.list_help_requests(
            "mandate:build-agent-os",
            admin.principal,
        )
        if item.help_request_id == help_id
    )
    assert help_request.gap_kind.value == "PENDING_ACTION_APPROVAL"
    assert target.read_text(encoding="utf-8") == preimage
    provider_prompt = provider.requests[0].messages[0].content
    assert "SELFDEV persisted execution envelope" in provider_prompt
    assert f"Exact base HEAD: {head}" in provider_prompt
    assert f"Isolated branch: {branch}" in provider_prompt
    assert f"Allowed write path: {spec.target_path}" in provider_prompt
    assert "Verifier: pytest" in provider_prompt
    assert "main, master, release, commit, push, merge" in provider_prompt
    assert "Acceptance criteria:" in provider_prompt
    assert "pytest passes" in provider_prompt

    admin.record_approval(
        task_id,
        {"disposition": "APPROVE", "reason": "external exact approval"},
    )
    with pytest.raises(
        ResponsibilitySurfaceError,
        match="SELFDEV_APPROVAL_DECISION_CONFLICT",
    ):
        answer_responsibility_help(
            app=admin,
            execution_app=owner,
            workspace=isolated,
            database=database,
            help_request_id=help_id,
            payload={
                "response_kind": SrlHelpResponseKind.OPERATOR_DECISION.value,
                "decision": "REJECT",
                "notes": "must not contradict the durable approval",
            },
        )

    answer = answer_responsibility_help(
        app=admin,
        execution_app=owner,
        workspace=isolated,
        database=database,
        help_request_id=help_id,
        payload={
            "response_kind": SrlHelpResponseKind.OPERATOR_DECISION.value,
            "decision": "APPROVE",
            "notes": "approve exact shadow patch only",
        },
    )
    assert answer["task_approval_recorded"] is True
    assert owner.tasks.get_task(task_id).approval is not None
    assert owner.tasks.get_task(task_id).approval.actor_id == admin.principal.principal_id

    completed = run_responsibility_work(
        app=admin,
        execution_app=owner,
        workspace=isolated,
        database=database,
        inputs={},
        resume=True,
    )

    assert completed["cycles"][0]["state"] == "SETTLED"
    outcome = owner.tasks.current_outcome(task_id)
    assert outcome is not None
    assert outcome.status is OutcomeStatus.NOT_MET
    assert target.read_text(encoding="utf-8") == preimage
    assert len(owner.list_tasks()) == task_count


def test_selfdev_organ_rejects_task_owner_self_approval(
    tmp_path: Path,
) -> None:
    isolated, branch, head = _linked_worktree(tmp_path)
    target = isolated / "tests" / "product" / "test_selfdev_fixture.py"
    preimage = target.read_text(encoding="utf-8")
    spec = SelfDevelopmentWorkSpec(
        repository_head=head,
        isolated_branch=branch,
        target_path="tests/product/test_selfdev_fixture.py",
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
                proposal_id="proposal:selfdev-self-approval",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {"path": spec.target_path, "content": preimage + "# changed\n"}
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
    owner.record_approval(
        task_id,
        {"disposition": "APPROVE", "reason": "invalid self approval"},
    )
    with pytest.raises(
        ResponsibilitySurfaceError,
        match="SELFDEV_APPROVAL_AUTHORITY_INVALID",
    ):
        answer_responsibility_help(
            app=admin,
            execution_app=owner,
            workspace=isolated,
            database=database,
            help_request_id=waiting["cycles"][0]["help_request_id"],
            payload={
                "response_kind": SrlHelpResponseKind.OPERATOR_DECISION.value,
                "decision": "APPROVE",
                "notes": "must not inherit owner approval",
            },
        )
    assert target.read_text(encoding="utf-8") == preimage


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


@pytest.mark.parametrize(
    "crash_method",
    (
        "seal_cycle_receipt",
        "bind_cycle_settlement",
        "measure_hcw",
    ),
)
def test_process_b_recovers_each_post_settlement_finalization_crash(
    tmp_path: Path,
    crash_method: str,
) -> None:
    database, owner, admin, task_id, attached = _verified_responsibility(tmp_path)
    binding, loop_store, controller = _controller(
        database,
        owner,
        admin,
        tmp_path,
    )
    original = getattr(loop_store, crash_method)

    class SimulatedProcessCrash(RuntimeError):
        pass

    def crash_after_stage(*args, **kwargs):
        original(*args, **kwargs)
        raise SimulatedProcessCrash(f"process died after {crash_method}")

    setattr(loop_store, crash_method, crash_after_stage)
    with pytest.raises(SimulatedProcessCrash):
        controller.run_once(
            binding,
            process_instance_id=f"process:{crash_method}:A",
        )

    prior = SQLiteResponsibilityLoopStore(
        database,
        clock=lambda: NOW,
    ).latest_checkpoint(binding)
    assert prior is not None
    assert prior.active_cycle_id is not None
    recovered_store = SQLiteResponsibilityLoopStore(database, clock=lambda: NOW)
    recovered = ResponsibilityLoopController(
        responsibility_projector=admin.mandate_responsibility,
        portfolio_store=admin.mandate_outcome_portfolio_store,
        task_reader=admin.tasks,
        loop_store=recovered_store,
        actor=admin.principal,
        execute_task=lambda *_args: pytest.fail(
            "post-settlement recovery must not execute the Task twice"
        ),
        select_route=lambda item, _commitment: ResponsibilityOrganRoute(
            item.link.work_route.value
        ),
        hcw_evaluator_root_id="hcw-evaluator:agent-work:v1",
        clock=lambda: NOW,
    ).run_once(
        binding,
        process_instance_id=f"process:{crash_method}:B",
    )

    assert recovered.state in {
        ResponsibilityControllerState.SETTLED,
        ResponsibilityControllerState.WAITING_EVENT,
    }
    receipt = recovered_store.get_cycle_receipt(
        binding,
        prior.active_cycle_id,
    )
    assert receipt is not None
    replayed_hcw = recovered_store.measure_hcw(
        binding,
        cycle_id=prior.active_cycle_id,
        evaluator_root_id="hcw-evaluator:agent-work:v1",
        measured_at=NOW + timedelta(seconds=1),
    )
    assert replayed_hcw.receipt_digest
    portfolio = admin.mandate_outcome_portfolio_store.get_view(
        binding.mandate_id,
        admin.principal,
    )
    matching = [
        settlement
        for settlement in portfolio.settlements
        if settlement.commitment_record_id == attached.commitment_record_id
    ]
    assert len(matching) == 1
    assert owner.tasks.current_outcome(task_id) is not None


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


def test_status_marks_applied_effect_without_task_receipt_as_unreconciled(
    tmp_path: Path,
) -> None:
    database, owner, admin, task_id, _ = _verified_responsibility(tmp_path)
    binding, loop_store, _ = _controller(database, owner, admin, tmp_path)
    lease = loop_store.acquire_lease(
        binding,
        process_instance_id="process:effect-before-task-receipt",
        now=NOW,
    )
    loop_store.execute_effect(
        binding,
        lease,
        cycle_id="cycle:applied-before-task-receipt",
        task_id=task_id,
        operation_slot="read",
        intent_digest="d" * 64,
        effect=lambda: {
            "receipt_id": "receipt:applied-before-task-receipt",
            "resource_ref": "workspace.read:read-key",
            "evidence_digest": "e" * 64,
        },
        executed_at=NOW,
    )
    loop_store.release_lease(binding, lease, released_at=NOW)

    runtime = loop_store.runtime_status(binding)

    assert runtime["unknown_effect_count"] == 1
    assert runtime["applied_without_task_receipt_count"] == 1


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
        "AGENT_OS_AUTHORITY_BEARER",
        AUTHORITY_BEARER,
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
    assert status_payload["wake_capability"] == {
        "resident_watcher_active": False,
        "automatic_sources": [],
        "manual_resume_triggers": [
            "HELP_RESPONSE",
            "EXTERNAL_SIGNAL",
            "TYPED_OPERATOR_COMMAND",
        ],
    }

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


def test_agent_work_surface_rejects_selfdev_on_primary_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database, owner, admin, task_id, _ = _verified_responsibility(
        tmp_path,
        work_route=ResponsibilityWorkRoute.SELFDEV,
    )
    inputs_path = _attach_git_workspace(tmp_path, database, owner)
    monkeypatch.setenv(
        "AGENT_OS_AUTHORITY_BEARER",
        AUTHORITY_BEARER,
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
    payload = json.loads(capsys.readouterr().out)
    assert payload["terminal_state"] == "BLOCKED"
    assert payload["cycles"][0]["organ_route"] == "SELFDEV"
    assert payload["cycles"][0]["block_reason"] == "SELFDEV_WORKTREE_NOT_ISOLATED"
    assert owner.tasks.current_outcome(task_id) is None


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
    environment["AGENT_OS_AUTHORITY_BEARER"] = AUTHORITY_BEARER
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


def test_agent_run_rejects_missing_authority_bearer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, owner, _, task_id, _ = _verified_responsibility(tmp_path)
    inputs_path = _attach_git_workspace(tmp_path, database, owner)
    monkeypatch.delenv("AGENT_OS_AUTHORITY_BEARER", raising=False)

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


def test_agent_run_rejects_forged_admin_id_with_wrong_bearer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, owner, admin, task_id, _ = _verified_responsibility(tmp_path)
    inputs_path = _attach_git_workspace(tmp_path, database, owner)
    monkeypatch.setenv(
        "AGENT_OS_AUTHORITY_PRINCIPAL_ID",
        admin.principal.principal_id,
    )
    monkeypatch.setenv("AGENT_OS_AUTHORITY_BEARER", "wrong-bearer")

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
        "AGENT_OS_AUTHORITY_BEARER",
        AUTHORITY_BEARER,
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
        "AGENT_OS_AUTHORITY_BEARER",
        AUTHORITY_BEARER,
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


def test_agent_run_interrupt_inside_tool_effect_checkpoints_and_exits_130(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, owner, admin, task_id, _ = _verified_responsibility(tmp_path)
    inputs_path = _attach_git_workspace(tmp_path, database, owner)
    monkeypatch.setenv(
        "AGENT_OS_AUTHORITY_BEARER",
        AUTHORITY_BEARER,
    )

    def interrupt_effect(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "agent_os_core.capability.CapabilityBroker.invoke",
        interrupt_effect,
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

    assert exited.value.code == 130
    aggregate = owner.tasks.get_task(task_id)
    assert aggregate.run is not None
    assert owner.correction.halted(
        task_id,
        aggregate.run.run_id,
        "provider",
    )
    context = build_responsibility_surface_context(
        app=admin,
        execution_app=owner,
        workspace=tmp_path,
        database=database,
    )
    runtime = context.loop_store.runtime_status(context.binding)
    assert runtime["unknown_effect_count"] == 1
