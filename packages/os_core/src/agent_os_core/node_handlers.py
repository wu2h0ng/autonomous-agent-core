from __future__ import annotations

from typing import Any

from agent_os_contracts import (
    NodeKind,
)

from .errors import UnsupportedNodeError


class NodeHandlerRegistry:
    """Delegate per-node-kind execution to typed handlers.

    Currently handles only simple node kinds (TRANSFORM, DECISION, TERMINAL, WAIT_EVENT).
    Complex handlers (PROVIDER, TOOL, EVALUATION, APPROVAL) remain in RunCoordinator.run().
    """

    def handle_simple(
        self, node: Any, *, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        kind = node.kind
        if kind in {NodeKind.TRANSFORM, NodeKind.DECISION}:
            existing = context.get(node.node_id)
            context[node.node_id] = (
                existing
                if isinstance(existing, dict)
                else {
                    "available_context_keys": tuple(
                        sorted(
                            key
                            for key in context
                            if key != node.node_id
                            and not key.startswith("action:")
                        )
                    )
                }
            )
            return None
        elif kind is NodeKind.TERMINAL:
            context[node.node_id] = {"status": "complete"}
            return None
        elif kind in {
            NodeKind.LOOP,
            NodeKind.PARALLEL_MAP,
            NodeKind.SUBWORKFLOW,
        }:
            raise UnsupportedNodeError(
                f"node kind {kind.value} requires an explicit runtime extension"
            )
        return None
