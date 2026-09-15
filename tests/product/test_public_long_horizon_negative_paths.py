from __future__ import annotations

import inspect
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_os_contracts import (
    EdgeSpec,
    NodeKind,
    NodeSpec,
    PrincipalIdentity,
    PrincipalRole,
    RunStatus,
    TaskEventType,
    WorkflowGraph,
)
from agent_os_core import DeterministicProvider
from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler


def _app_with_waiting_task(
    tmp_path: Path,
    *,
    db_name: str = "test.sqlite3",
    wait_timeout_seconds: int = 300,
) -> tuple[AgentOSApplication, str, datetime]:
    db_path = tmp_path / db_name
    app = AgentOSApplication(database=db_path, workspace=tmp_path)
    app.provider = DeterministicProvider()
    app.provider_configured = True
    now = datetime.now(timezone.utc)

    workflow = WorkflowGraph(
        workflow_id="workflow:neg",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=now,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=(
            NodeSpec(
                node_id="wait",
                kind=NodeKind.WAIT_EVENT,
                wait_signal_name="build.finished",
                wait_correlation_key="build:neg",
                timeout_seconds=wait_timeout_seconds,
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="wait", target="done"),),
        max_replans=1,
    )

    task = app.create_task(
        {
            "goal_id": "goal:neg",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": now.isoformat(),
            "statement": "negative path test",
        }
    )

    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": "commitment:neg",
                "task_id": task.task_id,
                "goal_id": "goal:neg",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "accepted_by": "user:local",
                "accepted_at": now.isoformat(),
                "deliverables": ["test"],
                "acceptance_criteria": ["passed"],
                "authority_scopes": ["workspace:read"],
                "budget": {
                    "max_cost_usd": "1",
                    "max_duration_seconds": 3600,
                    "max_provider_tokens": 100,
                    "max_tool_calls": 5,
                },
                "risk_tier": 1,
                "exit_conditions": ["test"],
                "expires_at": (now + timedelta(hours=1)).isoformat(),
            },
            "workflow": workflow.model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": "expected:neg",
                "task_id": task.task_id,
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "evaluator_type": "pytest",
                "evaluator_version": "1",
                "evidence_requirements": ["signal"],
                "failure_semantics": ["missing"],
                "threshold": 1,
                "observation_window_seconds": 60,
                "frozen_at": now.isoformat(),
            },
        },
    )

    waiting = app.run_task(task.task_id)
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_EVENT
    return app, task.task_id, now


def _serve(app: AgentOSApplication):
    handler = type("_HttpHandler", (Handler,), {"application": app})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _post(base: str, path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _post400(base: str, path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
        return json.loads(exc.read().decode())


def _principal(
    app: AgentOSApplication,
    *,
    principal_id: str,
    role: PrincipalRole = PrincipalRole.PRINCIPAL,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
) -> PrincipalIdentity:
    return PrincipalIdentity(
        principal_id=principal_id,
        tenant_id=tenant_id or app.principal.tenant_id,
        workspace_id=workspace_id or app.principal.workspace_id,
        role=role,
        authenticated_at=datetime.now(timezone.utc),
    )


def _correction_audit_state(
    app: AgentOSApplication,
    task_id: str,
) -> tuple[int, bool, int]:
    run_id = "run:correction-audit"
    snapshot = app.correction.snapshot(task_id, run_id, "capability:audit")
    correction_event_count = sum(
        event.event_type is TaskEventType.CORRECTION_WRITTEN
        for event in app.store.read(task_id)
    )
    return (
        snapshot.task_epoch,
        app.correction.halted(task_id, run_id, "capability:audit"),
        correction_event_count,
    )


def _assert_rejected_without_correction_mutation(
    app: AgentOSApplication,
    task_id: str,
    invoke: Callable[[], object],
    expected_error: type[Exception],
) -> None:
    before = _correction_audit_state(app, task_id)
    caught: Exception | None = None
    try:
        invoke()
    except Exception as exc:  # noqa: BLE001 - asserted public error is captured below
        caught = exc
    after = _correction_audit_state(app, task_id)

    assert after == before, (
        "rejected correction command mutated epoch, halt, or audit event"
    )
    assert isinstance(caught, expected_error), (
        f"expected {expected_error.__name__}, got "
        f"{type(caught).__name__ if caught is not None else 'no exception'}"
    )


@pytest.mark.parametrize("command", ("correct_task", "resume_correction"))
@pytest.mark.parametrize(
    ("actor", "expected_error"),
    (
        ("worker", PermissionError),
        ("wrong-tenant", PermissionError),
        ("wrong-workspace", PermissionError),
    ),
)
def test_public_correction_rejects_role_and_scope_before_mutation(
    tmp_path: Path,
    command: str,
    actor: str,
    expected_error: type[Exception],
) -> None:
    app, task_id, _ = _app_with_waiting_task(
        tmp_path,
        db_name=f"correction-{command}-{actor}.sqlite3",
    )
    principals = {
        "worker": _principal(
            app,
            principal_id="worker:untrusted",
            role=PrincipalRole.WORKER,
        ),
        "wrong-tenant": _principal(
            app,
            principal_id="user:wrong-tenant",
            tenant_id="tenant:other",
        ),
        "wrong-workspace": _principal(
            app,
            principal_id="user:wrong-workspace",
            workspace_id="workspace:other",
        ),
    }

    _assert_rejected_without_correction_mutation(
        app,
        task_id,
        lambda: getattr(app, command)(
            task_id,
            "unauthorized correction",
            principal=principals[actor],
        ),
        expected_error,
    )


@pytest.mark.parametrize("command", ("correct_task", "resume_correction"))
def test_public_correction_rejects_missing_commitment_and_run_before_mutation(
    tmp_path: Path,
    command: str,
) -> None:
    app = AgentOSApplication(
        database=tmp_path / f"no-run-{command}.sqlite3", workspace=tmp_path
    )
    now = datetime.now(timezone.utc)
    task = app.create_task(
        {
            "goal_id": f"goal:no-run:{command}",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": now.isoformat(),
            "statement": "correction without commitment or run",
        }
    )

    _assert_rejected_without_correction_mutation(
        app,
        task.task_id,
        lambda: getattr(app, command)(task.task_id, "must not mutate"),
        ValueError,
    )


@pytest.mark.parametrize("command", ("correct_task", "resume_correction"))
def test_public_correction_rejects_blank_normalized_reason_before_mutation(
    tmp_path: Path,
    command: str,
) -> None:
    app, task_id, _ = _app_with_waiting_task(
        tmp_path,
        db_name=f"blank-reason-{command}.sqlite3",
    )

    _assert_rejected_without_correction_mutation(
        app,
        task_id,
        lambda: getattr(app, command)(task_id, "  \t\n  "),
        ValueError,
    )


@pytest.mark.parametrize("command", ("correct_task", "resume_correction"))
@pytest.mark.parametrize("terminal_status", (RunStatus.SUCCEEDED, RunStatus.CANCELLED))
def test_public_correction_rejects_terminal_run_before_mutation(
    tmp_path: Path,
    command: str,
    terminal_status: RunStatus,
) -> None:
    app, task_id, _ = _app_with_waiting_task(
        tmp_path,
        db_name=f"terminal-{terminal_status.value}-{command}.sqlite3",
    )
    if terminal_status is RunStatus.SUCCEEDED:
        app.tasks.update_run_status(
            task_id,
            RunStatus.FAILED,
            event_type=TaskEventType.RUN_FAILED,
        )
        app.tasks.update_run_status(
            task_id,
            RunStatus.RUNNING,
            event_type=TaskEventType.RUN_RESUMED,
        )
        terminal_event = TaskEventType.RUN_SUCCEEDED
    else:
        terminal_event = TaskEventType.RUN_CANCELLED
    app.tasks.update_run_status(
        task_id,
        terminal_status,
        event_type=terminal_event,
    )

    _assert_rejected_without_correction_mutation(
        app,
        task_id,
        lambda: getattr(app, command)(task_id, "terminal run must stay immutable"),
        ValueError,
    )


def test_correct_task_declares_and_accepts_optional_keyword_only_principal(
    tmp_path: Path,
) -> None:
    app, task_id, _ = _app_with_waiting_task(
        tmp_path, db_name="correct-principal.sqlite3"
    )
    parameter = inspect.signature(app.correct_task).parameters.get("principal")

    assert parameter is not None
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None
    corrected = app.correct_task(
        task_id,
        "principal-authored halt",
        principal=app.principal,
    )
    assert corrected.task_id == task_id


def test_tenant_admin_can_halt_and_resume_failed_run_with_exact_audit_identity(
    tmp_path: Path,
) -> None:
    app, task_id, _ = _app_with_waiting_task(
        tmp_path,
        db_name="tenant-admin-failed-run.sqlite3",
    )
    failed = app.tasks.update_run_status(
        task_id,
        RunStatus.FAILED,
        event_type=TaskEventType.RUN_FAILED,
    )
    assert failed.run is not None
    run_id = failed.run.run_id
    admin = _principal(
        app,
        principal_id="admin:custom-c7",
        role=PrincipalRole.TENANT_ADMIN,
    )

    corrected = app.correct_task(
        task_id,
        "  tenant admin halt  ",
        principal=admin,
    )
    assert corrected.run is not None
    assert corrected.run.status is RunStatus.FAILED
    assert _correction_audit_state(app, task_id) == (1, True, 1)

    resumed = app.resume_correction(
        task_id,
        "  tenant admin resume  ",
        principal=admin,
    )
    assert resumed.run is not None
    assert resumed.run.status is RunStatus.FAILED
    assert _correction_audit_state(app, task_id) == (2, False, 2)

    correction_events = [
        event
        for event in app.store.read(task_id)
        if event.event_type is TaskEventType.CORRECTION_WRITTEN
    ]
    assert [
        (event.decoded_payload(), event.correlation_id) for event in correction_events
    ] == [
        (
            {
                "scope": "TASK",
                "epoch": 1,
                "halted": True,
                "reason": "tenant admin halt",
                "written_by": admin.principal_id,
            },
            run_id,
        ),
        (
            {
                "scope": "TASK",
                "epoch": 2,
                "halted": False,
                "reason": "tenant admin resume",
                "written_by": admin.principal_id,
            },
            run_id,
        ),
    ]


class TestHTTPPublicNegativePaths:
    def test_signal_replay_idempotent_via_http(self, tmp_path: Path) -> None:
        app, task_id, _ = _app_with_waiting_task(tmp_path, db_name="http-idem.sqlite3")
        server, base = _serve(app)
        try:
            signal = {
                "signal_id": "signal:http-idem",
                "signal_name": "build.finished",
                "correlation_key": "build:neg",
                "payload_json": '{"status":"passed"}',
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }

            first = _post(base, f"/v1/tasks/{task_id}/signals", signal)
            assert first["run"]["status"] == "RUNNING"

            second = _post(base, f"/v1/tasks/{task_id}/signals", signal)
            assert second["sequence"] == first["sequence"]

            events = app.store.read(task_id)
            assert (
                sum(
                    1
                    for e in events
                    if e.event_type is TaskEventType.EXTERNAL_SIGNAL_RECORDED
                )
                == 1
            )
            assert (
                sum(1 for e in events if e.event_type is TaskEventType.WAIT_SATISFIED)
                == 1
            )
        finally:
            server.shutdown()

    def test_spoofed_signal_scope_returns_400_zero_new_events(
        self,
        tmp_path: Path,
    ) -> None:
        app, task_id, _ = _app_with_waiting_task(tmp_path, db_name="http-scope.sqlite3")
        before_count = len(app.store.read(task_id))
        server, base = _serve(app)
        try:
            signal = {
                "signal_id": "signal:http-spoof",
                "signal_name": "build.finished",
                "correlation_key": "build:neg",
                "payload_json": '{"status":"hacked"}',
                "tenant_id": "tenant:evil",
                "workspace_id": "workspace:evil",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }

            err = _post400(base, f"/v1/tasks/{task_id}/signals", signal)
            assert err["error"] == "SignalMismatchError"
            assert len(app.store.read(task_id)) == before_count

            run = app.tasks.get_task(task_id).run
            assert run is not None
            assert run.status is RunStatus.WAITING_EVENT
        finally:
            server.shutdown()

    def test_spoofed_run_id_and_correlation_key_returns_400(
        self,
        tmp_path: Path,
    ) -> None:
        app, task_id, _ = _app_with_waiting_task(
            tmp_path, db_name="http-scope2.sqlite3"
        )
        before_count = len(app.store.read(task_id))
        server, base = _serve(app)
        try:
            stale_run = _post400(
                base,
                f"/v1/tasks/{task_id}/signals",
                {
                    "signal_id": "signal:http-stale",
                    "signal_name": "build.finished",
                    "correlation_key": "build:neg",
                    "run_id": "run:stale",
                    "payload_json": '{"status":"hacked"}',
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            assert stale_run["error"] == "SignalMismatchError"
            assert "run" in stale_run["message"].lower()

            wrong_corr = _post400(
                base,
                f"/v1/tasks/{task_id}/signals",
                {
                    "signal_id": "signal:http-corr",
                    "signal_name": "build.finished",
                    "correlation_key": "build:evil",
                    "payload_json": '{"status":"hacked"}',
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            assert wrong_corr["error"] == "SignalMismatchError"

            assert len(app.store.read(task_id)) == before_count
            run = app.tasks.get_task(task_id).run
            assert run is not None
            assert run.status is RunStatus.WAITING_EVENT
        finally:
            server.shutdown()

    def test_late_signal_after_expired_wait_returns_400_stays_failed(
        self,
        tmp_path: Path,
    ) -> None:
        app, task_id, _ = _app_with_waiting_task(tmp_path, db_name="http-late.sqlite3")

        app.tasks.expire_wait(task_id)
        after_expire = len(app.store.read(task_id))
        expired = app.tasks.get_task(task_id)
        assert expired.run is not None
        assert expired.run.status is RunStatus.FAILED

        server, base = _serve(app)
        try:
            err = _post400(
                base,
                f"/v1/tasks/{task_id}/signals",
                {
                    "signal_id": "signal:http-late",
                    "signal_name": "build.finished",
                    "correlation_key": "build:neg",
                    "payload_json": '{"status":"too late"}',
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            assert err["error"] == "SignalMismatchError"
            assert "no active wait" in err["message"]

            assert len(app.store.read(task_id)) == after_expire
            final = app.tasks.get_task(task_id)
            assert final.run is not None
            assert final.run.status is RunStatus.FAILED

            events = app.store.read(task_id)
            event_types = [e.event_type for e in events]
            assert TaskEventType.WAIT_TIMED_OUT in event_types
            assert TaskEventType.WAIT_SATISFIED not in event_types
            assert TaskEventType.EXTERNAL_SIGNAL_RECORDED not in event_types
        finally:
            server.shutdown()

    def test_replan_budget_exhaustion_returns_400_no_extra_rebound(
        self,
        tmp_path: Path,
    ) -> None:
        app, task_id, now = _app_with_waiting_task(
            tmp_path,
            db_name="http-budget.sqlite3",
        )
        current = app.tasks.get_task(task_id).workflow
        assert current is not None

        server, base = _serve(app)
        try:
            v2 = WorkflowGraph(
                workflow_id=current.workflow_id,
                version=2,
                tenant_id=current.tenant_id,
                workspace_id=current.workspace_id,
                created_by=current.created_by,
                created_at=current.created_at,
                policy_version=current.policy_version,
                evaluator_refs=current.evaluator_refs,
                nodes=(NodeSpec(node_id="done", kind=NodeKind.TERMINAL),),
                edges=(),
                max_replans=1,
            )

            first = _post(
                base,
                f"/v1/tasks/{task_id}/replan",
                {"workflow": v2.model_dump(mode="json"), "reason": "first replan"},
            )
            assert first["workflow"]["version"] == 2
            assert first["run"]["replan_count"] == 1
            assert first["run"]["status"] == "PAUSED"

            v3 = v2.model_copy(update={"version": 3})
            err = _post400(
                base,
                f"/v1/tasks/{task_id}/replan",
                {"workflow": v3.model_dump(mode="json"), "reason": "second replan"},
            )
            assert err["error"] == "ReplanRejectedError"
            assert "budget" in err["message"].lower()

            events = app.store.read(task_id)
            assert (
                sum(1 for e in events if e.event_type is TaskEventType.RUN_PLAN_REBOUND)
                == 1
            )
        finally:
            server.shutdown()

    def test_replan_scope_denial_returns_400_zero_rebound(
        self,
        tmp_path: Path,
    ) -> None:
        app, task_id, now = _app_with_waiting_task(
            tmp_path,
            db_name="http-replan-scope.sqlite3",
        )
        current = app.tasks.get_task(task_id).workflow
        assert current is not None

        server, base = _serve(app)
        try:
            v2_wrong_tenant = WorkflowGraph(
                workflow_id=current.workflow_id,
                version=2,
                tenant_id="tenant:evil",
                workspace_id=current.workspace_id,
                created_by=current.created_by,
                created_at=current.created_at,
                policy_version=current.policy_version,
                evaluator_refs=current.evaluator_refs,
                nodes=(NodeSpec(node_id="done", kind=NodeKind.TERMINAL),),
                edges=(),
                max_replans=1,
            )
            err = _post400(
                base,
                f"/v1/tasks/{task_id}/replan",
                {
                    "workflow": v2_wrong_tenant.model_dump(mode="json"),
                    "reason": "cross-tenant attack",
                },
            )
            assert err["error"] == "ReplanRejectedError"
            assert "scope" in err["message"].lower()

            assert not any(
                e.event_type is TaskEventType.RUN_PLAN_REBOUND
                for e in app.store.read(task_id)
            )
            run = app.tasks.get_task(task_id).run
            assert run is not None
            assert run.replan_count == 0
        finally:
            server.shutdown()
