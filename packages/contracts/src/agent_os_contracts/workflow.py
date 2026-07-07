from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    step_type: str  # "approval" | "notification" | "escalation" | "condition"
    approver_role: str | None = None
    timeout_seconds: int | None = None
    next_step_id: str | None = None
    fallback_step_id: str | None = None


@dataclass(frozen=True)
class ApprovalWorkflow:
    workflow_id: str
    name: str
    action_type: str
    risk_levels: tuple[str, ...]
    steps: tuple[WorkflowStep, ...]
    state: str = "draft"  # "draft" | "active" | "deprecated"


@dataclass(frozen=True)
class WorkflowEvent:
    event_id: str
    instance_id: str
    step_id: str
    event_type: str
    actor: str
    timestamp: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class WorkflowInstance:
    instance_id: str
    workflow_id: str
    proposal_id: str
    current_step_id: str
    state: str = "pending"  # "pending" | "approved" | "rejected" | "escalated" | "timeout"
    events: tuple[WorkflowEvent, ...] = ()


__all__ = [
    "ApprovalWorkflow",
    "WorkflowEvent",
    "WorkflowInstance",
    "WorkflowStep",
]
