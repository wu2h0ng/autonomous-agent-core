from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    Commitment,
    EdgeSpec,
    ExpectedOutcome,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    ResourceBudget,
    TaskStatus,
    WorkflowGraph,
)
from agent_os_core import InMemoryTaskEventStore, TaskService


NOW = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)


def _nodes() -> tuple[NodeSpec, ...]:
    return (
        NodeSpec(
            node_id="inspect",
            kind=NodeKind.TOOL,
            capability="workspace.read",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(
            node_id="patch",
            kind=NodeKind.TOOL,
            capability="workspace.apply_patch",
            idempotency=IdempotencyMode.COMPENSATABLE,
        ),
        NodeSpec(node_id="verify", kind=NodeKind.EVALUATION),
        NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
    )


def _edges() -> tuple[EdgeSpec, ...]:
    return (
        EdgeSpec(source="inspect", target="patch"),
        EdgeSpec(source="patch", target="verify"),
        EdgeSpec(source="verify", target="done"),
    )


def _graph(
    *,
    nodes: tuple[NodeSpec, ...] | None = None,
    edges: tuple[EdgeSpec, ...] | None = None,
) -> WorkflowGraph:
    return WorkflowGraph(
        schema_version="WorkflowGraph/dag_v1",
        workflow_id="workflow-1",
        version=1,
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        created_by="user-1",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=nodes if nodes is not None else _nodes(),
        edges=edges if edges is not None else _edges(),
    )


def _loop_workflow() -> WorkflowGraph:
    return WorkflowGraph(
        schema_version="WorkflowGraph/dag_v1",
        workflow_id="workflow-loop",
        version=1,
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        created_by="user-1",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=(
            NodeSpec(
                node_id="retry",
                kind=NodeKind.LOOP,
                max_iterations=3,
                stop_predicate="done",
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="retry", target="done"),),
    )


@pytest.fixture
def spine0_workflow() -> WorkflowGraph:
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
    edges = tuple(
        EdgeSpec(source=source, target=target)
        for source, target in (
            ("read", "provider"),
            ("provider", "approve"),
            ("approve", "apply"),
            ("apply", "tests"),
            ("tests", "evaluate"),
            ("evaluate", "done"),
        )
    )
    return WorkflowGraph(
        schema_version="WorkflowGraph/dag_v1",
        workflow_id="workflow:developer-golden-path",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=nodes,
        edges=edges,
    )


def test_dag_v1_rejects_loop_node() -> None:
    loop_node = NodeSpec(
        node_id="retry",
        kind=NodeKind.LOOP,
        max_iterations=3,
        stop_predicate="done",
    )
    with pytest.raises(ValidationError, match="dag_v1 does not support node kind 'loop'"):
        _graph(nodes=(*_nodes(), loop_node))


def test_dag_v1_rejects_parallel_map_node() -> None:
    fanout = NodeSpec(
        node_id="fanout",
        kind=NodeKind.PARALLEL_MAP,
        max_concurrency=4,
    )
    with pytest.raises(ValidationError, match="parallel_map"):
        _graph(nodes=(*_nodes(), fanout))


def test_dag_v1_rejects_subworkflow_node() -> None:
    sub = NodeSpec(
        node_id="child",
        kind=NodeKind.SUBWORKFLOW,
        subworkflow_ref="workflow-child:1",
    )
    with pytest.raises(ValidationError, match="subworkflow"):
        _graph(nodes=(*_nodes(), sub))


def test_dag_v1_rejects_conditional_edge() -> None:
    conditional = (
        EdgeSpec(source="inspect", target="patch", condition="ctx.ready == true"),
        *_edges()[1:],
    )
    with pytest.raises(ValidationError, match="conditional edges"):
        _graph(edges=conditional)


def test_dag_v1_rejects_failure_edge() -> None:
    nodes = tuple(
        node.model_copy(update={"failure_edge": "done"})
        if node.node_id == "patch"
        else node
        for node in _nodes()
    )
    with pytest.raises(ValidationError, match="failure_edge"):
        _graph(nodes=nodes)


def test_dag_v1_rejects_non_default_retry() -> None:
    nodes = tuple(
        node.model_copy(update={"retry_class": "exponential", "max_attempts": 3})
        if node.node_id == "patch"
        else node
        for node in _nodes()
    )
    with pytest.raises(ValidationError, match="retry_class|max_attempts"):
        _graph(nodes=nodes)


def test_commit_rejects_loop_workflow(goal) -> None:
    task_service = TaskService(InMemoryTaskEventStore())
    task = task_service.create_task(goal)
    commitment = Commitment(
        commitment_id="commitment-1",
        task_id=task.task_id,
        goal_id=goal.goal_id,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        accepted_by="user-1",
        accepted_at=NOW,
        deliverables=("patch",),
        acceptance_criteria=("tests pass",),
        authority_scopes=("repo:read", "repo:write"),
        budget=ResourceBudget(
            max_cost_usd=Decimal("1.00"),
            max_duration_seconds=300,
            max_provider_tokens=1_000,
            max_tool_calls=4,
        ),
        risk_tier=1,
        exit_conditions=("tests verified",),
        expires_at=NOW + timedelta(hours=1),
    )
    expected_outcome = ExpectedOutcome(
        expected_outcome_id="expected-1",
        task_id=task.task_id,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=60,
        frozen_at=NOW,
    )
    with pytest.raises(ValidationError, match="loop"):
        task_service.commit_task(
            task.task_id,
            commitment,
            _loop_workflow(),
            expected_outcome,
        )
    assert task_service.get_task(task.task_id).status is TaskStatus.DRAFT


def test_spine0_workflow_is_valid_dag_v1(spine0_workflow: WorkflowGraph) -> None:
    assert spine0_workflow.schema_version == "WorkflowGraph/dag_v1"
    WorkflowGraph.model_validate(spine0_workflow.model_dump(mode="json"))
