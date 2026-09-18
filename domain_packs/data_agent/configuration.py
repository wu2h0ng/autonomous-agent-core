from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeFeatureFlags:
    data_fabric_v1: bool = False
    domain_pack_sdk: bool = False
    mcp_gateway: bool = False
    full_bpm_workflow: bool = False
    r4_r5_auto_execution: bool = False
    frontend_f3_live_api: bool = False
    temporal_orchestration: bool = False
    opa_external_policy: bool = False
    trino_federation: bool = False

    def is_enabled(self, flag_name: str) -> bool:
        return getattr(self, flag_name, False)


@dataclass(frozen=True)
class AutoExecutionRule:
    rule_id: str
    action_type: str
    risk_levels: tuple[str, ...]
    mode: str  # "proposal_only" | "policy_pre_approved"
    guard_conditions: dict[str, Any]
    compensating_action: str | None


@dataclass(frozen=True)
class AutoExecutionPolicy:
    version: str
    tenant_id: str
    owner: str
    rules: tuple[AutoExecutionRule, ...]
    default_mode: str = "proposal_only"

    def mode_for(self, action_type: str, risk_level: str) -> str:
        for rule in self.rules:
            if rule.action_type == action_type and risk_level in rule.risk_levels:
                return rule.mode
        return self.default_mode


@dataclass(frozen=True)
class PolicyApprovalRecord:
    record_id: str
    trace_id: str
    proposal_id: str
    rule_id: str
    policy_version: str
    tenant_id: str
    created_at: str
    revoked_at: str | None = None
    status: str = "active"  # "active" | "revoked" | "consumed"

    def revoke(self, revoked_at: str) -> "PolicyApprovalRecord":
        return self.__class__(
            record_id=self.record_id,
            trace_id=self.trace_id,
            proposal_id=self.proposal_id,
            rule_id=self.rule_id,
            policy_version=self.policy_version,
            tenant_id=self.tenant_id,
            created_at=self.created_at,
            revoked_at=revoked_at,
            status="revoked",
        )


__all__ = [
    "AutoExecutionPolicy",
    "AutoExecutionRule",
    "PolicyApprovalRecord",
    "RuntimeFeatureFlags",
]
