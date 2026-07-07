"""Alert Agent skeleton: rule-driven candidate ActionProposal generation.

The Alert Agent evaluates metric observations against a set of static rules and
produces a candidate :class:`ActionProposal` when a rule fires. It does NOT
execute actions — proposals enter the normal Trusted Loop approval path.

This module intentionally stays lightweight: rules are parsed from simple
dataclass definitions rather than an external DSL, and evaluation is fully
deterministic. The agent is a skeleton that future work can extend with
multi-metric windows, anomaly models, or causal attribution, but the MVP
contract is "metric + threshold + comparison → proposal".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from agent_os_contracts import ActionProposal, RiskLevel


@dataclass(frozen=True)
class AlertRule:
    """Static rule that fires when a metric value crosses a threshold.

    Args:
        rule_id: Unique identifier for this rule.
        metric_name: The metric to watch.
        threshold: The numeric threshold to compare against.
        comparison: One of ``gt`` (greater than), ``gte``, ``lt``, ``lte``,
            ``eq``.
        action_type: The connector action type to propose if the rule fires.
        connector_name: The connector that would handle the proposed action.
        target_object: Human-readable object the action targets.
        reason: Explanation shown to the operator when the rule fires.
        expected_impact: Description of the expected impact if executed.
        risk_level: Risk level of the proposed action.
        approval_required: Whether the proposal requires operator approval.
        approver_role: Optional role required to approve the proposal.
        action_parameters: Default parameters passed to the connector.
    """

    rule_id: str
    metric_name: str
    threshold: float
    comparison: Literal["gt", "gte", "lt", "lte", "eq"] = "gt"
    action_type: str = "notify"
    connector_name: str = "manual_review"
    target_object: str = ""
    reason: str = ""
    expected_impact: str = ""
    risk_level: RiskLevel = RiskLevel.R2
    approval_required: bool = True
    approver_role: str | None = "operator"
    action_parameters: dict[str, Any] = field(default_factory=dict)


class AlertAgent:
    """Lightweight rule engine that turns metric observations into proposals.

    The agent never mutates state or executes actions. It is designed to be
    called from a scheduler or stream consumer with ``(metric_name, value)``
    pairs and returns at most one proposal per evaluation.
    """

    def __init__(self, rules: tuple[AlertRule, ...] = ()) -> None:
        self._rules = tuple(rules)

    def add_rule(self, rule: AlertRule) -> None:
        """Register a new rule.

        Because :class:`AlertRule` is frozen and the internal tuple is replaced,
        the agent remains safely shareable across threads/coroutines.
        """
        self._rules = self._rules + (rule,)

    @property
    def rules(self) -> tuple[AlertRule, ...]:
        return self._rules

    def evaluate(self, metric_name: str, value: float) -> ActionProposal | None:
        """Evaluate all rules for ``metric_name`` and return the first firing proposal."""
        for rule in self._rules:
            if rule.metric_name != metric_name:
                continue
            if self._fires(rule, value):
                return self._to_proposal(rule, value)
        return None

    @staticmethod
    def _fires(rule: AlertRule, value: float) -> bool:
        comp = rule.comparison
        if comp == "gt":
            return value > rule.threshold
        if comp == "gte":
            return value >= rule.threshold
        if comp == "lt":
            return value < rule.threshold
        if comp == "lte":
            return value <= rule.threshold
        if comp == "eq":
            return value == rule.threshold
        raise ValueError(f"Unsupported comparison: {comp!r}")

    @staticmethod
    def _to_proposal(rule: AlertRule, value: float) -> ActionProposal:
        return ActionProposal(
            proposal_id=f"alert-proposal-{uuid4().hex[:12]}",
            evidence_chain_id=f"alert-evidence-{rule.rule_id}",
            target_object=rule.target_object or rule.metric_name,
            recommended_action=rule.action_type,
            reason=(
                rule.reason
                or f"Metric '{rule.metric_name}' ({value}) fired rule '{rule.rule_id}' "
                f"with {rule.comparison} threshold {rule.threshold}."
            ),
            risk_level=rule.risk_level,
            expected_impact=rule.expected_impact,
            approval_required=rule.approval_required,
            approver_role=rule.approver_role,
            connector_name=rule.connector_name,
            action_type=rule.action_type,
            action_parameters={
                "rule_id": rule.rule_id,
                "metric_name": rule.metric_name,
                "observed_value": value,
                "threshold": rule.threshold,
                "comparison": rule.comparison,
                **rule.action_parameters,
            },
        )
