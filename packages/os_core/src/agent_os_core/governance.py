from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Protocol
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
    ExternalPolicyAdvice,
    ExternalPolicyQuery,
    PolicyDecision,
    PolicyVerdict,
    PrincipalIdentity,
    content_digest,
)
from pydantic import ValidationError


POLICY_KERNEL_V1_SPEC = {
    "schema": "AGENT-OS-POLICY-KERNEL-CONTRACT-V1",
    "version": "policy-1",
    "authority_source": "PRODUCT_DETERMINISTIC_RULES",
    "model_final_authority": False,
    "required_bindings": (
        "principal",
        "tenant",
        "workspace",
        "capability-version",
        "risk-tier",
        "budget",
        "correction-epochs",
        "approval-when-required",
    ),
}
POLICY_KERNEL_V1_DIGEST = content_digest(POLICY_KERNEL_V1_SPEC)


class CorrectionGuard(Protocol):
    """Minimal correction contract required by local effect writers."""

    def snapshot(
        self,
        task_id: str,
        run_id: str,
        capability_id: str,
    ) -> CorrectionEpochVector: ...

    def halted(self, task_id: str, run_id: str, capability_id: str) -> bool: ...

    def guard_unchanged(
        self,
        task_id: str,
        run_id: str,
        capability_id: str,
        observed_epochs: CorrectionEpochVector,
    ) -> AbstractContextManager[bool]: ...


class ExternalPolicyBackend(Protocol):
    """OPA/Cedar-shaped enforcement backend without policy-root authority."""

    backend_id: str
    version: int

    def evaluate(self, query: ExternalPolicyQuery) -> object: ...


class CorrectionAuthority:
    """Externally-owned correction epochs. Acting code receives snapshots only."""

    def __init__(self, persistence: object | None = None, *, tenant_id: str = "tenant:local", workspace_id: str = "workspace:local", written_by: str = "principal") -> None:
        self._epochs: dict[tuple[str, str], tuple[int, bool, str]] = {}
        self._lock = RLock()
        self._persistence = persistence
        self._tenant_id = tenant_id
        self._workspace_id = workspace_id
        self._written_by = written_by

    def snapshot(self, task_id: str, run_id: str, capability_id: str) -> CorrectionEpochVector:
        with self._lock:
            return CorrectionEpochVector(
                task_epoch=self._epoch("task", task_id)[0],
                run_epoch=self._epoch("run", run_id)[0],
                capability_epoch=self._epoch("capability", capability_id)[0],
            )

    def halted(self, task_id: str, run_id: str, capability_id: str) -> bool:
        with self._lock:
            return any(
                self._epoch(scope, value)[1]
                for scope, value in (
                    ("task", task_id),
                    ("run", run_id),
                    ("capability", capability_id),
                )
            )

    @contextmanager
    def guard_unchanged(
        self,
        task_id: str,
        run_id: str,
        capability_id: str,
        observed_epochs: CorrectionEpochVector,
    ) -> Iterator[bool]:
        """Linearize a local effect against correction changes on this authority."""
        with self._lock:
            unchanged = (
                self.snapshot(task_id, run_id, capability_id) == observed_epochs
                and not self.halted(task_id, run_id, capability_id)
            )
            yield unchanged

    def correct(self, scope: str, scope_id: str, reason: str) -> int:
        with self._lock:
            return self._advance(scope, scope_id, halted=True, reason=reason)

    def resume(self, scope: str, scope_id: str, reason: str = "resumed") -> int:
        with self._lock:
            return self._advance(scope, scope_id, halted=False, reason=reason)

    def _advance(
        self,
        scope: str,
        scope_id: str,
        *,
        halted: bool,
        reason: str,
    ) -> int:
        if scope not in {"task", "run", "capability"}:
            raise ValueError("unsupported correction scope")
        advance = getattr(self._persistence, "advance_correction", None)
        if advance is not None:
            value = advance(
                scope,
                scope_id,
                self._tenant_id,
                self._workspace_id,
                halted,
                reason,
                self._written_by,
                datetime.now(timezone.utc).isoformat(),
            )
            self._epochs[(scope, scope_id)] = value
            return value[0]
        epoch, _, _ = self._epoch(scope, scope_id)
        self._epochs[(scope, scope_id)] = (epoch + 1, halted, reason)
        self._persist(scope, scope_id, epoch + 1, halted, reason)
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

    def __init__(
        self,
        correction: CorrectionAuthority,
        policy_version: str = "policy-1",
        external_backend: ExternalPolicyBackend | None = None,
    ) -> None:
        if external_backend is not None and (
            not external_backend.backend_id.strip() or external_backend.version < 1
        ):
            raise ValueError("external policy backend identity is invalid")
        self.correction = correction
        self.policy_version = policy_version
        self.external_backend = external_backend

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
        internal = PolicyDecision(
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
        if internal.verdict is not PolicyVerdict.ALLOW or self.external_backend is None:
            return internal
        assert context.grant is not None
        policy_request_id = f"external-policy-request:{uuid4()}"
        policy_nonce = str(uuid4())
        query = ExternalPolicyQuery(
            policy_request_id=policy_request_id,
            backend_id=self.external_backend.backend_id,
            backend_version=self.external_backend.version,
            action_id=action.action_id,
            action_digest=action.action_digest(),
            task_id=action.task_id,
            run_id=action.run_id,
            principal_id=action.principal_id,
            tenant_id=action.tenant_id,
            workspace_id=action.workspace_id,
            capability_id=action.capability_id,
            capability_version=action.capability_version,
            grant_id=context.grant.grant_id,
            policy_version=self.policy_version,
            risk_tier=action.risk_tier,
            correction_epochs=internal.correction_epochs,
            nonce=policy_nonce,
            issued_at=now,
            expires_at=now + timedelta(seconds=30),
        )

        def external_denial(reason: str) -> PolicyDecision:
            return internal.model_copy(
                update={
                    "decision_id": f"decision-{uuid4()}",
                    "verdict": PolicyVerdict.DENY,
                    "reason_codes": (reason,),
                }
            )

        try:
            raw_advice = self.external_backend.evaluate(query)
        except Exception:
            return external_denial("EXTERNAL_POLICY_UNAVAILABLE")
        try:
            advice = ExternalPolicyAdvice.model_validate(raw_advice)
        except (TypeError, ValidationError, ValueError):
            return external_denial("EXTERNAL_POLICY_MALFORMED")
        exact = (
            advice.backend_id == query.backend_id,
            advice.backend_version == query.backend_version,
            advice.action_id == query.action_id,
            advice.principal_id == query.principal_id,
            advice.tenant_id == query.tenant_id,
            advice.workspace_id == query.workspace_id,
        )
        if not all(exact):
            return external_denial("EXTERNAL_POLICY_SCOPE_MISMATCH")
        binding = (
            advice.policy_query_digest == query.query_digest(),
            advice.policy_request_id == query.policy_request_id,
            advice.nonce == query.nonce,
            advice.issued_at == query.issued_at,
            advice.expires_at == query.expires_at,
            advice.issued_at <= now < advice.expires_at,
        )
        if not all(binding):
            return external_denial("EXTERNAL_POLICY_BINDING_MISMATCH")
        if advice.verdict == "DENY":
            return external_denial("EXTERNAL_POLICY_DENY")
        return internal

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
