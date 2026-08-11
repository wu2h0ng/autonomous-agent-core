"""Staged-out capability management service (ADR-0013 C/D/E HTTP plane)."""

from __future__ import annotations

from typing import Any

from agent_os_contracts import (
    ApprovalWorkflow,
    AutoExecutionPolicy,
    AutoExecutionRule,
    McpServerRegistration,
    McpToolContract,
    RuntimeFeatureFlags,
    WorkflowStep,
)
from agent_os_core.mcp_gateway import McpGatewayRegistry
from agent_os_core.policy_engine import AutoExecutionPolicyStorePort, PolicyEngine
from agent_os_core.workflow import (
    InvalidWorkflowState,
    WorkflowDisabled,
    WorkflowInstanceNotFound,
    WorkflowNotFound,
    WorkflowRuntime,
)

from .mcp_transport import McpTransportRegistry, McpTransportRejected


def register_auto_execution_policy(
    *,
    policy_engine: PolicyEngine | None,
    policy_store: AutoExecutionPolicyStorePort | None,
    flags: RuntimeFeatureFlags,
    tenant_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    if not flags.r4_r5_auto_execution or policy_engine is None:
        return {
            "status": "error",
            "code": "FEATURE_DISABLED",
            "message": "r4_r5_auto_execution is off",
        }
    rules = tuple(
        AutoExecutionRule(
            rule_id=r["rule_id"],
            action_type=r["action_type"],
            risk_levels=tuple(r["risk_levels"]),
            mode=r["mode"],
            guard_conditions=dict(r.get("guard_conditions", {})),
            compensating_action=r.get("compensating_action"),
        )
        for r in body.get("rules", [])
    )
    policy = AutoExecutionPolicy(
        version=body["version"],
        tenant_id=tenant_id,
        owner=body.get("owner", "tenant_admin"),
        default_mode=body.get("default_mode", "proposal_only"),
        rules=rules,
    )
    policy_engine.register_policy(policy)
    if policy_store is not None:
        policy_store.save(policy)
    return {"status": "ok", "tenant_id": tenant_id, "version": policy.version}


def get_auto_execution_policy(
    *,
    policy_store: AutoExecutionPolicyStorePort | None,
    flags: RuntimeFeatureFlags,
    tenant_id: str,
) -> dict[str, Any]:
    if not flags.r4_r5_auto_execution:
        return {
            "status": "error",
            "code": "FEATURE_DISABLED",
            "message": "r4_r5_auto_execution is off",
        }
    if policy_store is None:
        return {
            "status": "error",
            "code": "STORE_UNAVAILABLE",
            "message": "policy store not configured",
        }
    policy = policy_store.get(tenant_id)
    if policy is None:
        return {"status": "not_found", "tenant_id": tenant_id}
    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "version": policy.version,
        "default_mode": policy.default_mode,
        "rules": [
            {
                "rule_id": r.rule_id,
                "action_type": r.action_type,
                "risk_levels": list(r.risk_levels),
                "mode": r.mode,
                "guard_conditions": dict(r.guard_conditions),
                "compensating_action": r.compensating_action,
            }
            for r in policy.rules
        ],
    }


def register_workflow(
    *,
    workflow_runtime: WorkflowRuntime | None,
    flags: RuntimeFeatureFlags,
    tenant_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    if not flags.full_bpm_workflow:
        return _workflow_disabled()
    if workflow_runtime is None:
        return _workflow_runtime_unavailable()
    steps = tuple(
        WorkflowStep(
            step_id=s["step_id"],
            step_type=s["step_type"],
            approver_role=s.get("approver_role"),
            timeout_seconds=s.get("timeout_seconds"),
            next_step_id=s.get("next_step_id"),
            fallback_step_id=s.get("fallback_step_id"),
        )
        for s in body.get("steps", [])
    )
    workflow = ApprovalWorkflow(
        workflow_id=body["workflow_id"],
        name=body["name"],
        action_type=body["action_type"],
        risk_levels=tuple(body.get("risk_levels", ())),
        steps=steps,
        state=body.get("state", "draft"),
    )
    workflow_runtime.register_workflow(workflow, tenant_id=tenant_id)
    return {"status": "ok", "workflow_id": workflow.workflow_id, "state": workflow.state}


def _workflow_disabled() -> dict[str, Any]:
    return {
        "status": "error",
        "code": "FEATURE_DISABLED",
        "message": "full_bpm_workflow is off",
    }


def _workflow_runtime_unavailable() -> dict[str, Any]:
    return {
        "status": "error",
        "code": "RUNTIME_UNAVAILABLE",
        "message": "workflow runtime not configured",
    }


def _workflow_instance_payload(workflow_runtime: WorkflowRuntime, instance: Any) -> dict[str, Any]:
    return {
        "instance_id": instance.instance_id,
        "workflow_id": instance.workflow_id,
        "proposal_id": instance.proposal_id,
        "current_step_id": instance.current_step_id,
        "state": instance.state,
        "assigned_role": workflow_runtime.assigned_role(instance.instance_id),
        "events": [
            {
                "event_id": event.event_id,
                "instance_id": event.instance_id,
                "step_id": event.step_id,
                "event_type": event.event_type,
                "actor": event.actor,
                "timestamp": event.timestamp,
                "payload": dict(event.payload),
            }
            for event in instance.events
        ],
    }


def _workflow_error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, WorkflowDisabled):
        return _workflow_disabled()
    if isinstance(exc, WorkflowInstanceNotFound):
        return {
            "status": "not_found",
            "code": "WORKFLOW_INSTANCE_NOT_FOUND",
            "message": "workflow instance not found",
        }
    if isinstance(exc, WorkflowNotFound):
        return {
            "status": "not_found",
            "code": "WORKFLOW_NOT_FOUND",
            "message": "workflow not found",
        }
    if isinstance(exc, InvalidWorkflowState):
        return {
            "status": "error",
            "code": "INVALID_WORKFLOW_STATE",
            "message": "workflow operation is not allowed in the current state",
        }
    return {
        "status": "error",
        "code": "WORKFLOW_OPERATION_FAILED",
        "message": "workflow operation failed",
    }


def start_workflow_instance(
    *,
    workflow_runtime: WorkflowRuntime | None,
    flags: RuntimeFeatureFlags,
    tenant_id: str,
    workflow_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    if not flags.full_bpm_workflow:
        return _workflow_disabled()
    if workflow_runtime is None:
        return _workflow_runtime_unavailable()
    try:
        instance = workflow_runtime.start_instance(
            workflow_id,
            body["proposal_id"],
            tenant_id=tenant_id,
            first_step_id=body.get("first_step_id"),
            started_by=body.get("started_by", "system"),
        )
    except Exception as exc:  # noqa: BLE001 - public service returns sanitized JSON
        return _workflow_error_payload(exc)
    return {
        "status": "ok",
        "instance": _workflow_instance_payload(workflow_runtime, instance),
    }


def get_workflow_instance(
    *,
    workflow_runtime: WorkflowRuntime | None,
    flags: RuntimeFeatureFlags,
    tenant_id: str,
    instance_id: str,
) -> dict[str, Any]:
    if not flags.full_bpm_workflow:
        return _workflow_disabled()
    if workflow_runtime is None:
        return _workflow_runtime_unavailable()
    try:
        instance = workflow_runtime.get_instance(instance_id, tenant_id=tenant_id)
    except Exception as exc:  # noqa: BLE001 - public service returns sanitized JSON
        return _workflow_error_payload(exc)
    return {
        "status": "ok",
        "instance": _workflow_instance_payload(workflow_runtime, instance),
    }


def workflow_instance_operation(
    *,
    workflow_runtime: WorkflowRuntime | None,
    flags: RuntimeFeatureFlags,
    tenant_id: str,
    instance_id: str,
    operation: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    if not flags.full_bpm_workflow:
        return _workflow_disabled()
    if workflow_runtime is None:
        return _workflow_runtime_unavailable()
    try:
        if operation == "approve":
            instance = workflow_runtime.approve_step(
                instance_id,
                body.get("actor", "system"),
                reason=body.get("reason"),
                tenant_id=tenant_id,
            )
        elif operation == "reject":
            instance = workflow_runtime.reject_step(
                instance_id,
                body.get("actor", "system"),
                reason=body.get("reason"),
                tenant_id=tenant_id,
            )
        elif operation == "delegate":
            instance = workflow_runtime.delegate_step(
                instance_id,
                body.get("actor", "system"),
                body["to_role"],
                tenant_id=tenant_id,
            )
        elif operation == "timeout_check":
            instance = workflow_runtime.timeout_check(
                instance_id,
                body["now"],
                tenant_id=tenant_id,
            )
        else:
            return {
                "status": "error",
                "code": "UNSUPPORTED_WORKFLOW_OPERATION",
                "message": "workflow operation is not supported",
            }
    except Exception as exc:  # noqa: BLE001 - public service returns sanitized JSON
        return _workflow_error_payload(exc)
    return {
        "status": "ok",
        "operation": operation,
        "instance": _workflow_instance_payload(workflow_runtime, instance),
    }


def list_workflows(
    *,
    workflow_store: Any,
    flags: RuntimeFeatureFlags,
    tenant_id: str,
) -> dict[str, Any]:
    if not flags.full_bpm_workflow:
        return {
            "status": "error",
            "code": "FEATURE_DISABLED",
            "message": "full_bpm_workflow is off",
        }
    if workflow_store is None:
        return {
            "status": "error",
            "code": "STORE_UNAVAILABLE",
            "message": "workflow store not configured",
        }
    items = workflow_store.list_workflows(tenant_id)
    return {
        "status": "ok",
        "items": [
            {
                "workflow_id": w.workflow_id,
                "name": w.name,
                "action_type": w.action_type,
                "state": w.state,
                "risk_levels": list(w.risk_levels),
            }
            for w in items
        ],
    }


def register_mcp_server(
    *,
    registry: McpGatewayRegistry | None,
    flags: RuntimeFeatureFlags,
    tenant_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    if not flags.mcp_gateway or registry is None:
        return {"status": "error", "code": "FEATURE_DISABLED", "message": "mcp_gateway is off"}
    registration = McpServerRegistration(
        server_id=body["server_id"],
        name=body["name"],
        transport_url=body.get("transport_url", "in-process://local"),
        owner=body.get("owner", "platform"),
        tenant_id=tenant_id,
        allowed_scopes=tuple(body.get("allowed_scopes", ())),
        risk_ceiling=body.get("risk_ceiling", "R3"),
        state=body.get("state", "pending"),
    )
    registry.register_server(registration)
    if registration.state == "active":
        registry.activate_server(registration.server_id)
    return {"status": "ok", "server_id": registration.server_id, "state": registration.state}


def register_mcp_tool(
    *,
    registry: McpGatewayRegistry | None,
    flags: RuntimeFeatureFlags,
    server_id: str,
    body: dict[str, Any],
    transport_registry: McpTransportRegistry | None = None,
) -> dict[str, Any]:
    if not flags.mcp_gateway or registry is None:
        return {"status": "error", "code": "FEATURE_DISABLED", "message": "mcp_gateway is off"}
    tool = McpToolContract(
        tool_id=body["tool_id"],
        server_id=server_id,
        name=body["name"],
        description=body.get("description", ""),
        input_schema=body.get("input_schema", {"type": "object"}),
        risk_level=body.get("risk_level", "R1"),
        dry_run_supported=bool(body.get("dry_run_supported", False)),
    )
    transport_registry = transport_registry or McpTransportRegistry()
    try:
        transport = transport_registry.handler_for(tool_id=tool.tool_id, body=body)
    except McpTransportRejected as exc:
        return {"status": "error", "code": exc.code, "message": exc.message}
    if body.get("activate_server", True):
        registry.activate_server(server_id)
    registry.register_tool(tool, handler=transport.handler)
    return {
        "status": "ok",
        "tool_id": tool.tool_id,
        "server_id": server_id,
        "transport": transport.transport,
    }
