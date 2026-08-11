from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_os_contracts import (
    CapabilityGrant,
    CapabilityGrantStatus,
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    ResourceBudget,
    TaskEventType,
    WorkflowGraph,
)
from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from domain_packs.data_agent.runtime import DATA_QUERY_CAPABILITY_ID


def _warehouse(tmp_path: Path) -> Path:
    path = tmp_path / "warehouse.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE orders(amount INTEGER NOT NULL)")
    connection.executemany("INSERT INTO orders(amount) VALUES (?)", [(10,), (20,)])
    connection.commit()
    connection.close()
    return path


def _grant(app: AgentOSApplication) -> CapabilityGrant:
    now = datetime.now(timezone.utc)
    return CapabilityGrant(
        grant_id="grant:data.query.safe",
        principal_id=app.principal.principal_id,
        tenant_id=app.principal.tenant_id,
        workspace_id=app.principal.workspace_id,
        capability_id=DATA_QUERY_CAPABILITY_ID,
        capability_version="1",
        max_risk_tier=0,
        budget_limit=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=30,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        status=CapabilityGrantStatus.ACTIVE,
        granted_by="tenant-admin:local",
        granted_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _active_query_task(app: AgentOSApplication) -> str:
    now = datetime.now(timezone.utc)
    task = app.create_task(
        {
            "goal_id": "goal:data-query",
            "tenant_id": app.principal.tenant_id,
            "workspace_id": app.principal.workspace_id,
            "created_by": app.principal.principal_id,
            "created_at": now,
            "statement": "query governed data",
        }
    )
    workflow = WorkflowGraph(
        schema_version="WorkflowGraph/dag_v1",
        workflow_id=f"workflow:{task.task_id}",
        version=1,
        tenant_id=app.principal.tenant_id,
        workspace_id=app.principal.workspace_id,
        created_by=app.principal.principal_id,
        created_at=now,
        policy_version="policy-1",
        evaluator_refs=("evaluator:data_agent.outcome:1",),
        nodes=(
            NodeSpec(
                node_id="data-query",
                kind=NodeKind.TOOL,
                capability=DATA_QUERY_CAPABILITY_ID,
                idempotency=IdempotencyMode.IDEMPOTENT,
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="data-query", target="done"),),
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": f"commitment:{task.task_id}",
                "task_id": task.task_id,
                "goal_id": "goal:data-query",
                "tenant_id": app.principal.tenant_id,
                "workspace_id": app.principal.workspace_id,
                "accepted_by": app.principal.principal_id,
                "accepted_at": now,
                "deliverables": ["query result"],
                "acceptance_criteria": ["evidence recorded"],
                "authority_scopes": [DATA_QUERY_CAPABILITY_ID],
                "budget": {
                    "max_cost_usd": "0",
                    "max_duration_seconds": 30,
                    "max_provider_tokens": 0,
                    "max_tool_calls": 1,
                },
                "risk_tier": 0,
                "exit_conditions": ["outcome observed"],
                "expires_at": now + timedelta(hours=1),
            },
            "workflow": workflow.model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": f"expected:{task.task_id}",
                "task_id": task.task_id,
                "tenant_id": app.principal.tenant_id,
                "workspace_id": app.principal.workspace_id,
                "evaluator_type": "data_agent.outcome",
                "evaluator_version": "1",
                "evidence_requirements": ["action receipt"],
                "failure_semantics": ["unknown effect remains unresolved"],
                "threshold": 1,
                "observation_window_seconds": 60,
                "frozen_at": now,
            },
        },
    )
    app.start_run(task.task_id)
    return task.task_id


def _post(base: str, path: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def test_data_agent_query_uses_unified_task_surface_and_server_bound_scope(
    tmp_path: Path,
) -> None:
    base_app = AgentOSApplication(
        database=tmp_path / "base.sqlite3",
        workspace=tmp_path,
    )
    app = AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
        principal=base_app.principal,
        data_agent_query_database=_warehouse(tmp_path),
        data_agent_query_grant=_grant(base_app),
    )
    task_id = _active_query_task(app)
    handler = type("DataAgentSurfaceHandler", (Handler,), {"application": app})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    payload = {
        "request_id": "request:gmv",
        "safe_query": {
            "query_id": "query:gmv",
            "metric": {
                "metric_id": "metric:gmv",
                "metric_version": "1",
                "contract_digest": "a" * 64,
            },
            "sql": "SELECT SUM(amount) AS gmv FROM orders LIMIT 100",
            "parameters_json": "{}",
            "provider_contract_id": "provider:sqlite",
        },
    }
    try:
        result = _post(
            base,
            f"/v1/tasks/{task_id}/data-agent/query:run",
            payload,
        )
        assert result["status"] == "COMPLETED"
        assert result["tenant_id"] == app.principal.tenant_id
        assert result["workspace_id"] == app.principal.workspace_id
        query_result = result["query_result"]
        assert isinstance(query_result, dict)
        assert query_result["rows_json"] == '[{"gmv":30}]'
        event_types = [event.event_type for event in app.store.read(task_id)]
        assert TaskEventType.ACTION_RECEIPT_RECORDED in event_types

        with pytest.raises(urllib.error.HTTPError) as denied:
            _post(
                base,
                f"/v1/tasks/{task_id}/data-agent/query:run",
                {**payload, "tenant_id": "tenant:attacker"},
            )
        assert denied.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
