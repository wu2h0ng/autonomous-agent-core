"""Full BPM multi-step approval workflow engine (workstream D / ADR-0013).

Governed multi-step approval chains with delegation, manual escalation, and
timeout-driven escalation. Behind ``RuntimeFeatureFlags.full_bpm_workflow``
(default ``False``); when off, no instances can be started so proposals remain
on the single-step ``ApprovalLiteRuntime`` path.

The engine operates over the workflow contracts
(``ApprovalWorkflow`` / ``WorkflowStep`` / ``WorkflowInstance`` /
``WorkflowEvent``) defined in ``agent_os_contracts``. Storage is in-memory; a
durable port may be added in a later slice. Instances are immutable: each
operation returns a new ``WorkflowInstance`` with appended events.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    ApprovalWorkflow,
    RuntimeFeatureFlags,
    WorkflowEvent,
    WorkflowInstance,
    WorkflowStep,
)

from .workflow_store import WorkflowInstanceRecord, WorkflowStorePort

__all__ = [
    "InvalidWorkflowState",
    "WorkflowDisabled",
    "WorkflowInstanceNotFound",
    "WorkflowNotFound",
    "WorkflowRuntime",
]

_TERMINAL_STATES = frozenset({"approved", "rejected", "timeout"})


class WorkflowDisabled(Exception):
    """Raised when the workflow engine is used while its feature flag is off."""


class WorkflowNotFound(Exception):
    """Raised when a referenced workflow is not registered."""


class WorkflowInstanceNotFound(Exception):
    """Raised when a referenced workflow instance does not exist (or tenant mismatch)."""


class InvalidWorkflowState(Exception):
    """Raised when an operation targets a terminal instance or a non-active workflow."""


def _default_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


class WorkflowRuntime:
    """Multi-step governed approval workflow engine.

    The workflow is modelled as a linked step graph (``next_step_id`` on
    approve, ``fallback_step_id`` on escalate/timeout). A chain completes when
    an approved step has no ``next_step_id``.
    """

    def __init__(
        self,
        feature_flags: RuntimeFeatureFlags,
        *,
        workflow_store: WorkflowStorePort | None = None,
        now: Callable[[], str] | None = None,
        trace_sink: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.feature_flags = feature_flags
        self._store = workflow_store
        self._now = now or _default_now
        self._trace_sink = trace_sink
        self._workflows: dict[str, ApprovalWorkflow] = {}
        self._instances: dict[str, WorkflowInstance] = {}
        self._tenant: dict[str, str] = {}
        self._assigned: dict[str, str] = {}
        self._step_started_at: dict[str, str] = {}
        self._counter = 0

    # -- registration ------------------------------------------------------

    def register_workflow(self, workflow: ApprovalWorkflow, *, tenant_id: str = "default") -> None:
        self._workflows[workflow.workflow_id] = workflow
        if self._store is not None:
            self._store.save_workflow(tenant_id, workflow)

    def _step_map(self, workflow: ApprovalWorkflow) -> dict[str, WorkflowStep]:
        return {s.step_id: s for s in workflow.steps}

    # -- helpers -----------------------------------------------------------

    def _next_instance_id(self) -> str:
        if self._store is not None:
            return f"wi-{uuid4().hex[:12]}"
        self._counter += 1
        return f"wi-{self._counter}"

    def _persist_instance(self, tenant_id: str, inst: WorkflowInstance) -> None:
        self._instances[inst.instance_id] = inst
        if self._store is not None:
            self._store.save_instance(
                WorkflowInstanceRecord(
                    tenant_id=tenant_id,
                    instance=inst,
                    assigned_role=self._assigned.get(inst.instance_id, ""),
                    step_started_at=self._step_started_at.get(inst.instance_id, ""),
                )
            )

    def _hydrate_instance(self, tenant_id: str, instance_id: str) -> WorkflowInstance | None:
        if self._store is None:
            return self._instances.get(instance_id)
        cached = self._instances.get(instance_id)
        if cached is not None:
            return cached
        record = self._store.get_instance(tenant_id, instance_id)
        if record is None:
            return None
        self._instances[instance_id] = record.instance
        self._tenant[instance_id] = record.tenant_id
        self._assigned[instance_id] = record.assigned_role
        self._step_started_at[instance_id] = record.step_started_at
        return record.instance

    def _workflows_for(self, tenant_id: str) -> tuple[ApprovalWorkflow, ...]:
        if self._store is not None:
            return self._store.list_workflows(tenant_id)
        return tuple(self._workflows.values())

    def _emit(self, step: str, payload: dict[str, Any]) -> None:
        if self._trace_sink is not None:
            self._trace_sink(step, dict(payload))

    def _append_event(
        self,
        inst: WorkflowInstance,
        step_id: str,
        event_type: str,
        actor: str,
        payload: dict[str, Any] | None = None,
    ) -> WorkflowInstance:
        n = len(inst.events) + 1
        evt = WorkflowEvent(
            event_id=f"evt-{inst.instance_id}-{n}",
            instance_id=inst.instance_id,
            step_id=step_id,
            event_type=event_type,
            actor=actor,
            timestamp=self._now(),
            payload=payload or {},
        )
        return replace(inst, events=inst.events + (evt,))

    def _require_instance(
        self, instance_id: str, *, tenant_id: str = "default"
    ) -> WorkflowInstance:
        inst = self._hydrate_instance(tenant_id, instance_id)
        if inst is None or self._tenant.get(instance_id, tenant_id) != tenant_id:
            raise WorkflowInstanceNotFound(f"workflow instance not found: {instance_id}")
        return inst

    def _require_active(self, inst: WorkflowInstance) -> None:
        if inst.state in _TERMINAL_STATES:
            raise InvalidWorkflowState(
                f"instance {inst.instance_id} is terminal: state={inst.state}"
            )

    def _step_for(self, workflow: ApprovalWorkflow, step_id: str) -> WorkflowStep:
        steps = self._step_map(workflow)
        step = steps.get(step_id)
        if step is None:
            raise InvalidWorkflowState(
                f"step {step_id} not found in workflow {workflow.workflow_id}"
            )
        return step

    def _advance_to(
        self,
        inst: WorkflowInstance,
        workflow: ApprovalWorkflow,
        step_id: str,
        state: str,
    ) -> WorkflowInstance:
        step = self._step_for(workflow, step_id)
        self._assigned[inst.instance_id] = step.approver_role or ""
        self._step_started_at[inst.instance_id] = self._now()
        return replace(inst, current_step_id=step_id, state=state)

    # -- public API --------------------------------------------------------

    def start_instance(
        self,
        workflow_id: str,
        proposal_id: str,
        *,
        tenant_id: str = "default",
        first_step_id: str | None = None,
        started_by: str = "system",
    ) -> WorkflowInstance:
        if not self.feature_flags.full_bpm_workflow:
            raise WorkflowDisabled("full_bpm_workflow feature flag is off; use ApprovalLiteRuntime")
        workflow = self._workflows.get(workflow_id)
        if workflow is None and self._store is not None:
            workflow = self._store.get_workflow(tenant_id, workflow_id)
            if workflow is not None:
                self._workflows[workflow_id] = workflow
        if workflow is None:
            raise WorkflowNotFound(f"workflow not registered: {workflow_id}")
        if workflow.state != "active":
            raise InvalidWorkflowState(
                f"workflow {workflow_id} is not active: state={workflow.state}"
            )
        steps = self._step_map(workflow)
        first_step_id = first_step_id or workflow.steps[0].step_id
        first_step = steps.get(first_step_id)
        if first_step is None:
            raise InvalidWorkflowState(
                f"first step {first_step_id} not found in workflow {workflow_id}"
            )
        instance_id = self._next_instance_id()
        inst = WorkflowInstance(
            instance_id=instance_id,
            workflow_id=workflow_id,
            proposal_id=proposal_id,
            current_step_id=first_step_id,
            state="pending",
            events=(),
        )
        inst = self._append_event(inst, first_step_id, "started", started_by)
        self._emit(
            "workflow.started",
            {
                "instance_id": instance_id,
                "step_id": first_step_id,
                "proposal_id": proposal_id,
                "workflow_id": workflow_id,
            },
        )
        self._assigned[instance_id] = first_step.approver_role or ""
        self._step_started_at[instance_id] = self._now()
        self._tenant[instance_id] = tenant_id
        self._persist_instance(tenant_id, inst)
        return inst

    def _workflow_of(
        self, inst: WorkflowInstance, *, tenant_id: str = "default"
    ) -> ApprovalWorkflow:
        workflow = self._workflows.get(inst.workflow_id)
        if workflow is None and self._store is not None:
            workflow = self._store.get_workflow(tenant_id, inst.workflow_id)
            if workflow is not None:
                self._workflows[inst.workflow_id] = workflow
        if workflow is None:
            raise WorkflowNotFound(f"workflow not registered: {inst.workflow_id}")
        return workflow

    def approve_step(
        self,
        instance_id: str,
        actor: str,
        *,
        reason: str | None = None,
        tenant_id: str = "default",
    ) -> WorkflowInstance:
        inst = self._require_instance(instance_id, tenant_id=tenant_id)
        self._require_active(inst)
        workflow = self._workflow_of(inst, tenant_id=tenant_id)
        step = self._step_for(workflow, inst.current_step_id)
        inst = self._append_event(
            inst,
            inst.current_step_id,
            "approved",
            actor,
            payload={"reason": reason} if reason else {},
        )
        if step.next_step_id:
            inst = self._advance_to(inst, workflow, step.next_step_id, "pending")
            self._emit(
                "workflow.step_advanced",
                {
                    "instance_id": instance_id,
                    "next_step": step.next_step_id,
                    "proposal_id": inst.proposal_id,
                },
            )
        else:
            inst = replace(inst, state="approved")
            self._emit(
                "workflow.completed",
                {"instance_id": instance_id, "proposal_id": inst.proposal_id},
            )
        self._persist_instance(tenant_id, inst)
        self._emit(
            "workflow.approved",
            {"instance_id": instance_id, "actor": actor, "proposal_id": inst.proposal_id},
        )
        return inst

    def reject_step(
        self,
        instance_id: str,
        actor: str,
        *,
        reason: str | None = None,
        tenant_id: str = "default",
    ) -> WorkflowInstance:
        inst = self._require_instance(instance_id, tenant_id=tenant_id)
        self._require_active(inst)
        inst = self._append_event(
            inst,
            inst.current_step_id,
            "rejected",
            actor,
            payload={"reason": reason} if reason else {},
        )
        self._emit(
            "workflow.rejected",
            {"instance_id": instance_id, "actor": actor, "proposal_id": inst.proposal_id},
        )
        inst = replace(inst, state="rejected")
        self._persist_instance(tenant_id, inst)
        return inst

    def delegate_step(
        self,
        instance_id: str,
        actor: str,
        to_role: str,
        *,
        tenant_id: str = "default",
    ) -> WorkflowInstance:
        inst = self._require_instance(instance_id, tenant_id=tenant_id)
        self._require_active(inst)
        inst = self._append_event(
            inst,
            inst.current_step_id,
            "delegated",
            actor,
            payload={"to_role": to_role},
        )
        self._assigned[instance_id] = to_role
        self._persist_instance(tenant_id, inst)
        return inst

    def escalate_step(
        self,
        instance_id: str,
        actor: str,
        *,
        tenant_id: str = "default",
    ) -> WorkflowInstance:
        inst = self._require_instance(instance_id, tenant_id=tenant_id)
        self._require_active(inst)
        workflow = self._workflow_of(inst, tenant_id=tenant_id)
        step = self._step_for(workflow, inst.current_step_id)
        inst = self._append_event(inst, inst.current_step_id, "escalated", actor)
        if step.fallback_step_id:
            inst = self._advance_to(inst, workflow, step.fallback_step_id, "escalated")
        else:
            inst = replace(inst, state="rejected")
        self._persist_instance(tenant_id, inst)
        return inst

    def timeout_check(
        self,
        instance_id: str,
        now: str,
        *,
        tenant_id: str = "default",
    ) -> WorkflowInstance:
        inst = self._require_instance(instance_id, tenant_id=tenant_id)
        if inst.state in _TERMINAL_STATES:
            return inst
        workflow = self._workflow_of(inst, tenant_id=tenant_id)
        step = self._step_for(workflow, inst.current_step_id)
        if step.timeout_seconds is None:
            return inst
        started = self._step_started_at.get(instance_id, "")
        if not started:
            return inst
        elapsed = (_parse_iso(now) - _parse_iso(started)).total_seconds()
        if elapsed < step.timeout_seconds:
            return inst
        inst = self._append_event(inst, inst.current_step_id, "timeout", "system")
        if step.fallback_step_id:
            inst = self._advance_to(inst, workflow, step.fallback_step_id, "escalated")
        else:
            inst = replace(inst, state="timeout")
        self._persist_instance(tenant_id, inst)
        return inst

    def try_start_for(
        self,
        proposal: Any,
        operation: Any,
        *,
        tenant_id: str = "default",
    ) -> str | None:
        """Start a workflow instance matching the proposal action/risk, if any.

        Returns the instance id, or None when no registered active workflow
        matches the proposal action type and operation risk level.
        """
        if not self.feature_flags.full_bpm_workflow:
            return None
        for wf in self._workflows_for(tenant_id):
            if wf.state != "active":
                continue
            if proposal.action_type != wf.action_type:
                continue
            if operation.risk_level not in wf.risk_levels:
                continue
            inst = self.start_instance(wf.workflow_id, proposal.proposal_id, tenant_id=tenant_id)
            return inst.instance_id
        return None

    def get_instance(self, instance_id: str, *, tenant_id: str = "default") -> WorkflowInstance:
        return self._require_instance(instance_id, tenant_id=tenant_id)

    def assigned_role(self, instance_id: str) -> str:
        return self._assigned.get(instance_id, "")
