"""R4/R5 auto-execution PolicyEngine (workstream E / ADR-0012).

Evaluates R4/R5 business actions against a tenant ``AutoExecutionPolicy`` and
decides whether an action may execute automatically (policy pre-approval) or
must remain proposal-only (human approval).

Behind ``RuntimeFeatureFlags.r4_r5_auto_execution`` (default ``False``). When
off, every evaluation returns ``proposal_only`` (the MVP default).

Enforcement order (fail-closed at every step):

1. feature flag enabled
2. tenant policy registered and a matching rule exists
3. ``OperationContract.auto_executable``
4. rollback (R4) / compensating action (R5) declared
5. corrigibility pause shell not paused (C7 supremacy — non-negotiable)
6. guard conditions: dry-run success, evidence completeness, confidence
   floor, metric delta bound (and any unknown guard fails closed)

A successful evaluation mints a durable, revocable ``PolicyApprovalRecord``
bound to the proposal, operation evidence, and policy version. A revoked,
consumed, or stale-version record is invalid and blocks execution.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from agent_os_contracts import (
    ActionProposal,
    AutoExecutionPolicy,
    AutoExecutionRule,
    OperationContract,
    OperationState,
    PolicyApprovalRecord,
    RuntimeFeatureFlags,
)

from .operation_trace import OperationTraceBuilder

__all__ = [
    "AutoExecutionPolicyStore",
    "AutoExecutionPolicyStorePort",
    "GuardrailInput",
    "PolicyApprovalConsumed",
    "PolicyApprovalRecordStorePort",
    "PolicyApprovalRecordStore",
    "PolicyEngine",
    "PolicyEvaluationResult",
]

_GUARD_REASON = {
    "dry_run_success": "dry_run_failed",
    "evidence_complete": "evidence_incomplete",
}


def _default_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class GuardrailInput:
    """Runtime inputs the PolicyEngine evaluates guard conditions against."""

    dry_run_success: bool = False
    evidence_complete: bool = False
    confidence: float = 0.0
    metric_delta_pct: float | None = None


@dataclass(frozen=True)
class PolicyEvaluationResult:
    proposal_id: str
    decision: str  # "proposal_only" | "policy_pre_approved" | "denied"
    rule_id: str | None
    reason: str
    guardrails_checked: dict[str, bool]
    policy_approval_id: str | None = None


class PolicyApprovalRecordStorePort(ABC):
    """Port for durable policy-approval-record lifecycle storage.

    OS Core owns this Port; the in-memory implementation lives in OS Core and
    a SQLAlchemy adapter lives in the persistence package. Durable adapters
    must round-trip ``PolicyApprovalRecord`` (frozen) and preserve the
    active/revoked/consumed lifecycle and idempotency semantics.
    """

    @abstractmethod
    def save(self, record: PolicyApprovalRecord) -> PolicyApprovalRecord: ...

    @abstractmethod
    def get(self, record_id: str, *, tenant_id: str = "default") -> PolicyApprovalRecord | None: ...

    @abstractmethod
    def revoke(
        self, record_id: str, revoked_at: str, *, tenant_id: str = "default"
    ) -> PolicyApprovalRecord: ...

    @abstractmethod
    def consume(self, record_id: str, *, tenant_id: str = "default") -> PolicyApprovalRecord: ...

    @abstractmethod
    def is_active(
        self, record_id: str, *, tenant_id: str = "default", policy_version: str
    ) -> bool: ...

    @abstractmethod
    def active_for_proposal(
        self, proposal_id: str, *, tenant_id: str, policy_version: str
    ) -> PolicyApprovalRecord | None: ...


class PolicyApprovalConsumed(Exception):
    """Raised when a policy approval cannot be consumed (paused / not active)."""

    def __init__(self, record_id: str, *, reason: str) -> None:
        super().__init__(f"{reason}: {record_id}")
        self.record_id = record_id
        self.reason = reason


class AutoExecutionPolicyStorePort(ABC):
    """Port for durable tenant auto-execution policy storage (workstream E)."""

    @abstractmethod
    def save(self, policy: AutoExecutionPolicy) -> AutoExecutionPolicy: ...

    @abstractmethod
    def get(self, tenant_id: str) -> AutoExecutionPolicy | None: ...


class AutoExecutionPolicyStore(AutoExecutionPolicyStorePort):
    """In-memory auto-execution policy store."""

    def __init__(self) -> None:
        self._policies: dict[str, AutoExecutionPolicy] = {}

    def save(self, policy: AutoExecutionPolicy) -> AutoExecutionPolicy:
        self._policies[policy.tenant_id] = policy
        return policy

    def get(self, tenant_id: str) -> AutoExecutionPolicy | None:
        return self._policies.get(tenant_id)


class PolicyApprovalRecordStore(PolicyApprovalRecordStorePort):
    """In-memory store for ``PolicyApprovalRecord`` lifecycle."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], PolicyApprovalRecord] = {}

    @staticmethod
    def _tenant_key(record_id: str, *, tenant_id: str) -> tuple[str, str]:
        return (tenant_id or "default", record_id)

    def save(self, record: PolicyApprovalRecord) -> PolicyApprovalRecord:
        key = self._tenant_key(record.record_id, tenant_id=record.tenant_id or "default")
        self._records[key] = record
        return record

    def get(self, record_id: str, *, tenant_id: str = "default") -> PolicyApprovalRecord | None:
        return self._records.get(self._tenant_key(record_id, tenant_id=tenant_id))

    def revoke(
        self, record_id: str, revoked_at: str, *, tenant_id: str = "default"
    ) -> PolicyApprovalRecord:
        key = self._tenant_key(record_id, tenant_id=tenant_id)
        record = self._records.get(key)
        if record is None:
            raise KeyError(f"policy approval record not found: {record_id}")
        updated = record.revoke(revoked_at)
        self._records[key] = updated
        return updated

    def consume(self, record_id: str, *, tenant_id: str = "default") -> PolicyApprovalRecord:
        key = self._tenant_key(record_id, tenant_id=tenant_id)
        record = self._records.get(key)
        if record is None:
            raise KeyError(f"policy approval record not found: {record_id}")
        updated = replace(record, status="consumed")
        self._records[key] = updated
        return updated

    def is_active(
        self, record_id: str, *, tenant_id: str = "default", policy_version: str
    ) -> bool:
        record = self._records.get(self._tenant_key(record_id, tenant_id=tenant_id))
        if record is None:
            return False
        if record.status != "active":
            return False
        if record.policy_version != policy_version:
            return False
        return True

    def active_for_proposal(
        self, proposal_id: str, *, tenant_id: str, policy_version: str
    ) -> PolicyApprovalRecord | None:
        """Return the active record for a proposal, if one exists and is valid."""
        for record in self._records.values():
            if (
                record.proposal_id == proposal_id
                and record.tenant_id == tenant_id
                and record.status == "active"
                and record.policy_version == policy_version
            ):
                return record
        return None


class PolicyEngine:
    """Evaluates R4/R5 actions against tenant auto-execution policy."""

    def __init__(
        self,
        feature_flags: RuntimeFeatureFlags,
        *,
        record_store: PolicyApprovalRecordStorePort | None = None,
        policy_store: AutoExecutionPolicyStorePort | None = None,
        shell: Any | None = None,
        now: Callable[[], str] | None = None,
        trace_builder: OperationTraceBuilder | None = None,
    ) -> None:
        self.feature_flags = feature_flags
        self._store = record_store or PolicyApprovalRecordStore()
        self._policy_store = policy_store
        self._shell = shell
        self._now = now or _default_now
        self._policies: dict[str, AutoExecutionPolicy] = {}
        self._counter = 0
        self._trace_builder = trace_builder or OperationTraceBuilder()
        self._traces: dict[str, Any] = {}  # proposal_id -> OperationTrace

    # -- registration ------------------------------------------------------

    def register_policy(self, policy: AutoExecutionPolicy) -> None:
        self._policies[policy.tenant_id] = policy
        if self._policy_store is not None:
            self._policy_store.save(policy)

    @property
    def record_store(self) -> PolicyApprovalRecordStore:
        return self._store

    # -- helpers -----------------------------------------------------------

    def _paused(self) -> bool:
        if self._shell is None:
            return False
        return bool(self._shell.paused)

    def _ensure_trace(self, proposal: ActionProposal, trace_id: str) -> Any:
        trace = self._traces.get(proposal.proposal_id)
        if trace is None:
            trace = self._trace_builder.open_trace(
                trace_id=trace_id,
                proposal_id=proposal.proposal_id,
                evidence_chain_id=proposal.evidence_chain_id,
                operation_id=None,
            )
            self._traces[proposal.proposal_id] = trace
        return trace

    def _trace_step(self, proposal_id: str, state: OperationState, event: dict[str, Any]) -> None:
        trace = self._traces.get(proposal_id)
        if trace is None:
            return
        self._traces[proposal_id] = self._trace_builder.update_trace(trace, state, event)

    def trace_for(self, proposal_id: str) -> Any | None:
        return self._traces.get(proposal_id)

    def _matching_rule(
        self, policy: AutoExecutionPolicy, action_type: str, risk_level: str
    ) -> AutoExecutionRule | None:
        for rule in policy.rules:
            if rule.action_type == action_type and risk_level in rule.risk_levels:
                return rule
        return None

    def _has_rollback_compensation(self, operation: OperationContract) -> bool:
        has_comp = bool(operation.compensating_action)
        if operation.risk_level == "R5":
            return has_comp
        return operation.rollback_supported or has_comp

    def _check_guard(self, key: str, expected: Any, guardrails: GuardrailInput) -> bool:
        if key == "dry_run_success":
            return guardrails.dry_run_success == bool(expected)
        if key == "evidence_complete":
            return guardrails.evidence_complete == bool(expected)
        if key == "confidence_min":
            return guardrails.confidence >= float(expected)
        if key == "max_delta_pct":
            if guardrails.metric_delta_pct is None:
                return False
            return abs(guardrails.metric_delta_pct) <= float(expected)
        # Unknown guard key: fail-closed.
        return False

    def _next_record_id(self) -> str:
        self._counter += 1
        return f"par-{self._counter}"

    # -- evaluation --------------------------------------------------------

    def evaluate(
        self,
        proposal: ActionProposal,
        operation: OperationContract,
        guardrails: GuardrailInput,
        *,
        tenant_id: str,
        trace_id: str,
    ) -> PolicyEvaluationResult:
        def _result(
            decision: str,
            reason: str,
            rule_id: str | None = None,
            approval_id: str | None = None,
            checked: dict[str, bool] | None = None,
        ) -> PolicyEvaluationResult:
            return PolicyEvaluationResult(
                proposal_id=proposal.proposal_id,
                decision=decision,
                rule_id=rule_id,
                reason=reason,
                guardrails_checked=checked or {},
                policy_approval_id=approval_id,
            )

        if not self.feature_flags.r4_r5_auto_execution:
            return _result("proposal_only", "feature_disabled")

        policy = self._policies.get(tenant_id)
        if policy is None:
            return _result("proposal_only", "no_policy")

        rule = self._matching_rule(policy, proposal.action_type, operation.risk_level)
        if rule is None:
            return _result("proposal_only", "no_matching_rule")

        if rule.mode != "policy_pre_approved":
            return _result("proposal_only", "proposal_only_rule", rule.rule_id)

        if not operation.auto_executable:
            return _result("denied", "not_auto_executable", rule.rule_id)

        if not self._has_rollback_compensation(operation):
            return _result("denied", "missing_rollback_compensation", rule.rule_id)

        if self._paused():
            return _result("denied", "paused", rule.rule_id)

        self._ensure_trace(proposal, trace_id)
        self._trace_step(
            proposal.proposal_id,
            OperationState.POLICY_EVALUATED,
            {"step": "policy_evaluated", "rule_id": rule.rule_id},
        )

        checked: dict[str, bool] = {}
        for key, expected in rule.guard_conditions.items():
            ok = self._check_guard(key, expected, guardrails)
            checked[key] = ok
            if not ok:
                reason = _GUARD_REASON.get(key, f"guardrail_failed:{key}")
                self._trace_step(
                    proposal.proposal_id,
                    OperationState.REJECTED,
                    {"step": "rejected", "reason": reason},
                )
                return _result("denied", reason, rule.rule_id, checked=checked)

        # F2 (AR-20260707): idempotent mint — reuse an existing active record for
        # this proposal rather than minting a second consumable record on retry.
        existing = self._store.active_for_proposal(
            proposal.proposal_id,
            tenant_id=tenant_id,
            policy_version=policy.version,
        )
        if existing is not None:
            return _result(
                "policy_pre_approved",
                "pre_approved",
                rule.rule_id,
                approval_id=existing.record_id,
                checked=checked,
            )

        self._trace_step(
            proposal.proposal_id,
            OperationState.POLICY_PRE_APPROVED,
            {"step": "policy_pre_approved", "rule_id": rule.rule_id},
        )
        record_id = self._next_record_id()
        record = PolicyApprovalRecord(
            record_id=record_id,
            trace_id=trace_id,
            proposal_id=proposal.proposal_id,
            rule_id=rule.rule_id,
            policy_version=policy.version,
            tenant_id=tenant_id,
            created_at=self._now(),
        )
        self._store.save(record)
        return _result(
            "policy_pre_approved",
            "pre_approved",
            rule.rule_id,
            approval_id=record_id,
            checked=checked,
        )

    # -- approval lifecycle ------------------------------------------------

    def is_approval_valid(self, record_id: str, *, tenant_id: str) -> bool:
        policy = self._policies.get(tenant_id)
        version = policy.version if policy is not None else ""
        return self._store.is_active(
            record_id, tenant_id=tenant_id, policy_version=version
        )

    def revoke_approval(self, record_id: str, *, tenant_id: str) -> PolicyApprovalRecord:
        return self._store.revoke(record_id, self._now(), tenant_id=tenant_id)

    def consume_approval(self, record_id: str, *, tenant_id: str) -> PolicyApprovalRecord:
        """Consume a policy approval record at execution time.

        F1 (AR-20260707): re-checks the pause shell (C7 supremacy) and record
        validity before consuming. Fails closed instead of silently consuming.
        """
        if self._paused():
            raise PolicyApprovalConsumed(record_id, reason="paused_at_consume")
        record = self._store.get(record_id, tenant_id=tenant_id)
        if record is None:
            raise KeyError(f"policy approval record not found: {record_id}")
        policy = self._policies.get(tenant_id)
        version = policy.version if policy is not None else ""
        if not self._store.is_active(
            record_id, tenant_id=tenant_id, policy_version=version
        ):
            raise PolicyApprovalConsumed(record_id, reason="record_not_active")
        consumed = self._store.consume(record_id, tenant_id=tenant_id)
        self._trace_step(
            consumed.proposal_id,
            OperationState.EXECUTED,
            {"step": "executed", "record_id": record_id},
        )
        return consumed

    def apply_decision(
        self, proposal: ActionProposal, result: PolicyEvaluationResult
    ) -> ActionProposal:
        mode = (
            "policy_pre_approved" if result.decision == "policy_pre_approved" else "proposal_only"
        )
        return replace(proposal, execution_mode=mode)
