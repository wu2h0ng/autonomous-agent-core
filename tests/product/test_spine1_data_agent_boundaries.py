from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_os_contracts import PrincipalIdentity, PrincipalRole
from domain_packs.data_agent import manifest
from domain_packs.data_agent.contracts import (
    DataAgentRequest,
    DataAgentResult,
    DataAgentStatus,
    DataEvidenceRef,
    MetricContractRef,
    SafeQueryRequest,
)


NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)


def _principal(*, tenant_id: str = "tenant:acme") -> PrincipalIdentity:
    return PrincipalIdentity(
        principal_id="user:operator",
        tenant_id=tenant_id,
        workspace_id="workspace:finance",
        role=PrincipalRole.PRINCIPAL,
        authenticated_at=NOW,
    )


def _query() -> SafeQueryRequest:
    return SafeQueryRequest(
        query_id="query:gmv",
        metric=MetricContractRef(
            metric_id="metric:gmv",
            metric_version="1",
            contract_digest="a" * 64,
        ),
        sql="SELECT SUM(amount) AS gmv FROM orders LIMIT 100",
        parameters_json='{"end":"2026-08-11","start":"2026-08-01"}',
        provider_contract_id="provider:data-warehouse",
    )


def test_manifest_registers_proposal_only_data_capabilities() -> None:
    data_manifest = manifest(now=NOW)

    assert data_manifest.pack_id == "data-agent"
    assert data_manifest.namespace == "data_agent"
    assert data_manifest.capabilities == (
        "data.query.safe",
        "data.report.observe",
        "data.action.propose",
    )
    assert "data.action.execute" not in data_manifest.capabilities
    assert data_manifest.credential_classes == ()


def test_request_rejects_principal_scope_mismatch() -> None:
    with pytest.raises(ValidationError, match="principal scope must match"):
        DataAgentRequest(
            request_id="request:gmv",
            principal=_principal(tenant_id="tenant:other"),
            tenant_id="tenant:acme",
            workspace_id="workspace:finance",
            task_id="task:gmv",
            run_id="run:gmv",
            expected_outcome_id="outcome:gmv",
            safe_query=_query(),
        )


def test_query_parameters_are_canonical_and_object_only() -> None:
    assert _query().parameters_json == '{"end":"2026-08-11","start":"2026-08-01"}'

    with pytest.raises(ValidationError, match="parameters_json must encode an object"):
        SafeQueryRequest(
            query_id="query:invalid",
            metric=MetricContractRef(
                metric_id="metric:gmv",
                metric_version="1",
                contract_digest="a" * 64,
            ),
            sql="SELECT 1",
            parameters_json="[]",
            provider_contract_id="provider:data-warehouse",
        )


def test_completed_result_requires_evidence_and_observed_outcome() -> None:
    with pytest.raises(ValidationError, match="completed result requires"):
        DataAgentResult(
            request_id="request:gmv",
            task_id="task:gmv",
            run_id="run:gmv",
            tenant_id="tenant:acme",
            workspace_id="workspace:finance",
            status=DataAgentStatus.COMPLETED,
            trace_id="trace:gmv",
        )

    result = DataAgentResult(
        request_id="request:gmv",
        task_id="task:gmv",
        run_id="run:gmv",
        tenant_id="tenant:acme",
        workspace_id="workspace:finance",
        status=DataAgentStatus.COMPLETED,
        trace_id="trace:gmv",
        evidence=DataEvidenceRef(
            evidence_id="evidence:gmv",
            generic_evidence_ref="evidence-ref:gmv",
            metric_contract_digest="a" * 64,
            query_result_digest="b" * 64,
        ),
        observed_outcome_id="observed-outcome:gmv",
    )
    assert result.failure_code is None


def test_os_core_ast_contains_no_data_domain_contracts_or_staging_imports() -> None:
    root = Path("packages/os_core/src")
    forbidden_definitions = {
        "MetricContract",
        "SQLQuery",
        "DataProduct",
        "SemanticObject",
    }
    found: list[str] = []
    staging_imports: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.ClassDef, ast.FunctionDef))
                and node.name in forbidden_definitions
            ):
                found.append(f"{path}:{node.name}")
            if isinstance(node, ast.Import):
                staging_imports.extend(
                    alias.name
                    for alias in node.names
                    if alias.name.startswith("_migration")
                )
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "_migration"
            ):
                staging_imports.append(node.module or "")
    assert found == []
    assert staging_imports == []
