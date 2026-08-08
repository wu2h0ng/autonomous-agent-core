from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
from threading import Event, Thread

import pytest
from agent_os_contracts import (
    CapabilityGrantStatus,
    MandateTaskLinkCommand,
    MandateTaskLinkRevocationCommand,
    OutcomePortfolioCreateCommand,
    PersistentCommitment,
    PersistentCommitmentAttachCommand,
    PrincipalIdentity,
    PrincipalRole,
    ResponsibilityWorkRoute,
    SelfDevelopmentAdmissionCommand,
    SelfDevelopmentVerifierBinding,
    SelfDevelopmentWorkSpec,
    RunStatus,
    TaskEventType,
    content_digest,
)
from agent_os_core.mandate_terminal import attach_mandate
from agent_os_core.provider import DeterministicProvider
import agent_os_core.self_development_organ as selfdev_organ_module
from agent_os_core import TaskConfigurationDenied, TaskConfigurationDrift
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
        verifier_paths=("tests/product/test_selfdev_fixture.py",),
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


def _mutate_security_configuration(
    execution: AgentOSApplication,
    field: str,
) -> None:
    if field == "provider":
        execution.provider_profile = execution.provider_profile.model_copy(
            update={"model_id": "serialized-drift"}
        )
    elif field == "grant":
        grant = execution.grants["workspace.run_tests"]
        execution.grants["workspace.run_tests"] = grant.model_copy(
            update={"status": CapabilityGrantStatus.REVOKED}
        )
    else:
        execution.policy.policy_version = "serialized-drift"


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
            verifier_paths=("tests/product/test_selfdev_fixture.py",),
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


def test_admission_contract_requires_one_to_eight_product_verifier_paths() -> None:
    base = {
        "admission_id": "selfdev-admission:scoped-verifier",
        "statement": "verify one bounded product oracle",
        "deliverables": ("bounded implementation",),
        "acceptance_criteria": ("the named oracle passes",),
        "selfdev_spec": {
            "repository_head": "a" * 40,
            "isolated_branch": "codex/scoped-verifier",
            "target_path": "packages/os_core/src/agent_os_core/fixture.py",
            "edit_mode": "agent_loop_precise",
            "verifier_command": "pytest",
        },
    }

    with pytest.raises(ValueError, match="verifier_paths"):
        SelfDevelopmentAdmissionCommand.model_validate(base)

    invalid_paths = (
        (),
        tuple(f"tests/product/test_{index}.py" for index in range(9)),
        ("tests/product/test_ok.py", "tests/product/test_ok.py"),
        ("tests/product/test_ok.py", "tests/product/test_other.py -q"),
        ("tests/product/*.py",),
        ("tests/product/../product/test_ok.py",),
        ("tests/product/test_ok.py\n--collect-only",),
        ("packages/os_core/test_ok.py",),
    )
    for verifier_paths in invalid_paths:
        with pytest.raises(ValueError, match="verifier_paths"):
            SelfDevelopmentAdmissionCommand.model_validate(
                {**base, "verifier_paths": verifier_paths}
            )

    command = SelfDevelopmentAdmissionCommand.model_validate(
        {
            **base,
            "verifier_paths": (
                "tests/product/test_agent_cli_stream.py",
                "tests/product/test_selfdev_admission.py",
            ),
        }
    )
    assert command.verifier_paths == (
        "tests/product/test_agent_cli_stream.py",
        "tests/product/test_selfdev_admission.py",
    )
    noncanonical = {
        **base,
        "verifier_paths": ("tests/product/test_agent_cli_stream.py",),
        "selfdev_spec": {
            **base["selfdev_spec"],
            "verifier_command": "python -m pytest",
        },
    }
    with pytest.raises(ValueError, match="canonical pytest"):
        SelfDevelopmentAdmissionCommand.model_validate(noncanonical)


def test_admission_computes_exact_base_blob_binding_and_rejects_self_attestation(
    tmp_path: Path,
) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    caller_payload = command.model_dump(mode="json")
    caller_payload["selfdev_spec"]["verifier_bindings"] = [
        {
            "path": "tests/product/test_selfdev_fixture.py",
            "base_blob_sha256": "0" * 64,
        }
    ]
    with pytest.raises(ValueError, match="server-computed"):
        SelfDevelopmentAdmissionCommand.model_validate(caller_payload)

    receipt = admit_self_development(
        app=authority,
        execution_app=execution,
        workspace=workspace,
        database=database,
        command=command,
    )
    link = authority.mandate_responsibility_store.list_links(
        "mandate:build-agent-os", authority.principal
    )[0]
    assert link.task_id == receipt.task_id
    assert link.selfdev_spec is not None
    assert len(link.selfdev_spec.verifier_bindings) == 1
    binding = link.selfdev_spec.verifier_bindings[0]
    base_bytes = subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "show",
            f"{command.selfdev_spec.repository_head}:{binding.path}",
        ],
        check=True,
        capture_output=True,
    ).stdout
    assert binding.path == "tests/product/test_selfdev_fixture.py"
    assert binding.base_blob_sha256 == hashlib.sha256(base_bytes).hexdigest()
    assert receipt.work_spec_digest == content_digest(link.selfdev_spec)


def test_admission_runtime_rejects_constructed_self_attested_binding(
    tmp_path: Path,
) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    forged = command.model_copy(
        update={
            "selfdev_spec": command.selfdev_spec.model_copy(
                update={
                    "verifier_bindings": (
                        SelfDevelopmentVerifierBinding(
                            path="tests/product/test_selfdev_fixture.py",
                            base_blob_sha256="0" * 64,
                        ),
                    )
                }
            )
        }
    )

    with pytest.raises(
        SelfDevelopmentAdmissionError,
        match="ADMISSION_VERIFIER_INVALID",
    ):
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=forged,
        )
    assert authority.mandate_responsibility_store.list_links(
        "mandate:build-agent-os", authority.principal
    ) == ()
    assert isinstance(execution.provider, DeterministicProvider)
    assert execution.provider.decision_requests == []


@pytest.mark.parametrize("oracle_kind", ("missing", "symlink", "non_blob"))
def test_admission_rejects_verifier_that_is_not_an_unchanged_regular_base_blob(
    tmp_path: Path,
    oracle_kind: str,
) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    verifier_path = f"tests/product/test_{oracle_kind}.py"
    if oracle_kind == "symlink":
        (workspace / verifier_path).symlink_to("test_selfdev_fixture.py")
        subprocess.run(
            ["git", "-C", str(workspace), "add", verifier_path], check=True
        )
        subprocess.run(
            ["git", "-C", str(workspace), "commit", "-m", "symlink oracle"],
            check=True,
            capture_output=True,
        )
    elif oracle_kind == "non_blob":
        prior_head = command.selfdev_spec.repository_head
        subprocess.run(
            [
                "git",
                "-C",
                str(workspace),
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{prior_head},{verifier_path}",
            ],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(workspace), "commit", "-m", "gitlink oracle"],
            check=True,
            capture_output=True,
        )
        gitlink = workspace / verifier_path
        gitlink.mkdir(parents=True)
        subprocess.run(["git", "-C", str(gitlink), "init"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(gitlink), "fetch", str(workspace), prior_head],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(gitlink), "checkout", prior_head],
            check=True,
            capture_output=True,
        )
    head = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    command = command.model_copy(
        update={
            "verifier_paths": (verifier_path,),
            "selfdev_spec": command.selfdev_spec.model_copy(
                update={"repository_head": head}
            ),
        }
    )

    with pytest.raises(
        SelfDevelopmentAdmissionError,
        match="ADMISSION_VERIFIER_INVALID",
    ):
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command,
        )
    assert authority.mandate_responsibility_store.list_links(
        "mandate:build-agent-os", authority.principal
    ) == ()
    assert isinstance(execution.provider, DeterministicProvider)
    assert execution.provider.decision_requests == []


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
    with execution._selfdev_configuration_write():
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
        with execution._selfdev_configuration_write():
            execution.grants["workspace.run_tests"] = grant.model_copy(
                update={
                    "budget_limit": grant.budget_limit.model_copy(
                        update={
                            "max_tool_calls": grant.budget_limit.max_tool_calls + 1
                        }
                    )
                }
            )
    elif drift == "grant_status":
        with execution._selfdev_configuration_write():
            execution.grants["workspace.run_tests"] = grant.model_copy(
                update={"status": CapabilityGrantStatus.REVOKED}
            )
    elif drift == "grant_version":
        with execution._selfdev_configuration_write():
            execution.grants["workspace.run_tests"] = grant.model_copy(
                update={"capability_version": "drifted-version"}
            )
    elif drift == "policy":
        with execution._selfdev_configuration_write():
            execution.policy.policy_version = "policy-drift"
    elif drift == "provider":
        with execution._selfdev_configuration_write():
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


@pytest.mark.parametrize(
    "drift",
    ("run", "grant", "provider", "policy", "correction", "authority", "link"),
)
def test_serialized_attach_guard_rejects_drift_after_final_preflight(
    tmp_path: Path,
    drift: str,
) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)

    def inject_after_final_preflight(phase: str) -> None:
        if phase != "AFTER_FINAL_PREFLIGHT":
            return
        link = authority.mandate_responsibility_store.list_links(
            "mandate:build-agent-os", authority.principal
        )[0]
        task_id = link.task_id
        if drift == "run":
            execution.tasks.update_run_status(
                task_id,
                RunStatus.RUNNING,
                event_type=TaskEventType.RUN_RESUMED,
            )
        elif drift == "grant":
            grant = execution.grants["workspace.run_tests"]
            with execution._selfdev_configuration_write():
                execution.grants["workspace.run_tests"] = grant.model_copy(
                    update={"status": CapabilityGrantStatus.REVOKED}
                )
        elif drift == "provider":
            with execution._selfdev_configuration_write():
                execution.provider_profile = execution.provider_profile.model_copy(
                    update={"model_id": "post-preflight-drift"}
                )
        elif drift == "policy":
            with execution._selfdev_configuration_write():
                execution.policy.policy_version = "post-preflight-drift"
        elif drift == "correction":
            execution.correction.correct("task", task_id, "post-preflight correction")
        elif drift == "authority":
            connection = sqlite3.connect(str(database))
            try:
                connection.execute(
                    "UPDATE mandate_outcome_portfolios SET payload = ? "
                    "WHERE mandate_id = ?",
                    ("{}", "mandate:build-agent-os"),
                )
                connection.commit()
            finally:
                connection.close()
        else:
            authority.mandate_responsibility_store.revoke_link(
                MandateTaskLinkRevocationCommand(
                    expected_link_digest=link.record_digest,
                    reason="post-preflight revocation",
                ),
                "mandate:build-agent-os",
                link.link_id,
                authority.principal,
            )

    with pytest.raises(SelfDevelopmentAdmissionError) as excinfo:
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command,
            phase_hook=inject_after_final_preflight,
        )
    assert excinfo.value.code == "ADMISSION_STATE_DRIFT"
    connection = sqlite3.connect(str(database))
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM mandate_persistent_commitments"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT phase FROM selfdev_admissions_v1 "
            "WHERE mandate_id = ? AND admission_id = ?",
            ("mandate:build-agent-os", command.admission_id),
        ).fetchone() == ("LINKED",)
    finally:
        connection.close()


def test_serialized_attach_guard_holds_sqlite_write_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    store = authority.mandate_outcome_portfolio_store
    original_attach = store.attach_commitment
    guard_called = False

    def wrapped_attach(
        attach_command: PersistentCommitmentAttachCommand,
        mandate_id: str,
        actor: PrincipalIdentity,
        *,
        pre_insert_guard: Callable[[], None] | None = None,
    ) -> PersistentCommitment:
        assert pre_insert_guard is not None

        def prove_fence_after_exact_guard() -> None:
            nonlocal guard_called
            pre_insert_guard()
            guard_called = True
            contender = sqlite3.connect(str(database), timeout=0)
            try:
                with pytest.raises(
                    sqlite3.OperationalError, match="database is locked"
                ):
                    contender.execute("BEGIN IMMEDIATE")
            finally:
                contender.close()

        return original_attach(
            attach_command,
            mandate_id,
            actor,
            pre_insert_guard=prove_fence_after_exact_guard,
        )

    monkeypatch.setattr(store, "attach_commitment", wrapped_attach)
    receipt = admit_self_development(
        app=authority,
        execution_app=execution,
        workspace=workspace,
        database=database,
        command=command,
    )
    assert guard_called is True
    assert receipt.replayed is False
    assert _commitment_count(authority) == 1


@pytest.mark.parametrize("field", ("provider", "grant", "policy"))
def test_supported_configuration_writer_blocks_until_commit(
    tmp_path: Path,
    field: str,
) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)
    started = Event()
    finished = Event()
    threads: list[Thread] = []

    def mutate_with_supported_lock() -> None:
        started.set()
        with execution._selfdev_configuration_write():
            _mutate_security_configuration(execution, field)
        finished.set()

    def race_after_inner_guard(phase: str) -> None:
        if phase != "AFTER_SERIALIZED_CONFIG_GUARD":
            return
        thread = Thread(target=mutate_with_supported_lock, daemon=True)
        threads.append(thread)
        thread.start()
        assert started.wait(timeout=1)
        assert finished.wait(timeout=0.05) is False

    receipt = admit_self_development(
        app=authority,
        execution_app=execution,
        workspace=workspace,
        database=database,
        command=command,
        phase_hook=race_after_inner_guard,
    )
    assert len(threads) == 1
    threads[0].join(timeout=1)
    assert threads[0].is_alive() is False
    assert finished.is_set()
    assert receipt.replayed is False
    assert _commitment_count(authority) == 1
    task = execution.tasks.get_task(receipt.task_id)
    assert task.configuration_snapshot is not None
    snapshot = task.configuration_snapshot
    if field == "provider":
        assert snapshot.provider_profile.model_id != "serialized-drift"
        assert execution.provider_profile.model_id == "serialized-drift"
    elif field == "grant":
        sealed = next(
            grant
            for grant in snapshot.execution_grants
            if grant.capability_id == "workspace.run_tests"
        )
        assert sealed.status is CapabilityGrantStatus.ACTIVE
        assert (
            execution.grants["workspace.run_tests"].status
            is CapabilityGrantStatus.REVOKED
        )
    else:
        assert snapshot.policy_version == "policy-1"
        assert execution.policy.policy_version == "serialized-drift"
    with pytest.raises((TaskConfigurationDenied, TaskConfigurationDrift)):
        execution.task_configurations.assert_runtime_binding(
            execution.principal,
            receipt.task_id,
            snapshot.snapshot_id,
        )


@pytest.mark.parametrize("field", ("provider", "grant", "policy"))
def test_direct_post_guard_mutation_is_not_authoritative_for_admission(
    tmp_path: Path,
    field: str,
) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)

    def mutate_without_lock(phase: str) -> None:
        if phase == "AFTER_SERIALIZED_CONFIG_GUARD":
            _mutate_security_configuration(execution, field)

    receipt = admit_self_development(
        app=authority,
        execution_app=execution,
        workspace=workspace,
        database=database,
        command=command,
        phase_hook=mutate_without_lock,
    )
    task = execution.tasks.get_task(receipt.task_id)
    assert task.configuration_snapshot is not None
    snapshot = task.configuration_snapshot
    assert _commitment_count(authority) == 1
    if field == "provider":
        assert snapshot.provider_profile.model_id != "serialized-drift"
    elif field == "grant":
        assert all(
            grant.status is CapabilityGrantStatus.ACTIVE
            for grant in snapshot.execution_grants
        )
    else:
        assert snapshot.policy_version == "policy-1"
    with pytest.raises((TaskConfigurationDenied, TaskConfigurationDrift)):
        execution.task_configurations.assert_runtime_binding(
            execution.principal,
            receipt.task_id,
            snapshot.snapshot_id,
        )


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
            selfdev_spec=link.selfdev_spec,
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


def test_workspace_scan_iterator_failure_is_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, workspace, authority, execution, command = _setup(tmp_path)

    class FailingScandir:
        def __enter__(self) -> FailingScandir:
            return self

        def __exit__(
            self,
            exc_type: object,
            exc_value: object,
            traceback: object,
        ) -> bool:
            return False

        def __iter__(self) -> FailingScandir:
            return self

        def __next__(self) -> os.DirEntry[str]:
            raise OSError("iterator advance failed")

    monkeypatch.setattr(
        selfdev_organ_module.os,
        "scandir",
        lambda _path: FailingScandir(),
    )
    with pytest.raises(SelfDevelopmentAdmissionError) as excinfo:
        admit_self_development(
            app=authority,
            execution_app=execution,
            workspace=workspace,
            database=database,
            command=command,
        )
    assert excinfo.value.code == "ADMISSION_WORKTREE_INVALID"
    assert "SELFDEV_WORKSPACE_SCAN_FAILED" in excinfo.value.details


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
