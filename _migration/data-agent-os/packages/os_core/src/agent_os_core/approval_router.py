"""Runtime selection point (AR-20260707 next slice / AGENTS.md boundary #8).

The :class:`ApprovalRouter` is the entry point that makes the staged-out
engines (C/D/E) reachable from a real runtime path. Given an
``ActionProposal`` + ``OperationContract`` it decides which approval path
applies:

1. ``policy_pre_approved`` — the :class:`PolicyEngine` pre-approves
   (``r4_r5_auto_execution`` flag on + matching policy + guardrails pass).
2. ``workflow`` — a registered multi-step :class:`WorkflowRuntime` applies
   (``full_bpm_workflow`` flag on + a matching active workflow).
3. ``lite`` — default human single-step approval via ``ApprovalLiteRuntime``.

Priority: policy pre-approval wins over workflow when both are configured,
because a policy pre-approval is an explicit tenant decision to auto-execute.
When all flags are off (the default), every route is ``lite`` — the current
MVP behavior is unchanged.

The router does NOT execute the action; it only selects the path and returns a
decision carrying the proposal (with ``execution_mode`` set when pre-approved),
plus any policy-approval or workflow-instance handle. The caller (e.g.
``TrustedLoopRuntime``) owns execution and trace.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agent_os_contracts import ActionProposal, OperationContract, RuntimeFeatureFlags

if TYPE_CHECKING:
    from .policy_engine import GuardrailInput, PolicyEngine
    from .workflow import WorkflowRuntime

__all__ = ["ApprovalRouteDecision", "ApprovalRouter"]


@dataclass(frozen=True)
class ApprovalRouteDecision:
    """The selected approval path for a proposal + operation."""

    mode: str  # "policy_pre_approved" | "workflow" | "lite"
    proposal: ActionProposal
    policy_approval_id: str | None = None
    workflow_instance_id: str | None = None
    workflow_state: str | None = None
    policy_result: Any | None = None


class ApprovalRouter:
    """Select the approval path for a governed action.

    Optional dependencies: ``policy_engine`` and ``workflow_runtime``. When an
    injected engine is present but its flag is off, that path is skipped
    (fail-safe: the engine is inert unless its flag is on).
    """

    def __init__(
        self,
        feature_flags: RuntimeFeatureFlags,
        *,
        policy_engine: PolicyEngine | None = None,
        workflow_runtime: WorkflowRuntime | None = None,
    ) -> None:
        self.feature_flags = feature_flags
        self._policy_engine = policy_engine
        self._workflow_runtime = workflow_runtime

    def route(
        self,
        proposal: ActionProposal,
        operation: OperationContract,
        guardrails: GuardrailInput,
        *,
        tenant_id: str,
        trace_id: str,
    ) -> ApprovalRouteDecision:
        # 1. Policy pre-approval (highest priority — explicit tenant opt-in).
        if self.feature_flags.r4_r5_auto_execution and self._policy_engine is not None:
            result = self._policy_engine.evaluate(
                proposal,
                operation,
                guardrails,
                tenant_id=tenant_id,
                trace_id=trace_id,
            )
            if result.decision == "policy_pre_approved":
                updated = self._policy_engine.apply_decision(proposal, result)
                return ApprovalRouteDecision(
                    mode="policy_pre_approved",
                    proposal=updated,
                    policy_approval_id=result.policy_approval_id,
                    policy_result=result,
                )
            # policy denied / proposal_only -> fall through to workflow or lite

        # 2. Multi-step workflow.
        if self.feature_flags.full_bpm_workflow and self._workflow_runtime is not None:
            instance_id = self._workflow_runtime.try_start_for(
                proposal,
                operation,
                tenant_id=tenant_id,
            )
            if instance_id is not None:
                instance = self._workflow_runtime.get_instance(instance_id, tenant_id=tenant_id)
                return ApprovalRouteDecision(
                    mode="workflow",
                    proposal=proposal,
                    workflow_instance_id=instance_id,
                    workflow_state=instance.state,
                )

        # 3. Default: single-step human approval.
        return ApprovalRouteDecision(mode="lite", proposal=proposal)
