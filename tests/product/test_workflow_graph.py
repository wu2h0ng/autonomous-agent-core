from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    WorkflowGraph,
)


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
    nodes: Iterable[NodeSpec] | None = None,
    edges: Iterable[EdgeSpec] | None = None,
) -> WorkflowGraph:
    return WorkflowGraph(
        workflow_id="workflow-1",
        version=1,
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        created_by="user-1",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=tuple(nodes if nodes is not None else _nodes()),
        edges=tuple(edges if edges is not None else _edges()),
    )


def test_graph_digest_ignores_node_and_edge_input_order() -> None:
    first = _graph()
    second = _graph(nodes=reversed(_nodes()), edges=reversed(_edges()))

    assert first.canonical_digest() == second.canonical_digest()


def test_graph_digest_changes_when_semantics_change() -> None:
    original = _graph()
    changed_nodes = tuple(
        node.model_copy(update={"timeout_seconds": 120})
        if node.node_id == "patch"
        else node
        for node in _nodes()
    )

    assert original.canonical_digest() != _graph(nodes=changed_nodes).canonical_digest()


def test_graph_rejects_cycle() -> None:
    cyclic_edges = (*_edges(), EdgeSpec(source="verify", target="inspect"))

    with pytest.raises(ValidationError, match="acyclic"):
        _graph(edges=cyclic_edges)


def test_graph_rejects_unknown_edge_endpoint() -> None:
    with pytest.raises(ValidationError, match="unknown node"):
        _graph(edges=(*_edges(), EdgeSpec(source="ghost", target="done")))


def test_graph_rejects_duplicate_node_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate node"):
        _graph(nodes=(*_nodes(), _nodes()[0]))


def test_graph_rejects_duplicate_edges() -> None:
    with pytest.raises(ValidationError, match="duplicate edge"):
        _graph(edges=(*_edges(), _edges()[0]))


def test_graph_requires_terminal_node() -> None:
    with pytest.raises(ValidationError, match="terminal"):
        _graph(
            nodes=tuple(node for node in _nodes() if node.kind is not NodeKind.TERMINAL)
        )


def test_tool_node_requires_capability() -> None:
    with pytest.raises(ValidationError, match="capability"):
        NodeSpec(node_id="patch", kind=NodeKind.TOOL)


def test_loop_node_requires_iteration_bound() -> None:
    with pytest.raises(ValidationError, match="max_iterations"):
        NodeSpec(node_id="retry", kind=NodeKind.LOOP)


def test_parallel_map_requires_concurrency_bound() -> None:
    with pytest.raises(ValidationError, match="max_concurrency"):
        NodeSpec(node_id="fanout", kind=NodeKind.PARALLEL_MAP)


def test_terminal_node_cannot_have_outgoing_edge() -> None:
    with pytest.raises(ValidationError, match="terminal node"):
        _graph(edges=(*_edges(), EdgeSpec(source="done", target="inspect")))


def test_graph_rejects_executable_node_after_evaluation() -> None:
    nodes = (
        NodeSpec(
            node_id="inspect",
            kind=NodeKind.TOOL,
            capability="workspace.read",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(node_id="verify", kind=NodeKind.EVALUATION),
        NodeSpec(
            node_id="patch-after-verify",
            kind=NodeKind.TOOL,
            capability="workspace.apply_patch",
            idempotency=IdempotencyMode.COMPENSATABLE,
        ),
        NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
    )
    edges = (
        EdgeSpec(source="inspect", target="verify"),
        EdgeSpec(source="verify", target="patch-after-verify"),
        EdgeSpec(source="patch-after-verify", target="done"),
    )

    with pytest.raises(ValidationError, match="evaluation.*terminal"):
        _graph(nodes=nodes, edges=edges)
