from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from agent_os_contracts import (
    ActionContract,
    ActionPermit,
    ApprovalDecision,
    ApprovalDisposition,
    CapabilityGrant,
    CapabilityGrantStatus,
    CapabilitySpec,
    CorrectionEpochVector,
    PolicyDecision,
    PolicyVerdict,
    PrincipalIdentity,
)


class CorrectionAuthority:
    """Externally-owned correction epochs. Acting code receives snapshots only."""

    def __init__(self, persistence: object | None = None, *, tenant_id: str = "tenant:local", workspace_id: str = "workspace:local", written_by: str = "principal") -> None:
        self._epochs: dict[tuple[str, str], tuple[int, bool, str]] = {}
        self._persistence = persistence
        self._tenant_id = tenant_id
        self._workspace_id = workspace_id
        self._written_by = written_by

    def snapshot(self, task_id: str, run_id: str, capability_id: str) -> CorrectionEpochVector:
        return CorrectionEpochVector(
            task_epoch=self._epoch("task", task_id)[0],
            run_epoch=self._epoch("run", run_id)[0],
            capability_epoch=self._epoch("capability", capability_id)[0],
        )

    def halted(self, task_id: str, run_id: str, capability_id: str) -> bool:
        return any(
            self._epoch(scope, value)[1]
            for scope, value in (
                ("task", task_id),
                ("run", run_id),
                ("capability", capability_id),
            )
        )

    def correct(self, scope: str, scope_id: str, reason: str) -> int:
        if scope not in {"task", "run", "capability"}:
            raise ValueError("unsupported correction scope")
        advance = getattr(self._persistence, "advance_correction", None)
        if advance is not None:
            value = advance(
                scope,
                scope_id,
                self._tenant_id,
                self._workspace_id,
                True,
                reason,
                self._written_by,
                datetime.now(timezone.utc).isoformat(),
            )
            self._epochs[(scope, scope_id)] = value
            return value[0]
        epoch, _, _ = self._epoch(scope, scope_id)
        self._epochs[(scope, scope_id)] = (epoch + 1, True, reason)
        self._persist(scope, scope_id, epoch + 1, True, reason)
        return epoch + 1

    def resume(self, scope: str, scope_id: str, reason: str = "resumed") -> int:
        if scope not in {"task", "run", "capability"}:
            raise ValueError("unsupported correction scope")
        advance = getattr(self._persistence, "advance_correction", None)
        if advance is not None:
            value = advance(
                scope,
                scope_id,
                self._tenant_id,
                self._workspace_id,
                False,
                reason,
                self._written_by,
                datetime.now(timezone.utc).isoformat(),
            )
            self._epochs[(scope, scope_id)] = value
            return value[0]
        epoch, _, _ = self._epoch(scope, scope_id)
        self._epochs[(scope, scope_id)] = (epoch + 1, False, reason)
        self._persist(scope, scope_id, epoch + 1, False, reason)
        return epoch + 1

    def _epoch(self, scope: str, scope_id: str) -> tuple[int, bool, str]:
        reader = getattr(self._persistence, "read_correction", None)
        if reader is not None:
            value = reader(scope, scope_id) or (0, False, "none")
            self._epochs[(scope, scope_id)] = value
            return value
        return self._epochs.get((scope, scope_id), (0, False, "none"))

    def _persist(self, scope: str, scope_id: str, epoch: int, halted: bool, reason: str) -> None:
        writer = getattr(self._persistence, "write_correction", None)
        if writer is not None:
            writer(scope, scope_id, self._tenant_id, self._workspace_id, epoch, halted, reason, self._written_by, datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class PolicyInput:
    principal: PrincipalIdentity
    grant: CapabilityGrant | None
    capability: CapabilitySpec | None
    approval: ApprovalDecision | None = None
    now: datetime | None = None


class PolicyKernel:
    """Deterministic authority gate; provider/model output is never consulted."""

    def __init__(self, correction: CorrectionAuthority, policy_version: str = "policy-1") -> None:
        self.correction = correction
        self.policy_version = policy_version

    def decide(self, action: ActionContract, context: PolicyInput) -> PolicyDecision:
        now = context.now or datetime.now(timezone.utc)
        reasons: list[str] = []
        verdict = PolicyVerdict.ALLOW
        if action.policy_version != self.policy_version:
            verdict, reasons = PolicyVerdict.DENY, ["POLICY_VERSION_MISMATCH"]
        elif action.principal_id != context.principal.principal_id:
            verdict, reasons = PolicyVerdict.DENY, ["PRINCIPAL_MISMATCH"]
        elif action.tenant_id != context.principal.tenant_id or action.workspace_id != context.principal.workspace_id:
            verdict, reasons = PolicyVerdict.DENY, ["SCOPE_MISMATCH"]
        elif context.capability is None or context.grant is None:
            verdict, reasons = PolicyVerdict.DENY, ["CAPABILITY_NOT_GRANTED"]
        elif context.grant.status is not CapabilityGrantStatus.ACTIVE:
            verdict, reasons = PolicyVerdict.DENY, ["GRANT_REVOKED"]
        elif (
            context.grant.principal_id != action.principal_id
            or context.grant.tenant_id != action.tenant_id
            or context.grant.workspace_id != action.workspace_id
        ):
            verdict, reasons = PolicyVerdict.DENY, ["GRANT_SCOPE_MISMATCH"]
        elif context.grant.capability_id != action.capability_id or context.grant.capability_version != action.capability_version:
            verdict, reasons = PolicyVerdict.DENY, ["CAPABILITY_VERSION_MISMATCH"]
        elif action.risk_tier > context.grant.max_risk_tier:
            verdict, reasons = PolicyVerdict.DENY, ["RISK_TIER_EXCEEDED"]
        elif self.correction.halted(action.task_id, action.run_id, action.capability_id):
            verdict, reasons = PolicyVerdict.DENY, ["CORRECTION_HALTED"]
        elif context.capability.side_effect_guarantee.value == "NON_IDEMPOTENT_NON_QUERYABLE":
            verdict, reasons = PolicyVerdict.ESCALATE, ["NON_IDEMPOTENT_REQUIRES_HUMAN"]
        elif not action.estimated_budget.fits_within(context.grant.budget_limit):
            verdict, reasons = PolicyVerdict.DENY, ["BUDGET_EXCEEDED"]
        elif context.approval is not None and context.approval.action_digest != action.action_digest():
            verdict, reasons = PolicyVerdict.DENY, ["APPROVAL_DIGEST_MISMATCH"]
        elif context.approval is not None and context.approval.expires_at <= now:
            verdict, reasons = PolicyVerdict.DENY, ["APPROVAL_EXPIRED"]
        elif action.risk_tier >= 3 and (
            context.approval is None or context.approval.disposition is not ApprovalDisposition.APPROVE
        ):
            verdict, reasons = PolicyVerdict.ESCALATE, ["APPROVAL_REQUIRED"]
        elif now > context.grant.expires_at:
            verdict, reasons = PolicyVerdict.DENY, ["GRANT_EXPIRED"]
        else:
            reasons = ["ADMITTED"]
        return PolicyDecision(
            decision_id=f"decision-{uuid4()}",
            action_id=action.action_id,
            action_digest=action.action_digest(),
            principal_id=action.principal_id,
            tenant_id=action.tenant_id,
            workspace_id=action.workspace_id,
            verdict=verdict,
            policy_version=self.policy_version,
            reason_codes=tuple(reasons),
            correction_epochs=self.correction.snapshot(
                action.task_id, action.run_id, action.capability_id
            ),
            approval_id=context.approval.approval_id if context.approval else "approval:none",
            evaluated_at=now,
        )

    def permit(self, action: ActionContract, decision: PolicyDecision, grant: CapabilityGrant, lease_fence: int, now: datetime | None = None) -> ActionPermit:
        issued = now or datetime.now(timezone.utc)
        if decision.verdict is not PolicyVerdict.ALLOW:
            raise PermissionError(f"action is not allowed: {decision.reason_codes}")
        current = self.correction.snapshot(action.task_id, action.run_id, action.capability_id)
        if current != action.observed_correction_epochs or current != decision.correction_epochs:
            raise PermissionError("correction epoch changed before permit")
        return ActionPermit(
            permit_id=f"permit-{uuid4()}",
            action_id=action.action_id,
            action_digest=action.action_digest(),
            principal_id=action.principal_id,
            tenant_id=action.tenant_id,
            workspace_id=action.workspace_id,
            policy_decision_id=decision.decision_id,
            grant_id=grant.grant_id,
            correction_epochs=current,
            lease_fence=lease_fence,
            issued_at=issued,
            expires_at=issued + timedelta(minutes=5),
        )
