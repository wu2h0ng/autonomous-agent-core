from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))

from agent_os_contracts import (  # noqa: E402
    ApprovalWorkflow,
    AutoExecutionPolicy,
    AutoExecutionRule,
    BusinessAgentTemplate,
    DomainPack,
    FederatedQueryPlan,
    LogicalView,
    MaterializationHint,
    McpServerRegistration,
    McpToolContract,
    OperationContract,
    PolicyApprovalRecord,
    QueryPlan,
    RuntimeFeatureFlags,
    WorkflowEvent,
    WorkflowInstance,
    WorkflowStep,
)


class ContractsStagedOutCapabilitiesTest(unittest.TestCase):
    def test_runtime_feature_flags_default_to_false_and_is_enabled(self) -> None:
        flags = RuntimeFeatureFlags()
        self.assertFalse(flags.data_fabric_v1)
        self.assertFalse(flags.domain_pack_sdk)
        self.assertFalse(flags.mcp_gateway)
        self.assertFalse(flags.full_bpm_workflow)
        self.assertFalse(flags.r4_r5_auto_execution)
        self.assertFalse(flags.frontend_f3_live_api)
        self.assertTrue(flags.is_enabled("data_fabric_v1") is False)
        self.assertTrue(RuntimeFeatureFlags(mcp_gateway=True).is_enabled("mcp_gateway"))
        self.assertFalse(flags.is_enabled("unknown_flag"))

    def test_auto_execution_policy_mode_for(self) -> None:
        rule = AutoExecutionRule(
            rule_id="rule-1",
            action_type="adjust_budget",
            risk_levels=("R2",),
            mode="policy_pre_approved",
            guard_conditions={"max_amount": 1000},
            compensating_action="reverse_budget_adjustment",
        )
        policy = AutoExecutionPolicy(
            version="v1",
            tenant_id="tenant-1",
            owner="finance_ops",
            rules=(rule,),
        )
        self.assertEqual(policy.mode_for("adjust_budget", "R2"), "policy_pre_approved")
        self.assertEqual(policy.mode_for("adjust_budget", "R5"), "proposal_only")
        self.assertEqual(policy.mode_for("unknown_action", "R2"), "proposal_only")

    def test_policy_approval_record_can_be_created_and_revoked(self) -> None:
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
        self.assertIsNone(record.revoked_at)

        revoked = record.revoke("2026-07-07T01:00:00Z")
        self.assertEqual(revoked.status, "revoked")
        self.assertEqual(revoked.revoked_at, "2026-07-07T01:00:00Z")
        self.assertEqual(revoked.record_id, record.record_id)

    def test_domain_pack_and_business_agent_template_construction(self) -> None:
        pack = DomainPack(
            pack_id="pack-1",
            name="Content Commerce Pack",
            version="v1",
            domain="content_commerce",
            owner="domain_team",
            metric_contracts=("gmv", "spend", "roi"),
            business_agent_templates=("bat-1",),
            operation_contracts=("oc-1",),
            eval_pack_ids=("eval-1",),
            state="active",
        )
        self.assertEqual(pack.state, "active")
        self.assertEqual(pack.metric_contracts, ("gmv", "spend", "roi"))

        template = BusinessAgentTemplate(
            template_id="bat-1",
            name="Commerce Analyst",
            domain="content_commerce",
            responsibilities=("monitor_gmv", "flag_anomalies"),
            required_evidence=("evidence_chain", "sql_safety"),
            allowed_action_types=("propose", "notify"),
            default_approval_policy={"R4": "required", "R5": "required"},
        )
        self.assertEqual(template.template_id, "bat-1")
        self.assertEqual(template.default_approval_policy["R4"], "required")

    def test_mcp_server_registration_and_tool_contract(self) -> None:
        server = McpServerRegistration(
            server_id="mcp-1",
            name="Analytics MCP",
            transport_url="http://localhost:8080/sse",
            owner="platform",
            tenant_id="tenant-1",
            allowed_scopes=("read_metrics",),
            risk_ceiling="R2",
            state="active",
        )
        self.assertEqual(server.state, "active")
        self.assertEqual(server.allowed_scopes, ("read_metrics",))

        tool = McpToolContract(
            tool_id="tool-1",
            server_id="mcp-1",
            name="query_metric",
            description="Query a metric by name.",
            input_schema={"type": "object", "properties": {}},
            risk_level="R2",
            dry_run_supported=True,
        )
        self.assertEqual(tool.server_id, "mcp-1")
        self.assertTrue(tool.dry_run_supported)

    def test_approval_workflow_construction_and_state(self) -> None:
        step = WorkflowStep(
            step_id="step-1",
            step_type="approval",
            approver_role="manager",
            timeout_seconds=3600,
            next_step_id="step-2",
        )
        workflow = ApprovalWorkflow(
            workflow_id="wf-1",
            name="Budget Approval",
            action_type="adjust_budget",
            risk_levels=("R3", "R4"),
            steps=(step,),
            state="active",
        )
        self.assertEqual(workflow.state, "active")
        self.assertEqual(workflow.steps[0].step_id, "step-1")
        self.assertEqual(workflow.steps[0].approver_role, "manager")

        event = WorkflowEvent(
            event_id="evt-1",
            instance_id="wi-1",
            step_id="step-1",
            event_type="approved",
            actor="manager-1",
            timestamp="2026-07-07T00:00:00Z",
            payload={"comment": "looks good"},
        )
        instance = WorkflowInstance(
            instance_id="wi-1",
            workflow_id="wf-1",
            proposal_id="proposal-1",
            current_step_id="step-1",
            state="pending",
            events=(event,),
        )
        self.assertEqual(instance.state, "pending")
        self.assertEqual(instance.events[0].event_type, "approved")

    def test_operation_contract_backward_compatibility_and_new_fields(self) -> None:
        contract = OperationContract(
            operation_id="op-1",
            name="send_report",
            target_connector="email",
            risk_level="R2",
            approval_required=False,
        )
        self.assertFalse(contract.auto_executable)
        self.assertEqual(contract.required_policy_guardrails, ())
        self.assertEqual(contract.action_type, "propose")

    def test_logical_view_materialization_hint_and_federated_query_plan(self) -> None:
        view = LogicalView(
            view_id="lv-1",
            name="Unified GMV",
            source_providers=("warehouse-1", "warehouse-2"),
            owner="data_platform",
            view_sql="select * from warehouse_1.gmv union all select * from warehouse_2.gmv",
        )
        self.assertEqual(view.view_id, "lv-1")
        self.assertEqual(view.source_providers, ("warehouse-1", "warehouse-2"))

        hint = MaterializationHint(
            hint_id="mh-1",
            data_product_id="dp-1",
            strategy="view",
            refresh_policy="hourly",
        )
        self.assertEqual(hint.strategy, "view")

        sub_query = QueryPlan(
            metric_name="gmv",
            sql="select sum(amount) from sales.orders",
            parameters={"start_date": "2026-07-01", "end_date": "2026-07-07"},
        )
        plan = FederatedQueryPlan(
            plan_id="fqp-1",
            sub_queries=(sub_query,),
            combine_strategy="union_all",
            estimated_cost_hint="low",
        )
        self.assertEqual(plan.plan_id, "fqp-1")
        self.assertEqual(plan.sub_queries[0].metric_name, "gmv")


if __name__ == "__main__":
    unittest.main()
