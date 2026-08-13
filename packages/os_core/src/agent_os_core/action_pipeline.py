from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal
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

from .capability import (
    CapabilityBroker,
    CapabilityCorrectionBlocked,
    CapabilityEffectUnknown,
    CapabilityResult,
)
from ._action_outcome import ExecutionLease, ExecutionLeaseConflict
from .errors import RunExecutionError
from .governance import CorrectionReadPort, PolicyInput, PolicyKernel
from .task_service import TaskService


EffectCustodyPort = Callable[
    [str, str, Callable[[], CapabilityResult]],
    CapabilityResult,
]


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
        approval_requirement: Literal["policy", "external_exact"] = "policy",
    ) -> ActionContract:
        candidate = ActionContract(
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
            approval_requirement=approval_requirement,
            created_at=datetime.now(timezone.utc),
        )
        reusable = self._tasks._find_reusable_proposed_action(
            task_id, candidate
        )
        return reusable if reusable is not None else candidate

    def reconcile_before_policy(
        self,
        action: ActionContract,
        *,
        record_artifacts: bool = False,
    ) -> CapabilityResult | None:
        """Resolve Task/capability truth without policy or capability dispatch."""

        try:
            recorded = self._tasks._find_exact_action_receipt(
                action.task_id,
                action,
            )
        except Exception as exc:
            raise CapabilityEffectUnknown(
                action,
                reason_code="TASK_RECEIPT_CORRUPT",
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc
        try:
            replayed = self._broker.replay(action)
        except CapabilityEffectUnknown:
            raise
        except Exception as exc:
            raise CapabilityEffectUnknown(
                action,
                reason_code="CAPABILITY_OUTCOME_READ_FAILED",
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc
        if recorded is not None:
            if replayed is None:
                raise CapabilityEffectUnknown(
                    action,
                    reason_code="TASK_RECEIPT_WITHOUT_OUTCOME",
                    detail=(
                        "Task receipt exists without the exact sealed capability "
                        "outcome; automatic dispatch is forbidden"
                    ),
                )
            if (
                replayed.permit != recorded.permit
                or replayed.receipt != recorded.receipt
            ):
                raise CapabilityEffectUnknown(
                    action,
                    reason_code="RECEIPT_OUTCOME_CONFLICT",
                    detail="Task receipt and sealed capability outcome conflict",
                )
            return self._finish_result(
                action,
                replayed,
                record_artifacts=record_artifacts,
            )
        if replayed is not None:
            try:
                self._tasks._recover_action_receipt(
                    action.task_id,
                    action=action,
                    permit=replayed.permit,
                    receipt=replayed.receipt,
                    effect=(
                        {
                            key: str(replayed.output[key])
                            for key in (
                                "path",
                                "compensation_ref",
                                "manifest_sha256",
                                "applied_sha256",
                            )
                        }
                        if action.capability_id
                        in {"workspace.apply_patch", "workspace.edit"}
                        and all(
                            key in replayed.output
                            for key in (
                                "path",
                                "compensation_ref",
                                "manifest_sha256",
                                "applied_sha256",
                            )
                        )
                        else None
                    ),
                    writer_token=self._tasks._runtime_writer_token,
                )
            except Exception as exc:
                raise CapabilityEffectUnknown(
                    action,
                    reason_code="OUTCOME_TASK_TRUTH_CONFLICT",
                    detail=f"{type(exc).__name__}: {exc}",
                ) from exc
            return self._finish_result(
                action,
                replayed,
                record_artifacts=record_artifacts,
            )
        return None

    def _finish_result(
        self,
        action: ActionContract,
        result: CapabilityResult,
        *,
        record_artifacts: bool,
    ) -> CapabilityResult:
        if result.receipt.status.value != "SUCCEEDED":
            raise RunExecutionError(
                f"tool failed: {result.receipt.error_code}: "
                f"{result.output.get('error', '')}"
            )
        if not record_artifacts:
            # Chat-loop actions use ephemeral per-turn node ids (required for
            # idempotency uniqueness across repeated calls), which are not
            # committed workflow nodes; the workflow-bound artifact index
            # cannot cover them. The durable action receipt still binds the
            # output artifact ids.
            return result
        for artifact_id in result.receipt.output_artifact_ids:
            self._tasks.record_artifact(
                action.task_id,
                artifact_id,
                node_id=action.node_id,
                action_id=action.action_id,
            )
        return result

    def execute(
        self,
        action: ActionContract,
        principal: PrincipalIdentity,
        capability_spec: Any | None = None,
        approval: Any = None,
        *,
        lease_fence_fn: Callable[[str], int] | None = None,
        capability_id: str | None = None,
        record_artifacts: bool = True,
        execution_fence: Callable[[str], None] | None = None,
        effect_custody: EffectCustodyPort | None = None,
        execution_claim: ExecutionLease,
    ) -> CapabilityResult:
        cid = capability_id or action.capability_id
        if cid == "workspace.compensate_patch":
            raise RunExecutionError(
                "workspace.compensate_patch is coordinator-only"
            )
        replayed = self.reconcile_before_policy(
            action,
            record_artifacts=record_artifacts,
        )
        if replayed is not None:
            return replayed
        self._tasks.assert_external_exact_approval(action, approval)
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
            if bound_approval is not None and (
                self._correction.halted(
                    action.task_id,
                    action.run_id,
                    action.capability_id,
                )
                or self._correction.snapshot(
                    action.task_id,
                    action.run_id,
                    action.capability_id,
                )
                != action.observed_correction_epochs
            ):
                raise CapabilityCorrectionBlocked(
                    "C7 correction authority halted approved action execution"
                )
            raise PermissionError(
                f"policy denied {cid}: {decision.reason_codes}"
            )
        lease_fence = execution_claim.fence
        try:
            permit = self._policy.permit(
                action, decision, grant, lease_fence=lease_fence
            )
        except PermissionError as exc:
            current_epochs = self._correction.snapshot(
                action.task_id,
                action.run_id,
                action.capability_id,
            )
            if bound_approval is not None and (
                self._correction.halted(
                    action.task_id,
                    action.run_id,
                    action.capability_id,
                )
                or current_epochs != action.observed_correction_epochs
                or current_epochs != decision.correction_epochs
            ):
                raise CapabilityCorrectionBlocked(
                    "C7 correction authority changed before permit"
                ) from exc
            raise
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
        if execution_fence is not None:
            execution_fence("before_tool_effect")

        if execution_claim.fence != permit.lease_fence:
            raise ExecutionLeaseConflict("stale worker execution claim")

        def invoke() -> CapabilityResult:
            return self._broker.invoke(
                action,
                permit,
                execution_claim=execution_claim,
            )

        result = (
            effect_custody(action.node_id, action.action_digest(), invoke)
            if effect_custody is not None
            else invoke()
        )
        if execution_fence is not None:
            execution_fence("before_tool_effect_commit")
        self._tasks._record_action_receipt(
            action.task_id,
            action=action,
            decision=decision,
            permit=permit,
            receipt=result.receipt,
            writer_token=self._tasks._runtime_writer_token,
            effect=(
                {
                    key: str(result.output[key])
                    for key in (
                        "path",
                        "compensation_ref",
                        "manifest_sha256",
                        "applied_sha256",
                    )
                }
                if action.capability_id
                in {"workspace.apply_patch", "workspace.edit"}
                and result.receipt.status.value == "SUCCEEDED"
                else None
            ),
        )
        if result.receipt.status.value != "SUCCEEDED":
            raise RunExecutionError(
                f"tool failed: {result.receipt.error_code}: "
                f"{result.output.get('error', '')}"
            )
        if not record_artifacts:
            # Chat-loop actions use ephemeral per-turn node ids (required for
            # idempotency uniqueness across repeated calls), which are not
            # committed workflow nodes; the workflow-bound artifact index
            # cannot cover them. The durable action receipt still binds the
            # output artifact ids.
            return result
        for artifact_id in result.receipt.output_artifact_ids:
            self._tasks.record_artifact(
                action.task_id,
                artifact_id,
                node_id=action.node_id,
                action_id=action.action_id,
            )
        return result

    def record_action_proposed(
        self,
        action: ActionContract,
        *,
        provider_tool_call_id: str | None = None,
        turn_id: str | None = None,
    ) -> None:
        # Idempotent: crash recovery resumes exact logical action identities,
        # so re-proposing the same action must not duplicate the durable
        # ACTION_PROPOSED record (wave lineage semantics).
        self._tasks._record_or_reuse_action_proposed(action)
