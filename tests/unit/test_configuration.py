from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))

from agent_os_contracts import (  # noqa: E402
    AutoExecutionPolicy,
    AutoExecutionRule,
    PolicyApprovalRecord,
    RuntimeFeatureFlags,
)


class ConfigurationContractsTest(unittest.TestCase):
    def test_runtime_feature_flags_are_all_disabled_by_default(self) -> None:
        flags = RuntimeFeatureFlags()
        self.assertFalse(flags.data_fabric_v1)
        self.assertFalse(flags.domain_pack_sdk)
        self.assertFalse(flags.mcp_gateway)
        self.assertFalse(flags.full_bpm_workflow)
        self.assertFalse(flags.r4_r5_auto_execution)
        self.assertFalse(flags.frontend_f3_live_api)
        self.assertFalse(flags.temporal_orchestration)
        self.assertFalse(flags.opa_external_policy)
        self.assertFalse(flags.trino_federation)

    def test_is_enabled_looks_up_flag_safely(self) -> None:
        flags = RuntimeFeatureFlags(r4_r5_auto_execution=True)
        self.assertTrue(flags.is_enabled("r4_r5_auto_execution"))
        self.assertFalse(flags.is_enabled("mcp_gateway"))
        self.assertFalse(flags.is_enabled("not_a_flag"))

    def test_auto_execution_policy_selects_rule_or_default(self) -> None:
        rule = AutoExecutionRule(
            rule_id="rule-1",
            action_type="adjust_budget",
            risk_levels=("R2", "R3"),
            mode="policy_pre_approved",
            guard_conditions={"max_amount": 1000},
            compensating_action="reverse",
        )
        policy = AutoExecutionPolicy(
            version="v1",
            tenant_id="tenant-1",
            owner="finance",
            rules=(rule,),
        )
        self.assertEqual(policy.mode_for("adjust_budget", "R2"), "policy_pre_approved")
        self.assertEqual(policy.mode_for("adjust_budget", "R5"), "proposal_only")
        self.assertEqual(policy.mode_for("other_action", "R2"), "proposal_only")

    def test_policy_approval_record_revoke_returns_new_instance(self) -> None:
        record = PolicyApprovalRecord(
            record_id="par-1",
            trace_id="trace-1",
            proposal_id="proposal-1",
            rule_id="rule-1",
            policy_version="v1",
            tenant_id="tenant-1",
            created_at="2026-07-07T00:00:00Z",
        )
        self.assertEqual(record.status, "active")
        revoked = record.revoke("2026-07-07T01:00:00Z")
        self.assertEqual(revoked.status, "revoked")
        self.assertEqual(revoked.revoked_at, "2026-07-07T01:00:00Z")


if __name__ == "__main__":
    unittest.main()
