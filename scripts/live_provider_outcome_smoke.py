from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
for _source_path in (
    _REPO_ROOT / "packages" / "contracts" / "src",
    _REPO_ROOT / "packages" / "os_core" / "src",
    _REPO_ROOT,
):
    if str(_source_path) not in sys.path:
        sys.path.insert(0, str(_source_path))

from agent_os_contracts import (  # noqa: E402
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    RunStatus,
    WorkflowGraph,
)
from agent_os_core import TASK_CONFIGURATION_CAPABILITY, WorkerInterrupted  # noqa: E402
from apps.api_server.app import AgentOSApplication  # noqa: E402


AppFactory = Callable[..., AgentOSApplication]


def _workflow(now: datetime) -> WorkflowGraph:
    nodes = (
        NodeSpec(
            node_id="read",
            kind=NodeKind.TOOL,
            capability="workspace.read",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(node_id="provider", kind=NodeKind.PROVIDER, capability="provider.chat"),
        NodeSpec(node_id="approve", kind=NodeKind.APPROVAL),
        NodeSpec(
            node_id="apply",
            kind=NodeKind.TOOL,
            capability="workspace.apply_patch",
            idempotency=IdempotencyMode.COMPENSATABLE,
        ),
        NodeSpec(
            node_id="tests",
            kind=NodeKind.TOOL,
            capability="workspace.run_tests",
            idempotency=IdempotencyMode.COMPENSATABLE,
        ),
        NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION),
        NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
    )
    return WorkflowGraph(
        schema_version="WorkflowGraph/dag_v1",
        workflow_id="workflow:live-provider-outcome-smoke",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=now,
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


def run_smoke(
    *,
    app_factory: AppFactory = AgentOSApplication,
    workspace_root: Path | None = None,
    model_id: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    workspace = workspace_root or Path(
        tempfile.mkdtemp(prefix="agent-os-live-provider-outcome-", dir="/tmp")
    )
    workspace.mkdir(parents=True, exist_ok=True)
    database = workspace / "agent-os.sqlite3"
    (workspace / "fixture.txt").write_text("before\n", encoding="utf-8")
    (workspace / "test_fixture.py").write_text(
        "def test_fixture():\n    assert open('fixture.txt').read() == 'after\\n'\n",
        encoding="utf-8",
    )

    app = app_factory(database=database, workspace=workspace)
    task = app.create_task(
        {
            "goal_id": "goal:live-provider-outcome-smoke",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": now,
            "statement": (
                "You must call workspace.apply_patch exactly once. "
                "Set fixture.txt to exactly after newline."
            ),
        }
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": "commitment:live-provider-outcome-smoke",
                "task_id": task.task_id,
                "goal_id": "goal:live-provider-outcome-smoke",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "accepted_by": "user:local",
                "accepted_at": now,
                "deliverables": ["fixture patch"],
                "acceptance_criteria": ["pytest passes"],
                "authority_scopes": [
                    "workspace:read",
                    "workspace:write",
                    TASK_CONFIGURATION_CAPABILITY,
                ],
                "budget": {
                    "max_cost_usd": "1",
                    "max_duration_seconds": 300,
                    "max_provider_tokens": 4000,
                    "max_tool_calls": 10,
                },
                "risk_tier": 1,
                "exit_conditions": ["verified"],
                "expires_at": now + timedelta(hours=1),
            },
            "workflow": _workflow(now).model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": "expected:live-provider-outcome-smoke",
                "task_id": task.task_id,
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "evaluator_type": "pytest",
                "evaluator_version": "1",
                "evidence_requirements": ["test-report"],
                "failure_semantics": ["non-zero exit"],
                "threshold": 1,
                "observation_window_seconds": 300,
                "frozen_at": now,
            },
        },
    )
    snapshot = app.seal_task_configuration(task.task_id, {})
    inputs = {
        "target_path": "fixture.txt",
        "test_command": "python3 -m pytest",
        "prompt": (
            "Call workspace.apply_patch exactly once with JSON arguments "
            'path="fixture.txt" and content="after\\n". If tool calls are '
            'unavailable, answer with exactly {"path":"fixture.txt","content":"after\\n"} '
            "and no other text."
        ),
    }
    try:
        app.run_task(
            task.task_id,
            inputs,
            stop_after_node="read",
            configuration_snapshot_id=snapshot.snapshot_id,
        )
    except WorkerInterrupted:
        pass

    waiting_app = app_factory(database=database, workspace=workspace)
    waiting = waiting_app.run_task(
        task.task_id,
        inputs,
        recover_stale_lease=True,
        configuration_snapshot_id=snapshot.snapshot_id,
    )
    waiting_status = waiting.run.status.value if waiting.run else None
    if waiting.run is None or waiting.run.status is not RunStatus.WAITING_APPROVAL:
        raise RuntimeError(f"expected WAITING_APPROVAL, got {waiting_status}")

    approver = app_factory(database=database, workspace=workspace)
    approver.record_approval(
        task.task_id,
        {"disposition": "APPROVE", "reason": "Reviewed provider patch"},
    )
    finisher = app_factory(database=database, workspace=workspace)
    result = finisher.run_task(
        task.task_id,
        inputs,
        configuration_snapshot_id=snapshot.snapshot_id,
    )
    run = result.run
    if run is None:
        raise RuntimeError("smoke run missing run")
    report = finisher.tasks.validated_test_report(task.task_id, run.run_id)
    event_counts = Counter(
        event.event_type.value for event in finisher.store.read(task.task_id)
    )
    outcome = result.observed_outcome
    task_status = result.status.value if result.status is not None else None
    run_status = run.status.value if run.status is not None else None
    outcome_status = outcome.status.value if outcome and outcome.status else None
    return {
        "workspace": str(workspace),
        "model_id": model_id or finisher.provider_profile.model_id,
        "task_id": task.task_id,
        "run_id": run.run_id,
        "snapshot_id": snapshot.snapshot_id,
        "waiting_run_status": waiting_status,
        "task_status": task_status,
        "run_status": run_status,
        "outcome_status": outcome_status,
        "outcome_gaps": list(outcome.unresolved_gaps) if outcome else None,
        "validated_report": report is not None,
        "report_artifacts": list(report.artifact_ids) if report else [],
        "file_after": (workspace / "fixture.txt").read_text(encoding="utf-8"),
        "event_counts": dict(sorted(event_counts.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the live-provider Agent OS Outcome smoke."
    )
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--model-id", default=None)
    args = parser.parse_args()
    summary = run_smoke(workspace_root=args.workspace, model_id=args.model_id)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("outcome_status") == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
