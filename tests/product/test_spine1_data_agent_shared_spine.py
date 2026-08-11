from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from agent_os_contracts import (
    CapabilityGrant,
    CapabilityGrantStatus,
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    PrincipalIdentity,
    PrincipalRole,
    ReceiptStatus,
    ResourceBudget,
    RunStatus,
    TaskEventType,
    WorkflowGraph,
)
from agent_os_core.action_pipeline import ActionPipeline
from agent_os_core.capability import CapabilityBroker, CapabilityEffect, CapabilityPort
from agent_os_core.governance import CorrectionAuthority, PolicyKernel
from apps.api_server.app import AgentOSApplication
from domain_packs.data_agent.contracts import (
    BusinessActionProposalRequest,
    DataAgentRequest,
    DataAgentStatus,
    MetricContractRef,
    SafeQueryRequest,
)
from domain_packs.data_agent.runtime import (
    DATA_QUERY_CAPABILITY_ID,
    DataAgentDenied,
    DataAgentRuntime,
    SQLiteDataQueryCapability,
)


def _request(
    sql: str = "SELECT SUM(amount) AS gmv FROM main.orders LIMIT 100",
) -> DataAgentRequest:
    now = datetime.now(timezone.utc)
    principal = PrincipalIdentity(
        principal_id="user:operator",
        tenant_id="tenant:acme",
        workspace_id="workspace:finance",
        role=PrincipalRole.PRINCIPAL,
        authenticated_at=now,
    )
    return DataAgentRequest(
        request_id="request:gmv",
        principal=principal,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        task_id="task:gmv",
        run_id="run:gmv",
        expected_outcome_id="expected:gmv",
        safe_query=SafeQueryRequest(
            query_id="query:gmv",
            metric=MetricContractRef(
                metric_id="metric:gmv",
                metric_version="1",
                contract_digest="a" * 64,
            ),
            sql=sql,
            parameters_json="{}",
            provider_contract_id="provider:sqlite",
        ),
    )


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "warehouse.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE orders(amount INTEGER NOT NULL)")
    connection.executemany("INSERT INTO orders(amount) VALUES (?)", [(10,), (20,)])
    connection.commit()
    connection.close()
    return path


def _grant(request: DataAgentRequest) -> CapabilityGrant:
    now = datetime.now(timezone.utc)
    return CapabilityGrant(
        grant_id="grant:data.query.safe",
        principal_id=request.principal.principal_id,
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
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
        granted_by="tenant-admin:acme",
        granted_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _runtime(
    tmp_path: Path,
    request: DataAgentRequest,
    connector: CapabilityPort,
    correction: CorrectionAuthority | None = None,
) -> tuple[DataAgentRuntime, DataAgentRequest, AgentOSApplication]:
    authority = correction or CorrectionAuthority(
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        written_by="tenant-admin:acme",
    )
    app = AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
        principal=request.principal,
    )
    now = datetime.now(timezone.utc)
    task = app.create_task(
        {
            "goal_id": "goal:data-query",
            "tenant_id": request.tenant_id,
            "workspace_id": request.workspace_id,
            "created_by": request.principal.principal_id,
            "created_at": now,
            "statement": "query governed data",
        }
    )
    workflow = WorkflowGraph(
        schema_version="WorkflowGraph/dag_v1",
        workflow_id=f"workflow:{task.task_id}",
        version=1,
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        created_by=request.principal.principal_id,
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
            NodeSpec(
                node_id="data-action-proposal",
                kind=NodeKind.TOOL,
                capability="data.action.propose",
                idempotency=IdempotencyMode.IDEMPOTENT,
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(
            EdgeSpec(source="data-query", target="data-action-proposal"),
            EdgeSpec(source="data-action-proposal", target="done"),
        ),
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": f"commitment:{task.task_id}",
                "task_id": task.task_id,
                "goal_id": "goal:data-query",
                "tenant_id": request.tenant_id,
                "workspace_id": request.workspace_id,
                "accepted_by": request.principal.principal_id,
                "accepted_at": now,
                "deliverables": ["query result"],
                "acceptance_criteria": ["evidence recorded"],
                "authority_scopes": [
                    DATA_QUERY_CAPABILITY_ID,
                    "data.action.propose",
                ],
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
                "tenant_id": request.tenant_id,
                "workspace_id": request.workspace_id,
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
    assert active.run is not None and active.expected_outcome is not None
    bound_request = request.model_copy(
        update={
            "task_id": task.task_id,
            "run_id": active.run.run_id,
            "expected_outcome_id": active.expected_outcome.expected_outcome_id,
        }
    )
    spec = connector.specs()[DATA_QUERY_CAPABILITY_ID]
    pipeline = ActionPipeline(
        app.tasks,
        CapabilityBroker(connector, authority),
        PolicyKernel(authority),
        authority,
        _grant(bound_request),
    )
    runtime = DataAgentRuntime(
        tasks=app.tasks,
        pipeline=pipeline,
        capability_spec=spec,
    )
    return runtime, bound_request, app


def test_unsafe_sql_never_reaches_capability_broker(tmp_path: Path) -> None:
    request = _request("DELETE FROM orders")
    connector = SQLiteDataQueryCapability(_database(tmp_path))
    runtime, request, _ = _runtime(tmp_path, request, connector)

    with pytest.raises(DataAgentDenied, match="SQL_SAFETY_DENIED"):
        runtime.execute(request)

    connection = sqlite3.connect(tmp_path / "warehouse.sqlite3")
    assert connection.execute("SELECT COUNT(*) FROM orders").fetchone() == (2,)
    connection.close()
    assert connector.execution_count == 0


def test_valid_query_runs_through_real_policy_and_broker(tmp_path: Path) -> None:
    request = _request()
    connector = SQLiteDataQueryCapability(_database(tmp_path))

    runtime, request, app = _runtime(tmp_path, request, connector)
    result = runtime.execute(request)

    assert result.status is DataAgentStatus.COMPLETED
    assert result.query_result is not None
    assert result.query_result.rows_json == '[{"gmv":30}]'
    assert result.query_result.row_count == 1
    assert result.evidence is not None
    assert result.evidence.generic_evidence_ref.startswith("receipt-")
    assert result.evidence.provider_contract_id == "provider:sqlite"
    assert result.evidence.query_id == "query:gmv"
    assert result.evidence.sql_fingerprint == result.query_result.sql_fingerprint
    assert result.evidence.confidence_score <= 0.55
    assert set(result.evidence.confidence_flags) >= {
        "freshness_unknown",
        "unverified_template",
    }
    assert result.evidence.generic_evidence_ref in result.evidence.lineage_refs
    assert "provider:sqlite" in result.evidence.lineage_refs
    assert result.observed_outcome_id == "observed:request:gmv"
    assert connector.execution_count == 1
    event_types = [event.event_type for event in app.store.read(request.task_id)]
    assert TaskEventType.ACTION_PROPOSED in event_types
    assert TaskEventType.POLICY_DECIDED in event_types
    assert TaskEventType.ACTION_RECEIPT_RECORDED in event_types


class _UnknownEffectQueryCapability:
    def __init__(self, spec_source: SQLiteDataQueryCapability) -> None:
        self._spec_source = spec_source
        self.execution_count = 0

    def specs(self, now=None, *, include_internal: bool = False):
        return self._spec_source.specs(now, include_internal=include_internal)

    def execute(self, action):
        self.execution_count += 1
        return CapabilityEffect(
            status=ReceiptStatus.UNKNOWN,
            output={},
            error_code="EFFECT_UNKNOWN",
            detail_ref="detail:query-effect-unknown",
        )


class _MalformedSuccessQueryCapability(_UnknownEffectQueryCapability):
    def execute(self, action):
        self.execution_count += 1
        return CapabilityEffect(
            status=ReceiptStatus.SUCCEEDED,
            output={"row_count": "not-an-integer"},
        )


def test_unknown_effect_fails_closed_without_resend(tmp_path: Path) -> None:
    request = _request()
    connector = _UnknownEffectQueryCapability(
        SQLiteDataQueryCapability(_database(tmp_path))
    )

    runtime, request, _ = _runtime(tmp_path, request, connector)
    result = runtime.execute(request)

    assert result.status is DataAgentStatus.HELP_REQUIRED
    assert result.failure_code == "EFFECT_UNKNOWN"
    assert result.resend_attempts == 0
    assert connector.execution_count == 1


def test_malformed_success_output_fails_closed(tmp_path: Path) -> None:
    request = _request()
    connector = _MalformedSuccessQueryCapability(
        SQLiteDataQueryCapability(_database(tmp_path))
    )

    with pytest.raises(DataAgentDenied, match="MALFORMED_CAPABILITY_OUTPUT"):
        runtime, request, _ = _runtime(tmp_path, request, connector)
        runtime.execute(request)

    assert connector.execution_count == 1


def test_correction_halt_blocks_query_before_connector(tmp_path: Path) -> None:
    request = _request()
    connector = SQLiteDataQueryCapability(_database(tmp_path))
    correction = CorrectionAuthority(
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        written_by="tenant-admin:acme",
    )
    runtime, request, _ = _runtime(tmp_path, request, connector, correction)
    correction.correct("task", request.task_id, "operator stop")

    with pytest.raises(DataAgentDenied, match="POLICY_DENIED"):
        runtime.execute(request)

    assert connector.execution_count == 0


def test_business_action_is_proposal_only_and_enters_exact_approval_wait(
    tmp_path: Path,
) -> None:
    request = _request()
    connector = SQLiteDataQueryCapability(_database(tmp_path))
    runtime, request, app = _runtime(tmp_path, request, connector)
    proposal_request = BusinessActionProposalRequest(
        request_id="request:notify-finance",
        principal=request.principal,
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        task_id=request.task_id,
        run_id=request.run_id,
        expected_outcome_id=request.expected_outcome_id,
        target_capability_id="data.action.email",
        payload_json='{"report_id":"report:gmv"}',
        consequence_preview="Send the governed GMV report to finance reviewers.",
        alternatives=("Do nothing", "Create a draft without sending"),
        risk_tier=2,
    )

    result = runtime.propose_action(proposal_request)

    assert result.status is DataAgentStatus.AWAITING_APPROVAL
    assert result.action_proposal is not None
    assert result.action_proposal.capability_id == "data.action.email"
    assert result.action_proposal.approval_requirement == "external_exact"
    aggregate = app.tasks.get_task(request.task_id)
    assert aggregate.run is not None
    assert aggregate.run.status is RunStatus.WAITING_APPROVAL
    pending = app.tasks.pending_action(request.task_id)
    assert pending is not None
    assert pending.action_digest() == result.action_proposal.action_digest
    assert pending.capability_id == "data.action.propose"
    assert connector.execution_count == 0


def test_shared_action_pipeline_records_unknown_receipt_without_forcing_resend(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    task = app.create_task(
        {
            "goal_id": "goal:data-query",
            "tenant_id": app.principal.tenant_id,
            "workspace_id": app.principal.workspace_id,
            "created_by": app.principal.principal_id,
            "created_at": now,
            "statement": "query governed data",
        }
    )
    workflow = WorkflowGraph(
        schema_version="WorkflowGraph/dag_v1",
        workflow_id="workflow:data-query",
        version=1,
        tenant_id=app.principal.tenant_id,
        workspace_id=app.principal.workspace_id,
        created_by=app.principal.principal_id,
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
                "commitment_id": "commitment:data-query",
                "task_id": task.task_id,
                "goal_id": "goal:data-query",
                "tenant_id": app.principal.tenant_id,
                "workspace_id": app.principal.workspace_id,
                "accepted_by": app.principal.principal_id,
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
                "expected_outcome_id": "expected:data-query",
                "task_id": task.task_id,
                "tenant_id": app.principal.tenant_id,
                "workspace_id": app.principal.workspace_id,
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
    assert active.run is not None and active.expected_outcome is not None
    request = DataAgentRequest(
        **{
            **_request().model_dump(),
            "principal": app.principal,
            "tenant_id": app.principal.tenant_id,
            "workspace_id": app.principal.workspace_id,
            "task_id": task.task_id,
            "run_id": active.run.run_id,
            "expected_outcome_id": active.expected_outcome.expected_outcome_id,
        }
    )
    connector = _UnknownEffectQueryCapability(
        SQLiteDataQueryCapability(_database(tmp_path))
    )
    grant = _grant(request).model_copy(
        update={
            "budget_limit": ResourceBudget(
                max_cost_usd=Decimal("0"),
                max_duration_seconds=120,
                max_provider_tokens=0,
                max_tool_calls=1,
            )
        }
    )
    pipeline = ActionPipeline(
        app.tasks,
        CapabilityBroker(connector, app.correction),
        app.policy,
        app.correction,
        grant,
    )
    action = pipeline.build_action(
        task_id=task.task_id,
        run_id=active.run.run_id,
        node_id="data-query",
        capability_id=DATA_QUERY_CAPABILITY_ID,
        principal=app.principal,
        args={
            "query_id": request.safe_query.query_id,
            "sql": request.safe_query.sql,
            "parameters": {},
            "provider_contract_id": "provider:sqlite",
        },
        expected=active.expected_outcome,
        envelope_id="envelope:data-query",
        risk_tier=0,
    )
    pipeline.record_action_proposed(action)

    result = pipeline.execute_observed(
        action,
        app.principal,
        capability_spec=connector.specs()[DATA_QUERY_CAPABILITY_ID],
        record_artifacts=False,
    )

    assert result.receipt.status is ReceiptStatus.UNKNOWN
    receipt_events = [
        event
        for event in app.store.read(task.task_id)
        if event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED
    ]
    assert len(receipt_events) == 1
    assert connector.execution_count == 1
