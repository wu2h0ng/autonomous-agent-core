from __future__ import annotations

import json
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from agent_os_contracts import (
    EdgeSpec,
    NodeKind,
    NodeSpec,
    RunStatus,
    TaskEventType,
    WorkflowGraph,
)
from agent_os_core import DeterministicProvider


class ProviderHandler(BaseHTTPRequestHandler):
    seen_authorization = ""

    def do_POST(self) -> None:
        type(self).seen_authorization = self.headers.get("Authorization", "")
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        payload = json.dumps(
            {
                "id": "response:check",
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def _request_json(
    base: str, path: str, method: str = "GET", body: dict | None = None
) -> dict:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": f"test:{path}:{method}",
        },
        method=method,
    )
    with urllib.request.urlopen(request) as response:
        value = json.loads(response.read())
    assert isinstance(value, dict)
    return value


def test_http_api_and_workspace_use_application_path(tmp_path) -> None:
    app = AgentOSApplication(database=tmp_path / "api.sqlite3", workspace=tmp_path)
    handler = type("TestAgentOSHandler", (Handler,), {"application": app})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    provider_server = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
    provider_thread = threading.Thread(
        target=provider_server.serve_forever, daemon=True
    )
    provider_thread.start()
    try:
        with urllib.request.urlopen(base + "/v1/health") as response:
            assert json.loads(response.read())["product"] == "Agent OS"
        payload = {
            "goal_id": "goal:http",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "statement": "inspect repository",
        }
        request = urllib.request.Request(
            base + "/v1/tasks",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": "create:http",
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            task = json.loads(response.read())
        with urllib.request.urlopen(base + "/v1/tasks/" + task["task_id"]) as response:
            loaded = json.loads(response.read())
        assert loaded["task_id"] == task["task_id"]
        assert loaded["domain_pack"]["pack_id"] == "developer-agent"
        listed = _request_json(base, "/v1/tasks")
        assert listed["tasks"][0]["task_id"] == task["task_id"]
        workspace = _request_json(base, "/v1/workspace")
        assert workspace["root"] == str(tmp_path.resolve())
        attached = _request_json(
            base, "/v1/workspace", "POST", {"path": str(tmp_path.resolve())}
        )
        assert attached["attached"] is True
        assert _request_json(base, "/v1/provider")["configured"] is False
        secret = "pm-secret-never-return"
        configured = _request_json(
            base,
            "/v1/provider",
            "POST",
            {
                "base_url": f"http://127.0.0.1:{provider_server.server_address[1]}",
                "model": "test-model",
                "api_key": secret,
            },
        )
        assert configured["connection_test"] == "PASS"
        assert configured["model_id"] == "test-model"
        assert secret not in json.dumps(configured)
        assert ProviderHandler.seen_authorization == f"Bearer {secret}"
        workflow = {
            "workflow_id": "workflow:http",
            "version": 1,
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "policy_version": "policy-1",
            "evaluator_refs": ["evaluator:pytest:1"],
            "nodes": [{"node_id": "done", "kind": "terminal"}],
            "edges": [],
        }
        request = urllib.request.Request(
            base + "/v1/workflows/validate",
            data=json.dumps(workflow).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            validated = json.loads(response.read())
        assert validated["valid"] is True
        assert len(validated["workflow_digest"]) == 64
        with urllib.request.urlopen(
            base + "/v1/tasks/" + task["task_id"] + "/evidence"
        ) as response:
            assert json.loads(response.read())["evidence"] == []
        with urllib.request.urlopen(base + "/") as response:
            page = response.read().decode()
        assert "Agent OS" in page
        assert "Patch content" not in page
        with urllib.request.urlopen(base + "/preview-zh") as response:
            preview = response.read().decode()
            assert response.headers["Content-Type"] == "text/html; charset=utf-8"
        assert '<html lang="zh-CN">' in preview
        assert "Agent OS" in preview
        assert "空间" in preview
        assert "任务" in preview
        assert "上下文" in preview
        assert "计划" in preview
        assert "运行" in preview
        assert "成果" in preview
        assert "知识" in preview
        assert "个人空间" in preview
        assert "开发空间" in preview
        assert "组织空间" in preview
        assert "Ask" in preview
        assert "Work" in preview
        assert "场景预设" in preview
        assert 'data-testid="workspace-switcher"' in preview
        assert 'data-testid="interaction-mode"' in preview
        assert 'data-testid="scene-preset"' in preview
        assert 'data-action="switch-workspace"' in preview
        assert 'data-action="switch-mode"' in preview
        assert 'data-action="change-preset"' in preview
        assert "fetch(" not in preview
        assert '"/v1/' not in preview
        assert 'data-testid="task-search"' in preview
        assert 'data-testid="context-bar"' in preview
        assert 'data-testid="scene-stage-rail"' in preview
        assert 'data-testid="scene-metrics"' in preview
        assert 'data-testid="scene-graph"' in preview
        assert 'data-testid="evidence-table"' in preview
        assert 'data-testid="agent-topology"' in preview
        assert 'data-testid="environment-status"' in preview
        assert 'data-testid="event-timeline"' in preview
        assert 'data-testid="approval-card"' in preview
        assert 'data-testid="command-bar"' in preview
        assert 'data-testid="language-menu"' in preview
        assert 'aria-label="主导航"' in preview
        assert 'aria-live="polite"' in preview
        assert 'data-action="create-task"' in preview
        assert 'data-action="switch-locale"' in preview
        assert 'data-action="pause-run"' in preview
        assert 'data-action="correct-run"' in preview
        assert 'data-action="inspect-evidence"' in preview
        assert 'data-action="approve-action"' in preview
        assert 'data-action="reject-action"' in preview
        assert 'data-action="promote-to-work"' in preview
        assert 'data-scene-source="fixture"' in preview
        assert "componentRegistry" in preview
        for locale in ("zh-CN", "zh-TW", "en", "ja", "ko", "es", "fr", "de"):
            assert f'data-locale="{locale}"' in preview
    finally:
        provider_server.shutdown()
        provider_server.server_close()
        server.shutdown()
        server.server_close()


def _waiting_task(app: AgentOSApplication, suffix: str) -> tuple[str, WorkflowGraph]:
    now = datetime.now(timezone.utc)
    workflow = WorkflowGraph(
        workflow_id=f"workflow:http-wait:{suffix}",
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
                wait_correlation_key=f"build:{suffix}",
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="wait", target="done"),),
        max_replans=1,
    )
    task = app.create_task(
        {
            "goal_id": f"goal:http-wait:{suffix}",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": now,
            "statement": f"wait for build {suffix}",
        }
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": f"commitment:http-wait:{suffix}",
                "task_id": task.task_id,
                "goal_id": f"goal:http-wait:{suffix}",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "accepted_by": "user:local",
                "accepted_at": now,
                "deliverables": ["build signal"],
                "acceptance_criteria": ["signal recorded"],
                "authority_scopes": ["workspace:read"],
                "budget": {
                    "max_cost_usd": "1",
                    "max_duration_seconds": 300,
                    "max_provider_tokens": 100,
                    "max_tool_calls": 5,
                },
                "risk_tier": 1,
                "exit_conditions": ["signal"],
                "expires_at": now + timedelta(hours=1),
            },
            "workflow": workflow.model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": f"expected:http-wait:{suffix}",
                "task_id": task.task_id,
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "evaluator_type": "pytest",
                "evaluator_version": "1",
                "evidence_requirements": ["signal"],
                "failure_semantics": ["missing signal"],
                "threshold": 1,
                "observation_window_seconds": 60,
                "frozen_at": now,
            },
        },
    )
    waiting = app.run_task(task.task_id)
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_EVENT
    return task.task_id, workflow


def test_http_long_horizon_commands_share_application_path(tmp_path) -> None:
    app = AgentOSApplication(database=tmp_path / "api-long.sqlite3", workspace=tmp_path)
    app.provider = DeterministicProvider()
    app.provider_configured = True
    signal_task_id, _ = _waiting_task(app, "signal")
    replan_task_id, current = _waiting_task(app, "replan")
    failed_task_id, _ = _waiting_task(app, "compensate")
    app.tasks.update_run_status(
        failed_task_id,
        RunStatus.FAILED,
        event_type=TaskEventType.RUN_FAILED,
    )
    handler = type("TestLongAgentOSHandler", (Handler,), {"application": app})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        signalled = _request_json(
            base,
            f"/v1/tasks/{signal_task_id}/signals",
            "POST",
            {
                "signal_id": "signal:http",
                "signal_name": "build.finished",
                "correlation_key": "build:signal",
                "payload_json": '{"status":"passed"}',
                "evidence_refs": ["artifact:http-build"],
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        assert signalled["run"]["status"] == "RUNNING"
        recovery = _request_json(
            base,
            f"/v1/tasks/{signal_task_id}/recovery",
        )
        assert recovery["wait_registered_count"] == 1
        assert recovery["signal_satisfied_count"] == 1

        replanned_workflow = WorkflowGraph(
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
        replanned = _request_json(
            base,
            f"/v1/tasks/{replan_task_id}/replan",
            "POST",
            {
                "workflow": replanned_workflow.model_dump(mode="json"),
                "reason": "replace external wait",
            },
        )
        assert replanned["workflow"]["version"] == 2
        assert replanned["run"]["status"] == "PAUSED"

        app.correct_task(replan_task_id, "temporary principal halt")
        correction = _request_json(
            base,
            f"/v1/tasks/{replan_task_id}/correction/resume",
            "POST",
            {"reason": "principal reviewed and resumed correction"},
        )
        assert correction["task_id"] == replan_task_id
        assert not app.correction.halted(
            replan_task_id,
            app.tasks.get_task(replan_task_id).run.run_id,  # type: ignore[union-attr]
            "workspace.read",
        )

        compensated = _request_json(
            base,
            f"/v1/tasks/{failed_task_id}/compensate",
            "POST",
            {},
        )
        assert compensated["task_id"] == failed_task_id
    finally:
        server.shutdown()
        server.server_close()
