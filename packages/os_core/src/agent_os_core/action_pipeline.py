from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from agent_os_contracts import (
    ActionContract,
    ActionReceipt,
    CapabilityGrant,
    ExpectedOutcome,
    PolicyVerdict,
    PrincipalIdentity,
    ReceiptStatus,
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
        estimated_budget: ResourceBudget | None = None,
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
            estimated_budget=estimated_budget
            or ResourceBudget(
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
        # A capability with no grant in this loop's grant map is a typed
        # policy denial (CAPABILITY_NOT_GRANTED via PolicyKernel), not a
        # KeyError: a narrowed child loop must fail closed *visibly*, with a
        # durable POLICY_DECIDED(DENY) instead of an untyped tool failure.
        grant = (
            self._grant.get(cid)
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

        try:
            result = (
                effect_custody(action.node_id, action.action_digest(), invoke)
                if effect_custody is not None
                else invoke()
            )
        except CapabilityEffectUnknown as unknown:
            # ADR-0059 / probe P12: a post-dispatch fault means the effect MAY
            # have happened - a different state from a clean FAILED. When a
            # reservation exists (dispatch was attempted), leave a typed
            # UNKNOWN ActionReceipt on the task stream before the turn pauses,
            # so the durable record can never be read as "it failed" or "it
            # never ran". Pre-reservation denials carry no receipt identity and
            # leave no receipt. The reservation-without-outcome still forbids
            # an automatic resend; recording the uncertainty does not resolve
            # it. Behavior is preserved (the unknown is re-raised) on both the
            # chat seam and the reconciliation seam.
            self._record_unknown_action_receipt_if_current(
                action, decision, permit, unknown
            )
            raise
        if execution_fence is not None:
            execution_fence("before_tool_effect_commit")
        current_fence = getattr(
            self._tasks._event_store,
            "lease_fence",
            lambda _run_id: permit.lease_fence,
        )(action.run_id)
        if current_fence != permit.lease_fence:
            raise ExecutionLeaseConflict(
                "worker lost its run lease after dispatch before receipt"
            )
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

    def _record_unknown_action_receipt(
        self,
        action: ActionContract,
        decision: Any,
        permit: Any,
        unknown: CapabilityEffectUnknown,
    ) -> None:
        """Record a typed UNKNOWN receipt for a post-dispatch uncertain effect.

        Probe P12 / ADR-0059: once a capability has been reserved and
        dispatched, a fault that prevents sealing a terminal outcome means the
        effect *may* have happened. That is neither SUCCEEDED nor a clean
        FAILED, and the task stream must say so: an
        ``ACTION_RECEIPT_RECORDED`` carrying ``ReceiptStatus.UNKNOWN`` under
        the reservation's own receipt identity. The reservation-without-
        outcome in the idempotency store still forbids an automatic resend
        (replay raises RESERVATION_WITHOUT_OUTCOME), so this records the
        uncertainty exactly once and never resolves or retries it.

        A pre-reservation denial carries no receipt identity: nothing was
        dispatched, so it leaves no receipt, preserving the existing contract.
        """

        receipt_id = getattr(unknown, "receipt_id", None)
        if not isinstance(receipt_id, str) or not receipt_id:
            return
        receipt = ActionReceipt(
            receipt_id=receipt_id,
            action_id=action.action_id,
            action_digest=action.action_digest(),
            permit_id=permit.permit_id,
            tenant_id=action.tenant_id,
            workspace_id=action.workspace_id,
            connector_id=action.capability_id,
            status=ReceiptStatus.UNKNOWN,
            idempotency_key=action.idempotency_key,
            attempt=1,
            output_artifact_ids=(),
            error_code=f"UNKNOWN:{unknown.reason_code}",
            detail_ref="detail:none",
            occurred_at=datetime.now(timezone.utc),
        )
        self._tasks._record_action_receipt(
            action.task_id,
            action=action,
            decision=decision,
            permit=permit,
            receipt=receipt,
            writer_token=self._tasks._runtime_writer_token,
        )

    def _record_unknown_action_receipt_if_current(
        self,
        action: ActionContract,
        decision: Any,
        permit: Any,
        unknown: CapabilityEffectUnknown,
    ) -> None:
        current_fence = getattr(
            self._tasks._event_store,
            "lease_fence",
            lambda _run_id: permit.lease_fence,
        )(action.run_id)
        if current_fence != permit.lease_fence:
            raise ExecutionLeaseConflict(
                "worker lost its run lease before UNKNOWN receipt recording"
            ) from unknown
        self._record_unknown_action_receipt(action, decision, permit, unknown)

    def execute_observed(
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
        """Execute once, persist the receipt, and return every observed status.

        Unlike :meth:`execute`, this seam does not translate FAILED or UNKNOWN
        effects into an exception. Callers that reconcile effects need the
        durable receipt before deciding whether another invocation is safe.
        """
        cid = capability_id or action.capability_id
        if cid == "workspace.compensate_patch":
            raise RunExecutionError(
                "workspace.compensate_patch is coordinator-only"
            )
        self._tasks.assert_external_exact_approval(action, approval)
        # A capability with no grant in this loop's grant map is a typed
        # policy denial (CAPABILITY_NOT_GRANTED via PolicyKernel), not a
        # KeyError: a narrowed child loop must fail closed *visibly*, with a
        # durable POLICY_DECIDED(DENY) instead of an untyped tool failure.
        grant = (
            self._grant.get(cid)
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
        lease_fence = execution_claim.fence
        try:
            permit = self._policy.permit(
                action, decision, grant, lease_fence=lease_fence
            )
        except PermissionError:
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
        if execution_claim.fence != permit.lease_fence:
            raise ExecutionLeaseConflict("stale worker execution claim")
        if execution_fence is not None:
            execution_fence("before_tool_effect")

        def invoke() -> CapabilityResult:
            return self._broker.invoke(
                action,
                permit,
                execution_claim=execution_claim,
            )

        try:
            result = (
                effect_custody(action.node_id, action.action_digest(), invoke)
                if effect_custody is not None
                else invoke()
            )
        except CapabilityEffectUnknown as unknown:
            # ADR-0059 / probe P12: a post-dispatch fault means the effect MAY
            # have happened - a different state from a clean FAILED. When a
            # reservation exists (dispatch was attempted), leave a typed
            # UNKNOWN ActionReceipt on the task stream before the turn pauses,
            # so the durable record can never be read as "it failed" or "it
            # never ran". Pre-reservation denials carry no receipt identity and
            # leave no receipt. The reservation-without-outcome still forbids
            # an automatic resend; recording the uncertainty does not resolve
            # it. Behavior is preserved (the unknown is re-raised) on both the
            # chat seam and the reconciliation seam.
            self._record_unknown_action_receipt_if_current(
                action, decision, permit, unknown
            )
            raise
        if execution_fence is not None:
            execution_fence("before_tool_effect_commit")
        current_fence = getattr(
            self._tasks._event_store,
            "lease_fence",
            lambda _run_id: permit.lease_fence,
        )(action.run_id)
        if current_fence != permit.lease_fence:
            raise ExecutionLeaseConflict(
                "worker lost its run lease after dispatch before receipt"
            )
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
            return result
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
