"""E2 permission-mode gate over the frozen mode x tier x verdict matrix (M2).

Frozen source: GC §E2 — tier-1 READ_ONLY auto-pass is the pre-existing tier
default (no durable mode-provenance record); ACCEPT_IN_WORKSPACE policy
auto-allows tier-2 in-sandbox edits with provenance (the caller records
POLICY_VERDICT_RECORDED(ALLOW, basis=permission_mode, mode_event_id));
tier-3+ in-allowlist always requires a real human ApprovalDecision; anything
outside the capability allowlist is fail-closed denied in every mode, never
executable, not approvable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from agent_os_contracts import PermissionMode

from .permission_rules import PermissionDenyRule, active_deny_rule

ACTION_RISK_TIERS: dict[str, int] = {
    "workspace.read": 1,
    "workspace.search": 1,
    "workspace.run_tests": 1,
    "session.todo_write": 1,
    "workspace.edit": 2,
    "workspace.apply_patch": 2,
    "workspace.shell": 3,
}


class PermissionGateOutcome(str, Enum):
    TIER_DEFAULT_AUTO_PASS = "TIER_DEFAULT_AUTO_PASS"
    MODE_AUTO_ALLOW = "MODE_AUTO_ALLOW"
    REQUIRE_CONFIRM = "REQUIRE_CONFIRM"
    DENY_OUT_OF_ALLOWLIST = "DENY_OUT_OF_ALLOWLIST"
    DENY_BY_RULE = "DENY_BY_RULE"


@dataclass(frozen=True)
class PermissionGateDecision:
    outcome: PermissionGateOutcome
    risk_tier: int
    basis: Literal["permission_mode", "out_of_allowlist", "rule"] | None = None
    mode_event_id: str | None = None
    rule_id: str | None = None


def evaluate_permission_gate(
    *,
    capability_id: str,
    mode: PermissionMode,
    mode_event_id: str | None,
) -> PermissionGateDecision:
    """Translate the session permission mode into one frozen gate outcome."""
    if capability_id not in ACTION_RISK_TIERS:
        # Out-of-allowlist / sandbox escape: fail closed in every mode; the
        # caller records POLICY_VERDICT_RECORDED(DENY, basis=out_of_allowlist).
        return PermissionGateDecision(
            outcome=PermissionGateOutcome.DENY_OUT_OF_ALLOWLIST,
            risk_tier=0,
            basis="out_of_allowlist",
        )
    risk_tier = ACTION_RISK_TIERS[capability_id]
    if risk_tier <= 1:
        # Pre-existing tier-default policy; no mode-provenance record.
        return PermissionGateDecision(
            outcome=PermissionGateOutcome.TIER_DEFAULT_AUTO_PASS,
            risk_tier=risk_tier,
        )
    if risk_tier == 2 and mode == "ACCEPT_IN_WORKSPACE":
        return PermissionGateDecision(
            outcome=PermissionGateOutcome.MODE_AUTO_ALLOW,
            risk_tier=risk_tier,
            basis="permission_mode",
            mode_event_id=mode_event_id,
        )
    return PermissionGateDecision(
        outcome=PermissionGateOutcome.REQUIRE_CONFIRM,
        risk_tier=risk_tier,
    )


def apply_deny_rules(
    decision: PermissionGateDecision,
    *,
    capability_id: str,
    rules: Sequence[PermissionDenyRule],
    tenant_id: str,
    workspace_id: str,
) -> PermissionGateDecision:
    """Apply durable operator DENY rules — purely restrictive, never granting.

    A matching, unrevoked DENY rule downgrades any decision (including a mode
    auto-allow) to ``DENY_BY_RULE``. There is no rule that can ALLOW, auto-approve
    tier-3, or pre-empt C7; the frozen matrix itself is unchanged above.
    """

    rule = active_deny_rule(tuple(rules), capability_id, tenant_id, workspace_id)
    if rule is None:
        return decision
    return PermissionGateDecision(
        outcome=PermissionGateOutcome.DENY_BY_RULE,
        risk_tier=decision.risk_tier,
        basis="rule",
        rule_id=rule.rule_id,
    )
