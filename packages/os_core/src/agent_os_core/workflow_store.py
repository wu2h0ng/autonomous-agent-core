"""Workflow persistence port (workstream D / ADR-0013).

OS Core owns the Port; in-memory lives here and SQL adapters live in
``agent_os_persistence``. Workflows and instances survive restarts when a
durable adapter is injected at the composition boundary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from agent_os_contracts import ApprovalWorkflow, WorkflowInstance

__all__ = [
    "InMemoryWorkflowStore",
    "WorkflowInstanceRecord",
    "WorkflowStorePort",
]


@dataclass(frozen=True)
class WorkflowInstanceRecord:
    tenant_id: str
    instance: WorkflowInstance
    assigned_role: str = ""
    step_started_at: str = ""


class WorkflowStorePort(ABC):
    @abstractmethod
    def save_workflow(self, tenant_id: str, workflow: ApprovalWorkflow) -> ApprovalWorkflow: ...

    @abstractmethod
    def get_workflow(self, tenant_id: str, workflow_id: str) -> ApprovalWorkflow | None: ...

    @abstractmethod
    def list_workflows(self, tenant_id: str) -> tuple[ApprovalWorkflow, ...]: ...

    @abstractmethod
    def save_instance(self, record: WorkflowInstanceRecord) -> WorkflowInstanceRecord: ...

    @abstractmethod
    def get_instance(self, tenant_id: str, instance_id: str) -> WorkflowInstanceRecord | None: ...


class InMemoryWorkflowStore(WorkflowStorePort):
    def __init__(self) -> None:
        self._workflows: dict[tuple[str, str], ApprovalWorkflow] = {}
        self._instances: dict[tuple[str, str], WorkflowInstanceRecord] = {}

    def save_workflow(self, tenant_id: str, workflow: ApprovalWorkflow) -> ApprovalWorkflow:
        self._workflows[(tenant_id, workflow.workflow_id)] = workflow
        return workflow

    def get_workflow(self, tenant_id: str, workflow_id: str) -> ApprovalWorkflow | None:
        return self._workflows.get((tenant_id, workflow_id))

    def list_workflows(self, tenant_id: str) -> tuple[ApprovalWorkflow, ...]:
        return tuple(w for (tid, _), w in self._workflows.items() if tid == tenant_id)

    def save_instance(self, record: WorkflowInstanceRecord) -> WorkflowInstanceRecord:
        key = (record.tenant_id, record.instance.instance_id)
        self._instances[key] = record
        return record

    def get_instance(self, tenant_id: str, instance_id: str) -> WorkflowInstanceRecord | None:
        return self._instances.get((tenant_id, instance_id))
