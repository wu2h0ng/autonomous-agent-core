"""Unit tests for staged_out_service management plane."""

from __future__ import annotations

from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api_server" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_api import staged_out_service  # noqa: E402
from agent_os_contracts import RuntimeFeatureFlags  # noqa: E402
from agent_os_core.agent_runtime import AgentRunContext  # noqa: E402
from agent_os_core.mcp_gateway import McpGatewayRegistry, McpToolRouter  # noqa: E402
from agent_os_core.policy_engine import AutoExecutionPolicyStore, PolicyEngine  # noqa: E402
from agent_os_core.workflow import WorkflowRuntime  # noqa: E402
from agent_os_core.workflow_store import InMemoryWorkflowStore  # noqa: E402


class StagedOutServiceTest(unittest.TestCase):
    def test_register_workflow_disabled_when_flag_off(self) -> None:
        result = staged_out_service.register_workflow(
            workflow_runtime=None,
            flags=RuntimeFeatureFlags(),
            tenant_id="default",
            body={"workflow_id": "wf", "name": "n", "action_type": "execute", "steps": []},
        )
        self.assertEqual(result["code"], "FEATURE_DISABLED")

    def test_register_workflow_when_flag_on(self) -> None:
        flags = RuntimeFeatureFlags(full_bpm_workflow=True)
        runtime = WorkflowRuntime(flags, workflow_store=InMemoryWorkflowStore())
        result = staged_out_service.register_workflow(
            workflow_runtime=runtime,
            flags=flags,
            tenant_id="default",
            body={
                "workflow_id": "wf-1",
                "name": "Test",
                "action_type": "execute",
                "risk_levels": ["R3"],
                "state": "active",
                "steps": [{"step_id": "s1", "step_type": "approval", "approver_role": "mgr"}],
            },
        )
        self.assertEqual(result["status"], "ok")

    def test_register_workflow_runtime_unavailable_when_flag_on(self) -> None:
        result = staged_out_service.register_workflow(
            workflow_runtime=None,
            flags=RuntimeFeatureFlags(full_bpm_workflow=True),
            tenant_id="default",
            body={"workflow_id": "wf", "name": "n", "action_type": "execute", "steps": []},
        )
        self.assertEqual(result["code"], "RUNTIME_UNAVAILABLE")

    def test_list_workflows_requires_store_when_flag_on(self) -> None:
        result = staged_out_service.list_workflows(
            workflow_store=None,
            flags=RuntimeFeatureFlags(full_bpm_workflow=True),
            tenant_id="default",
        )
        self.assertEqual(result["code"], "STORE_UNAVAILABLE")

    def test_workflow_instance_operations_are_safe_json(self) -> None:
        flags = RuntimeFeatureFlags(full_bpm_workflow=True)
        runtime = WorkflowRuntime(flags, workflow_store=InMemoryWorkflowStore())
        staged_out_service.register_workflow(
            workflow_runtime=runtime,
            flags=flags,
            tenant_id="default",
            body={
                "workflow_id": "wf-ops",
                "name": "Ops",
                "action_type": "execute",
                "risk_levels": ["R3"],
                "state": "active",
                "steps": [
                    {
                        "step_id": "s1",
                        "step_type": "approval",
                        "approver_role": "manager",
                        "timeout_seconds": 0,
                        "next_step_id": "s2",
                        "fallback_step_id": "s2",
                    },
                    {
                        "step_id": "s2",
                        "step_type": "approval",
                        "approver_role": "director",
                    },
                ],
            },
        )

        started = staged_out_service.start_workflow_instance(
            workflow_runtime=runtime,
            flags=flags,
            tenant_id="default",
            workflow_id="wf-ops",
            body={"proposal_id": "proposal-1", "started_by": "tester"},
        )
        self.assertEqual(started["status"], "ok")
        approve_instance_id = started["instance"]["instance_id"]

        approved = staged_out_service.workflow_instance_operation(
            workflow_runtime=runtime,
            flags=flags,
            tenant_id="default",
            instance_id=approve_instance_id,
            operation="approve",
            body={"actor": "manager", "reason": "looks good"},
        )
        self.assertEqual(approved["status"], "ok")
        self.assertEqual(approved["instance"]["current_step_id"], "s2")
        self.assertEqual(approved["instance"]["assigned_role"], "director")
        self.assertEqual(approved["instance"]["events"][-1]["event_type"], "approved")

        delegated_instance_id = staged_out_service.start_workflow_instance(
            workflow_runtime=runtime,
            flags=flags,
            tenant_id="default",
            workflow_id="wf-ops",
            body={"proposal_id": "proposal-2"},
        )["instance"]["instance_id"]
        delegated = staged_out_service.workflow_instance_operation(
            workflow_runtime=runtime,
            flags=flags,
            tenant_id="default",
            instance_id=delegated_instance_id,
            operation="delegate",
            body={"actor": "manager", "to_role": "backup_manager"},
        )
        self.assertEqual(delegated["instance"]["assigned_role"], "backup_manager")
        self.assertEqual(
            delegated["instance"]["events"][-1]["payload"]["to_role"], "backup_manager"
        )

        rejected_instance_id = staged_out_service.start_workflow_instance(
            workflow_runtime=runtime,
            flags=flags,
            tenant_id="default",
            workflow_id="wf-ops",
            body={"proposal_id": "proposal-3"},
        )["instance"]["instance_id"]
        rejected = staged_out_service.workflow_instance_operation(
            workflow_runtime=runtime,
            flags=flags,
            tenant_id="default",
            instance_id=rejected_instance_id,
            operation="reject",
            body={"actor": "manager", "reason": "unsafe"},
        )
        self.assertEqual(rejected["instance"]["state"], "rejected")
        self.assertEqual(rejected["instance"]["events"][-1]["event_type"], "rejected")

        timeout_instance_id = staged_out_service.start_workflow_instance(
            workflow_runtime=runtime,
            flags=flags,
            tenant_id="default",
            workflow_id="wf-ops",
            body={"proposal_id": "proposal-4"},
        )["instance"]["instance_id"]
        timed_out = staged_out_service.workflow_instance_operation(
            workflow_runtime=runtime,
            flags=flags,
            tenant_id="default",
            instance_id=timeout_instance_id,
            operation="timeout_check",
            body={"now": datetime.now(timezone.utc).isoformat()},
        )
        self.assertEqual(timed_out["instance"]["state"], "escalated")
        self.assertEqual(timed_out["instance"]["current_step_id"], "s2")
        self.assertEqual(timed_out["instance"]["events"][-1]["event_type"], "timeout")

    def test_workflow_instance_unknown_is_not_found(self) -> None:
        flags = RuntimeFeatureFlags(full_bpm_workflow=True)
        runtime = WorkflowRuntime(flags, workflow_store=InMemoryWorkflowStore())
        result = staged_out_service.workflow_instance_operation(
            workflow_runtime=runtime,
            flags=flags,
            tenant_id="default",
            instance_id="missing",
            operation="approve",
            body={"actor": "manager"},
        )
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["code"], "WORKFLOW_INSTANCE_NOT_FOUND")

    def test_register_mcp_tool_requires_flag(self) -> None:
        result = staged_out_service.register_mcp_tool(
            registry=McpGatewayRegistry(),
            flags=RuntimeFeatureFlags(),
            server_id="srv",
            body={"tool_id": "t1", "name": "Tool"},
        )
        self.assertEqual(result["code"], "FEATURE_DISABLED")

    def test_register_mcp_tool_rejects_unknown_transport(self) -> None:
        reg = McpGatewayRegistry()
        staged_out_service.register_mcp_server(
            registry=reg,
            flags=RuntimeFeatureFlags(mcp_gateway=True),
            tenant_id="default",
            body={
                "server_id": "srv",
                "name": "Server",
                "allowed_scopes": ["read_metrics"],
                "state": "active",
            },
        )
        result = staged_out_service.register_mcp_tool(
            registry=reg,
            flags=RuntimeFeatureFlags(mcp_gateway=True),
            server_id="srv",
            body={"tool_id": "t1", "name": "Tool", "transport": "sse"},
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "UNKNOWN_TRANSPORT")

    def test_register_mcp_tool_rejects_stdio_when_disabled(self) -> None:
        reg = McpGatewayRegistry()
        staged_out_service.register_mcp_server(
            registry=reg,
            flags=RuntimeFeatureFlags(mcp_gateway=True),
            tenant_id="default",
            body={
                "server_id": "srv",
                "name": "Server",
                "allowed_scopes": ["read_metrics"],
                "state": "active",
            },
        )
        result = staged_out_service.register_mcp_tool(
            registry=reg,
            flags=RuntimeFeatureFlags(mcp_gateway=True),
            server_id="srv",
            body={
                "tool_id": "t1",
                "name": "Tool",
                "transport": "stdio",
                "stdio": {"command": "python"},
            },
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "STDIO_TRANSPORT_DISABLED")

    def test_noop_mcp_tool_invokes_through_router(self) -> None:
        reg = McpGatewayRegistry()
        staged_out_service.register_mcp_server(
            registry=reg,
            flags=RuntimeFeatureFlags(mcp_gateway=True),
            tenant_id="default",
            body={
                "server_id": "srv",
                "name": "Server",
                "allowed_scopes": ["read_metrics"],
                "state": "active",
            },
        )
        result = staged_out_service.register_mcp_tool(
            registry=reg,
            flags=RuntimeFeatureFlags(mcp_gateway=True),
            server_id="srv",
            body={"tool_id": "t1", "name": "Tool", "transport": "noop"},
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["transport"], "noop")

        router = McpToolRouter(reg, RuntimeFeatureFlags(mcp_gateway=True))
        invoke_result = router.invoke(
            "t1",
            AgentRunContext(
                tenant_id="default",
                workspace_id="ws",
                trace_id="trace",
                principal_id="principal",
                principal_role="operator",
                run_id="run",
                policy_scope=frozenset({"read_metrics"}),
                risk_ceiling="R3",
            ),
            metric="gmv",
        )

        self.assertEqual(invoke_result.status, "ok")
        self.assertEqual(
            invoke_result.output,
            {
                "status": "noop",
                "transport": "noop",
                "tool_id": "t1",
                "input": {"metric": "gmv"},
            },
        )

    def test_register_auto_execution_policy(self) -> None:
        flags = RuntimeFeatureFlags(r4_r5_auto_execution=True)
        pe = PolicyEngine(flags, policy_store=AutoExecutionPolicyStore())
        store = AutoExecutionPolicyStore()
        result = staged_out_service.register_auto_execution_policy(
            policy_engine=pe,
            policy_store=store,
            flags=flags,
            tenant_id="default",
            body={
                "version": "v1",
                "rules": [
                    {
                        "rule_id": "r1",
                        "action_type": "execute",
                        "risk_levels": ["R3"],
                        "mode": "proposal_only",
                        "guard_conditions": {},
                    }
                ],
            },
        )
        self.assertEqual(result["status"], "ok")
        got = staged_out_service.get_auto_execution_policy(
            policy_store=store,
            flags=flags,
            tenant_id="default",
        )
        self.assertEqual(got["status"], "ok")
        self.assertEqual(got["version"], "v1")


if __name__ == "__main__":
    unittest.main()
