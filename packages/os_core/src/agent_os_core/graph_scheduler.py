from __future__ import annotations

from agent_os_contracts import WorkflowGraph


class GraphScheduler:
    """Topological node ordering for bounded DAG execution."""

    @staticmethod
    def ordered_nodes(workflow: WorkflowGraph):
        incoming: dict[str, int] = {node.node_id: 0 for node in workflow.nodes}
        outgoing: dict[str, list[str]] = {node.node_id: [] for node in workflow.nodes}
        for edge in workflow.edges:
            incoming[edge.target] += 1
            outgoing[edge.source].append(edge.target)
        ready = sorted(node_id for node_id, count in incoming.items() if count == 0)
        by_id = {node.node_id: node for node in workflow.nodes}
        result = []
        while ready:
            node_id = ready.pop(0)
            result.append(by_id[node_id])
            for target in sorted(outgoing[node_id]):
                incoming[target] -= 1
                if incoming[target] == 0:
                    ready.append(target)
                    ready.sort()
        return result
