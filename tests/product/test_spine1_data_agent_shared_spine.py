from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from agent_os_contracts import (
    CapabilityGrant,
    CapabilityGrantStatus,
    PrincipalIdentity,
    PrincipalRole,
    ReceiptStatus,
    ResourceBudget,
)
from agent_os_core.capability import CapabilityBroker, CapabilityEffect, CapabilityPort
from agent_os_core.governance import CorrectionAuthority, PolicyKernel
from domain_packs.data_agent.contracts import (
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
    sql: str = "SELECT SUM(amount) AS gmv FROM orders LIMIT 100",
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
    request: DataAgentRequest,
    connector: CapabilityPort,
    correction: CorrectionAuthority | None = None,
) -> DataAgentRuntime:
    authority = correction or CorrectionAuthority(
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        written_by="tenant-admin:acme",
    )
    spec = connector.specs()[DATA_QUERY_CAPABILITY_ID]
    return DataAgentRuntime(
        broker=CapabilityBroker(connector, authority),
        policy=PolicyKernel(authority),
        correction=authority,
        capability_spec=spec,
        grant=_grant(request),
    )


def test_unsafe_sql_never_reaches_capability_broker(tmp_path: Path) -> None:
    request = _request("DELETE FROM orders")
    connector = SQLiteDataQueryCapability(_database(tmp_path))
    runtime = _runtime(request, connector)

    with pytest.raises(DataAgentDenied, match="SQL_SAFETY_DENIED"):
        runtime.execute(request)

    connection = sqlite3.connect(tmp_path / "warehouse.sqlite3")
    assert connection.execute("SELECT COUNT(*) FROM orders").fetchone() == (2,)
    connection.close()
    assert connector.execution_count == 0


def test_valid_query_runs_through_real_policy_and_broker(tmp_path: Path) -> None:
    request = _request()
    connector = SQLiteDataQueryCapability(_database(tmp_path))

    result = _runtime(request, connector).execute(request)

    assert result.status is DataAgentStatus.COMPLETED
    assert result.query_result is not None
    assert result.query_result.rows_json == '[{"gmv":30}]'
    assert result.query_result.row_count == 1
    assert result.evidence is not None
    assert result.evidence.generic_evidence_ref.startswith("receipt-")
    assert result.observed_outcome_id == "observed:request:gmv"
    assert connector.execution_count == 1


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

    result = _runtime(request, connector).execute(request)

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
        _runtime(request, connector).execute(request)

    assert connector.execution_count == 1


def test_correction_halt_blocks_query_before_connector(tmp_path: Path) -> None:
    request = _request()
    connector = SQLiteDataQueryCapability(_database(tmp_path))
    correction = CorrectionAuthority(
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        written_by="tenant-admin:acme",
    )
    correction.correct("task", request.task_id, "operator stop")

    with pytest.raises(DataAgentDenied, match="POLICY_DENIED"):
        _runtime(request, connector, correction).execute(request)

    assert connector.execution_count == 0
