from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import RiskLevel  # noqa: E402
from agent_os_core.alert_agent import AlertAgent, AlertRule  # noqa: E402


class AlertAgentTest(unittest.TestCase):
    def test_no_rules_returns_none(self) -> None:
        agent = AlertAgent()
        self.assertIsNone(agent.evaluate("gmv", 100.0))

    def test_rule_fires_on_greater_than(self) -> None:
        agent = AlertAgent(
            rules=(
                AlertRule(
                    rule_id="gmv-spike",
                    metric_name="gmv",
                    threshold=1000.0,
                    comparison="gt",
                    action_type="notify",
                    connector_name="manual_review",
                    target_object="revenue_ops",
                    reason="GMV exceeded threshold",
                    expected_impact="notify operator",
                    risk_level=RiskLevel.R2,
                    approval_required=True,
                    approver_role="operator",
                ),
            )
        )
        proposal = agent.evaluate("gmv", 1500.0)
        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual(proposal.risk_level, RiskLevel.R2)
        self.assertEqual(proposal.connector_name, "manual_review")
        self.assertEqual(proposal.action_type, "notify")
        self.assertEqual(proposal.target_object, "revenue_ops")
        self.assertTrue(proposal.approval_required)
        self.assertEqual(proposal.approver_role, "operator")
        self.assertIn("gmv-spike", proposal.action_parameters["rule_id"])
        self.assertEqual(proposal.action_parameters["observed_value"], 1500.0)

    def test_rule_does_not_fire_below_threshold(self) -> None:
        agent = AlertAgent(
            rules=(
                AlertRule(
                    rule_id="gmv-spike",
                    metric_name="gmv",
                    threshold=1000.0,
                    comparison="gt",
                ),
            )
        )
        self.assertIsNone(agent.evaluate("gmv", 500.0))

    def test_comparison_operators(self) -> None:
        base = AlertRule(rule_id="r", metric_name="m", threshold=10.0)
        agent = AlertAgent()
        agent.add_rule(base)

        cases = [
            ("gte", 10.0, True),
            ("gte", 9.9, False),
            ("lt", 9.9, True),
            ("lt", 10.0, False),
            ("lte", 10.0, True),
            ("lte", 10.1, False),
            ("eq", 10.0, True),
            ("eq", 11.0, False),
        ]
        for comparison, value, should_fire in cases:
            with self.subTest(comparison=comparison, value=value):
                agent._rules = ()
                agent.add_rule(
                    AlertRule(
                        rule_id="r",
                        metric_name="m",
                        threshold=10.0,
                        comparison=comparison,
                    )
                )
                result = agent.evaluate("m", value)
                if should_fire:
                    self.assertIsNotNone(result)
                else:
                    self.assertIsNone(result)

    def test_only_matching_metric_fires(self) -> None:
        agent = AlertAgent(
            rules=(AlertRule(rule_id="r", metric_name="gmv", threshold=100.0, comparison="gt"),)
        )
        self.assertIsNone(agent.evaluate("revenue", 200.0))

    def test_default_reason_when_omitted(self) -> None:
        agent = AlertAgent(
            rules=(AlertRule(rule_id="r", metric_name="m", threshold=1.0, comparison="gt"),)
        )
        proposal = agent.evaluate("m", 2.0)
        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertIn("m", proposal.reason)
        self.assertIn("r", proposal.reason)

    def test_unsupported_comparison_raises(self) -> None:
        agent = AlertAgent(
            rules=(
                AlertRule(
                    rule_id="r",
                    metric_name="m",
                    threshold=1.0,
                    comparison="invalid",  # type: ignore[arg-type]
                ),
            )
        )
        with self.assertRaises(ValueError):
            agent.evaluate("m", 2.0)


if __name__ == "__main__":
    unittest.main()
