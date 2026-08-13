from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from agent_os_contracts import (
    MandateRelevanceContextRef,
    MandateWorkspaceRecord,
    ObservationBindingDescriptor,
    PrincipalIdentity,
    PrincipalRole,
    RelevanceAssessorRef,
)
from apps.api_server.app import AgentOSApplication
from apps.api_server.data_agent_report_adapter import DataAgentReportAdapter
from tests.product.test_mandate_workspace_api import _payload


def create_workspace_record(
    database: str | Path,
    workspace: Path,
    *,
    adapter: DataAgentReportAdapter,
    now: datetime,
) -> MandateWorkspaceRecord:
    principal_id, tenant_id, workspace_id = adapter.principal_scope
    payload = _payload(expires_at=now + timedelta(days=30))
    payload["mandate_id"] = adapter.admission_policy_descriptor.mandate_id
    owner = AgentOSApplication(
        database=database,
        workspace=workspace,
        principal=PrincipalIdentity(
            principal_id=principal_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            role=PrincipalRole.PRINCIPAL,
            authenticated_at=now,
        ),
        clock=lambda: now,
    )
    return MandateWorkspaceRecord.model_validate(
        owner.create_mandate_workspace_record(payload)
    )


def authorize_workspace_observation(
    database: str | Path,
    workspace: Path,
    *,
    adapter: DataAgentReportAdapter,
    assessor: RelevanceAssessorRef,
    context: MandateRelevanceContextRef,
    now: datetime,
) -> None:
    _, tenant_id, workspace_id = adapter.principal_scope
    source = adapter.admission_policy_descriptor
    descriptor = ObservationBindingDescriptor(
        environment_binding_id=source.environment_binding_id,
        environment_binding_class="project-state",
        version=1,
        source_descriptor_digest=source.policy_digest,
        observation_capabilities=("observation.read",),
        max_wake_budget_per_window=8,
        max_query_budget_per_window=32,
        relevance_assessor=assessor,
        relevance_context=context,
    )
    admin = AgentOSApplication(
        database=database,
        workspace=workspace,
        principal=PrincipalIdentity(
            principal_id="principal:test-security-admin",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            role=PrincipalRole.TENANT_ADMIN,
            authenticated_at=now,
        ),
        clock=lambda: now,
        observation_binding_descriptors=(descriptor,),
    )
    admin.authorize_mandate_observation_binding(
        source.mandate_id,
        {
            "authorization_id": f"observation-auth:{source.mandate_id}",
            "environment_binding_id": source.environment_binding_id,
            "environment_binding_class": "project-state",
            "binding_version": 1,
            "requested_capabilities": ["observation.read"],
            "wake_budget_per_window": 8,
            "query_budget_per_window": 32,
            "relevance_assessor": assessor.model_dump(mode="json"),
            "relevance_context": context.model_dump(mode="json"),
        },
    )
