from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import ThreadingHTTPServer
from typing import Any, Iterator

from agent_os_contracts import (
    Commitment,
    ExpectedOutcome,
    Goal,
    NodeKind,
    NodeSpec,
    ResourceBudget,
    WorkflowGraph,
)
from agent_os_core import TASK_CONFIGURATION_CAPABILITY
from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler


NOW = datetime(2026, 7, 15, 22, 0, tzinfo=timezone.utc)


@contextmanager
def _running_server(app: AgentOSApplication) -> Iterator[str]:
    handler = type("TaskConfigurationHandler", (Handler,), {"application": app})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request_json(
    base: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    key: str = "task-configuration-http-key",
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "Idempotency-Key": key},
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as response:
            status = response.status
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        status = exc.code
        payload = json.loads(exc.read())
    assert isinstance(payload, dict)
    return status, payload


def _committed_task(app: AgentOSApplication) -> str:
    goal = Goal(
        goal_id="goal:http-configuration",
        tenant_id=app.principal.tenant_id,
        workspace_id=app.principal.workspace_id,
        created_by=app.principal.principal_id,
        created_at=NOW,
        statement="seal through closed HTTP surface",
    )
    task = app.tasks.create_task(goal)
    commitment = Commitment(
        commitment_id="commitment:http-configuration",
        task_id=task.task_id,
        goal_id=goal.goal_id,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        accepted_by=goal.created_by,
        accepted_at=NOW,
        deliverables=("result",),
        acceptance_criteria=("verified",),
        authority_scopes=(TASK_CONFIGURATION_CAPABILITY,),
        budget=ResourceBudget(
            max_cost_usd=Decimal("1"),
            max_duration_seconds=300,
            max_provider_tokens=0,
            max_tool_calls=0,
        ),
        risk_tier=1,
        exit_conditions=("done",),
        expires_at=NOW + timedelta(days=30),
    )
    workflow = WorkflowGraph(
        workflow_id="workflow:http-configuration",
        version=1,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        created_by=goal.created_by,
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=(NodeSpec(node_id="done", kind=NodeKind.TERMINAL),),
        edges=(),
    )
    expected = ExpectedOutcome(
        expected_outcome_id="outcome:http-configuration",
        task_id=task.task_id,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("NOT_MET",),
        threshold=1.0,
        observation_window_seconds=300,
        frozen_at=NOW,
    )
    app.tasks.commit_task(task.task_id, commitment, workflow, expected)
    return task.task_id


def test_http_seal_get_list_and_bound_start(tmp_path) -> None:
    app = AgentOSApplication(
        database=tmp_path / "configuration-http.sqlite3",
        workspace=tmp_path,
    )
    task_id = _committed_task(app)
    with _running_server(app) as base:
        status, sealed = _request_json(
            base,
            f"/v1/tasks/{task_id}/configuration-snapshots:seal",
            method="POST",
            body={},
        )
        assert status == 201
        snapshot_id = sealed["snapshot_id"]

        status, listed = _request_json(
            base,
            f"/v1/tasks/{task_id}/configuration-snapshots",
        )
        assert status == 200
        assert listed["configuration_snapshots"] == [sealed]

        status, loaded = _request_json(
            base,
            f"/v1/tasks/{task_id}/configuration-snapshots/{snapshot_id}",
        )
        assert status == 200
        assert loaded == sealed

        status, started = _request_json(
            base,
            f"/v1/tasks/{task_id}/start",
            method="POST",
            body={"configuration_snapshot_id": snapshot_id},
        )
        assert status == 200
        assert started["run"]["run_id"] == sealed["reserved_run_id"]
        assert started["run"]["configuration_snapshot_id"] == snapshot_id


def test_http_surface_rejects_authority_injection_and_bypasses_generic_cache(
    tmp_path,
) -> None:
    app = AgentOSApplication(
        database=tmp_path / "configuration-http-closed.sqlite3",
        workspace=tmp_path,
    )
    task_id = _committed_task(app)
    seal_path = f"/v1/tasks/{task_id}/configuration-snapshots:seal"
    with _running_server(app) as base:
        status, rejected = _request_json(
            base,
            seal_path,
            method="POST",
            body={"policy_digest": "a" * 64, "activation": True},
            key="same-key",
        )
        assert status == 400
        assert rejected["error"] in {"ValidationError", "ValueError"}

        status, sealed = _request_json(
            base,
            seal_path,
            method="POST",
            body={},
            key="same-key",
        )
        assert status == 201

        status, conflict = _request_json(
            base,
            seal_path,
            method="POST",
            body={
                "prior_selector": {
                    "candidate_task_id": "task:missing",
                    "candidate_digest": "b" * 64,
                    "prior_artifact_id": "prior:missing",
                }
            },
            key="same-key",
        )
        assert status == 409
        assert conflict["error"] == "TaskConfigurationConflict"
        assert conflict != sealed

        status, rejected_start = _request_json(
            base,
            f"/v1/tasks/{task_id}/start",
            method="POST",
            body={
                "configuration_snapshot_id": sealed["snapshot_id"],
                "configuration_snapshot_digest": sealed["snapshot_digest"],
            },
        )
        assert status == 400
        assert rejected_start["error"] == "ValueError"
