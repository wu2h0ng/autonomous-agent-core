from __future__ import annotations

from collections import deque
from enum import Enum

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime, content_digest


class NodeKind(str, Enum):
    PROVIDER = "provider"
    TOOL = "tool"
    TRANSFORM = "transform"
    DECISION = "decision"
    APPROVAL = "approval"
    EVALUATION = "evaluation"
    WAIT_EVENT = "wait_event"
    LOOP = "loop"
    PARALLEL_MAP = "parallel_map"
    SUBWORKFLOW = "subworkflow"
    TERMINAL = "terminal"


class IdempotencyMode(str, Enum):
    NONE = "none"
    IDEMPOTENT = "idempotent"
    COMPENSATABLE = "compensatable"


class NodeSpec(ContractModel):
    node_id: NonEmptyStr
    kind: NodeKind
    input_contract: NonEmptyStr = "contract:any:1"
    output_contract: NonEmptyStr = "contract:any:1"
    capability: NonEmptyStr | None = None
    timeout_seconds: int = Field(default=60, ge=1)
    max_attempts: int = Field(default=1, ge=1)
    risk_tier: int = Field(default=0, ge=0, le=5)
    idempotency: IdempotencyMode = IdempotencyMode.NONE
    max_iterations: int | None = Field(default=None, ge=1)
    max_concurrency: int | None = Field(default=None, ge=1)
    subworkflow_ref: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _validate_kind_requirements(self) -> NodeSpec:
        if self.kind in {NodeKind.PROVIDER, NodeKind.TOOL} and self.capability is None:
            raise ValueError(f"{self.kind.value} node requires capability")
        if self.kind is NodeKind.LOOP and self.max_iterations is None:
            raise ValueError("loop node requires max_iterations")
        if self.kind is not NodeKind.LOOP and self.max_iterations is not None:
            raise ValueError("max_iterations is valid only for loop nodes")
        if self.kind is NodeKind.PARALLEL_MAP and self.max_concurrency is None:
            raise ValueError("parallel_map node requires max_concurrency")
        if self.kind is not NodeKind.PARALLEL_MAP and self.max_concurrency is not None:
            raise ValueError("max_concurrency is valid only for parallel_map nodes")
        if self.kind is NodeKind.SUBWORKFLOW and self.subworkflow_ref is None:
            raise ValueError("subworkflow node requires subworkflow_ref")
        if self.kind is not NodeKind.SUBWORKFLOW and self.subworkflow_ref is not None:
            raise ValueError("subworkflow_ref is valid only for subworkflow nodes")
        return self


class EdgeSpec(ContractModel):
    source: NonEmptyStr
    target: NonEmptyStr
    condition: NonEmptyStr | None = None


class WorkflowGraph(ContractModel):
    workflow_id: NonEmptyStr
    version: int = Field(ge=1)
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    created_by: NonEmptyStr
    created_at: UtcDateTime
    policy_version: NonEmptyStr
    evaluator_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    nodes: tuple[NodeSpec, ...] = Field(min_length=1)
    edges: tuple[EdgeSpec, ...] = ()

    @field_validator("evaluator_refs", mode="after")
    @classmethod
    def _normalize_evaluator_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _validate_graph(self) -> WorkflowGraph:
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("workflow graph contains duplicate node ids")

        nodes_by_id = {node.node_id: node for node in self.nodes}
        if not any(node.kind is NodeKind.TERMINAL for node in self.nodes):
            raise ValueError("workflow graph requires a terminal node")

        adjacency = {node_id: [] for node_id in node_ids}
        indegree = {node_id: 0 for node_id in node_ids}
        for edge in self.edges:
            if edge.source not in nodes_by_id or edge.target not in nodes_by_id:
                raise ValueError("workflow edge references unknown node")
            if edge.source == edge.target:
                raise ValueError("workflow graph must be acyclic; self-edge found")
            if nodes_by_id[edge.source].kind is NodeKind.TERMINAL:
                raise ValueError("terminal node cannot have outgoing edge")
            adjacency[edge.source].append(edge.target)
            indegree[edge.target] += 1

        ready = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
        visited = 0
        while ready:
            current = ready.popleft()
            visited += 1
            for target in sorted(adjacency[current]):
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)

        if visited != len(node_ids):
            raise ValueError("workflow graph must be acyclic")
        return self

    def canonical_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude_none=True)
        payload["nodes"] = sorted(payload["nodes"], key=lambda item: item["node_id"])
        payload["edges"] = sorted(
            payload["edges"],
            key=lambda item: (
                item["source"],
                item["target"],
                item.get("condition") or "",
            ),
        )
        return content_digest(payload)
