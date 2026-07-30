from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    ActionContract,
    CapabilityGrant,
    ExpectedOutcome,
    PolicyVerdict,
    PrincipalIdentity,
    ResourceBudget,
    TaskEventType,
)

from .capability import CapabilityBroker, CapabilityResult
from .errors import RunExecutionError
from .governance import CorrectionReadPort, PolicyInput, PolicyKernel
from .task_service import TaskService


class ActionPipeline:
    """Typed action flow: build contract → policy → permit → broker → receipt."""

    def __init__(
        self,
        task_service: TaskService,
        broker: CapabilityBroker,
        policy: PolicyKernel,
        correction: CorrectionReadPort,
        grant: CapabilityGrant | dict[str, CapabilityGrant],
    ) -> None:
        self._tasks = task_service
        self._broker = broker
        self._policy = policy
        self._correction = correction
        self._grant = grant

    def build_action(
        self,
        *,
        task_id: str,
        run_id: str,
        node_id: str,
        capability_id: str,
        principal: PrincipalIdentity,
        args: dict[str, Any],
        expected: ExpectedOutcome,
        envelope_id: str,
        risk_tier: int,
    ) -> ActionContract:
        return ActionContract(
            action_id=f"action-{uuid4()}",
            task_id=task_id,
            run_id=run_id,
            node_id=node_id,
            principal_id=principal.principal_id,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            capability_id=capability_id,
            capability_version="1",
            arguments_json=json.dumps(args),
            risk_tier=risk_tier,
            idempotency_key=f"{run_id}:{node_id}",
            estimated_budget=ResourceBudget(
                max_cost_usd=Decimal("0"),
                max_duration_seconds=120,
                max_provider_tokens=0,
                max_tool_calls=1,
            ),
            policy_version=self._policy.policy_version,
            observed_correction_epochs=self._correction.snapshot(
                task_id, run_id, capability_id
            ),
            expected_outcome_id=expected.expected_outcome_id,
            candidate_envelope_id=envelope_id,
            created_at=datetime.now(timezone.utc),
        )

    def execute(
        self,
        action: ActionContract,
        principal: PrincipalIdentity,
        capability_spec: Any | None = None,
        approval: Any = None,
        *,
        lease_fence_fn: Callable[[str], int] | None = None,
        capability_id: str | None = None,
    ) -> CapabilityResult:
        cid = capability_id or action.capability_id
        if cid == "workspace.compensate_patch":
            raise RunExecutionError(
                "workspace.compensate_patch is coordinator-only"
            )
        grant = (
            self._grant[cid]
            if isinstance(self._grant, dict)
            else self._grant
        )
        bound_approval = (
            approval
            if approval is not None
            and approval.action_digest == action.action_digest()
            else None
        )
        decision = self._policy.decide(
            action,
            PolicyInput(
                principal=principal,
                grant=grant,
                capability=capability_spec,
                approval=bound_approval,
            ),
        )
        self._tasks.append_event(
            action.task_id,
            TaskEventType.POLICY_DECIDED,
            {"decision": decision.model_dump(mode="json")},
            correlation_id=action.run_id,
        )
        if decision.verdict is not PolicyVerdict.ALLOW:
            raise PermissionError(
                f"policy denied {cid}: {decision.reason_codes}"
            )
        aggregate = self._tasks.get_task(action.task_id)
        lease_fence = (
            aggregate.run.lease_fence if aggregate.run is not None else 0
        )
        permit = self._policy.permit(
            action, decision, grant, lease_fence=lease_fence
        )
        run_id = action.run_id
        if lease_fence_fn is not None:
            current_fence = lease_fence_fn(run_id)
        else:
            current_fence = lease_fence
            store = getattr(self._tasks._event_store, "lease_fence", None)
            if store is not None:
                current_fence = store(run_id)
        if current_fence != permit.lease_fence:
            raise PermissionError("stale worker lease")
        result = self._broker.invoke(action, permit)
        self._tasks._record_action_receipt(
            action.task_id,
            action=action,
            decision=decision,
            permit=permit,
            receipt=result.receipt,
            writer_token=self._tasks._runtime_writer_token,
        )
        if result.receipt.status.value != "SUCCEEDED":
            raise RunExecutionError(
                f"tool failed: {result.receipt.error_code}"
            )
        for artifact_id in result.receipt.output_artifact_ids:
            self._tasks.record_artifact(
                action.task_id,
                artifact_id,
                node_id=action.node_id,
                action_id=action.action_id,
            )
        return result

    def record_action_proposed(
        self, action: ActionContract
    ) -> None:
        self._tasks.append_event(
            action.task_id,
            TaskEventType.ACTION_PROPOSED,
            {"action": action.model_dump(mode="json")},
            correlation_id=action.run_id,
        )
