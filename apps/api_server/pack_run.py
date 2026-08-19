"""Execute one operator-approved pack metric through the governed spine.

This is the composition layer that closes the pack loop:

    materialized pack (inert files)
      -> load_pack_query (fail-closed validation, domain pack)
      -> Task + Commitment + WorkflowGraph + ExpectedOutcome (canonical)
      -> ActionContract via ActionPipeline / PolicyKernel / CapabilityBroker
      -> MySqlDataQueryCapability (read-only, env-referenced secret)
      -> DataEvidenceRef + ObservedOutcome

Nothing here approves metrics, mutates the pack, or bypasses the safety
gate, the policy kernel or the correction authority.  The query capability
is READ_ONLY (risk tier 0) and every dispatch carries a fenced execution
lease exactly like the existing DataAgentRuntime path.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from agent_os_contracts import (
    CapabilityGrant,
    CapabilityGrantStatus,
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    PrincipalIdentity,
    PrincipalRole,
    ResourceBudget,
    WorkflowGraph,
)
from agent_os_contracts.common import canonical_json
from agent_os_core.action_pipeline import ActionPipeline
from agent_os_core.capability import CapabilityBroker

from apps.api_server.app import AgentOSApplication
from domain_packs.data_agent.contracts import (
    DataAgentRequest,
    DataAgentResult,
    MetricContractRef,
    SafeQueryRequest,
)
from domain_packs.data_agent.pack_loader import PackQuery, load_pack_query
from domain_packs.data_agent.runtime import (
    DATA_QUERY_CAPABILITY_ID,
    DataAgentRuntime,
    MySqlDataQueryCapability,
    MySqlDataQueryConfig,
)
from domain_packs.data_agent.sql_safety import DataSQLSafetyChecker


def _pack_query_capability(
    query: PackQuery,
    *,
    connect: Any | None,
) -> MySqlDataQueryCapability:
    checker = DataSQLSafetyChecker(query.allowed_schemas, dialect="mysql")
    config = MySqlDataQueryConfig.from_env(
        host=str(query.connection["host"]),
        port=int(query.connection["port"]),
        database=str(query.connection["database"]),
        username=str(query.connection["username"]),
        password_env=str(query.connection["password_env"]),
    )
    return MySqlDataQueryCapability(
        config,
        allowed_schemas=query.allowed_schemas,
        checker=checker,
        provider_contract_id=query.provider_id,
        _connect=connect,
    )


def run_pack_metric(
    *,
    pack_dir: Path,
    metric_name: str,
    start_date: str,
    end_date: str,
    limit: int | None = None,
    database: str | Path = ":memory:",
    workspace: str | Path = ".",
    principal: PrincipalIdentity | None = None,
    connect: Any | None = None,
) -> DataAgentResult:
    """Run one approved pack metric and return the governed result.

    ``connect`` is a test seam for the pymysql connection factory; in
    production it stays ``None`` and the real driver is used.
    """
    query = load_pack_query(
        Path(pack_dir),
        metric_name,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    now = datetime.now(timezone.utc)
    principal = principal or PrincipalIdentity(
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        role=PrincipalRole.PRINCIPAL,
        authenticated_at=now,
    )

    app = AgentOSApplication(
        database=database,
        workspace=Path(workspace),
        principal=principal,
    )
    task = app.create_task(
        {
            "goal_id": f"goal:pack:{query.metric_name}",
            "tenant_id": principal.tenant_id,
            "workspace_id": principal.workspace_id,
            "created_by": principal.principal_id,
            "created_at": now,
            "statement": f"run approved pack metric {query.metric_name}",
        }
    )
    workflow = WorkflowGraph(
        schema_version="WorkflowGraph/dag_v1",
        workflow_id=f"workflow:{task.task_id}",
        version=1,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        created_by=principal.principal_id,
        created_at=now,
        policy_version="policy-1",
        evaluator_refs=("evaluator:data_agent.outcome:1",),
        nodes=(
            NodeSpec(
                node_id="data-query",
                kind=NodeKind.TOOL,
                capability=DATA_QUERY_CAPABILITY_ID,
                idempotency=IdempotencyMode.IDEMPOTENT,
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="data-query", target="done"),),
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": f"commitment:{task.task_id}",
                "task_id": task.task_id,
                "goal_id": f"goal:pack:{query.metric_name}",
                "tenant_id": principal.tenant_id,
                "workspace_id": principal.workspace_id,
                "accepted_by": principal.principal_id,
                "accepted_at": now,
                "deliverables": ["query result"],
                "acceptance_criteria": ["evidence recorded"],
                "authority_scopes": [DATA_QUERY_CAPABILITY_ID],
                "budget": {
                    "max_cost_usd": "0",
                    "max_duration_seconds": 30,
                    "max_provider_tokens": 0,
                    "max_tool_calls": 1,
                },
                "risk_tier": 0,
                "exit_conditions": ["outcome observed"],
                "expires_at": now + timedelta(hours=1),
            },
            "workflow": workflow.model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": f"expected:{task.task_id}",
                "task_id": task.task_id,
                "tenant_id": principal.tenant_id,
                "workspace_id": principal.workspace_id,
                "evaluator_type": "data_agent.outcome",
                "evaluator_version": "1",
                "evidence_requirements": ["action receipt"],
                "failure_semantics": ["unknown effect remains unresolved"],
                "threshold": 1,
                "observation_window_seconds": 60,
                "frozen_at": now,
            },
        },
    )
    active = app.tasks.start_run(task.task_id)
    if active.run is None or active.expected_outcome is None:
        raise ValueError("PACK_RUN_BINDING_FAILED: run or expected outcome missing")

    connector = _pack_query_capability(query, connect=connect)
    connector.bind_idempotency_store(app.tasks._event_store)
    grant = CapabilityGrant(
        grant_id=f"grant:{DATA_QUERY_CAPABILITY_ID}:{task.task_id}",
        principal_id=principal.principal_id,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        capability_id=DATA_QUERY_CAPABILITY_ID,
        capability_version="1",
        max_risk_tier=0,
        budget_limit=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=30,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        status=CapabilityGrantStatus.ACTIVE,
        granted_by=principal.principal_id,
        granted_at=now,
        expires_at=now + timedelta(hours=1),
    )
    pipeline = ActionPipeline(
        app.tasks,
        CapabilityBroker(connector, app.correction),
        app.policy,
        app.correction,
        grant,
    )
    runtime = DataAgentRuntime(
        tasks=app.tasks,
        pipeline=pipeline,
        capability_spec=connector.specs()[DATA_QUERY_CAPABILITY_ID],
        checker=DataSQLSafetyChecker(query.allowed_schemas, dialect="mysql"),
    )

    params_json = canonical_json(query.parameters)
    query_id = (
        f"query:{query.metric_name}:"
        f"{hashlib.sha256(params_json.encode('utf-8')).hexdigest()[:12]}"
    )
    request = DataAgentRequest(
        request_id=f"request:{task.task_id}",
        principal=principal,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        task_id=task.task_id,
        run_id=active.run.run_id,
        expected_outcome_id=active.expected_outcome.expected_outcome_id,
        safe_query=SafeQueryRequest(
            query_id=query_id,
            metric=MetricContractRef(
                metric_id=query.metric_name,
                metric_version=query.metric_version,
                contract_digest=query.metric_contract_digest,
            ),
            sql=query.sql,
            parameters_json=params_json,
            provider_contract_id=query.provider_id,
        ),
    )
    return runtime.execute(request)


__all__ = ["run_pack_metric"]
