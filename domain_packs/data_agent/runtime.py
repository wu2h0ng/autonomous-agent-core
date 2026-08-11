from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    ActionContract,
    CapabilityGrant,
    CapabilitySpec,
    PolicyVerdict,
    ReceiptStatus,
    ResourceBudget,
    SideEffectGuarantee,
)
from agent_os_contracts.common import canonical_json
from agent_os_core.capability import (
    CapabilityBroker,
    CapabilityDenied,
    CapabilityEffect,
)
from agent_os_core.governance import CorrectionReadPort, PolicyInput, PolicyKernel
from pydantic import ValidationError

from .contracts import (
    DataAgentRequest,
    DataAgentResult,
    DataAgentStatus,
    DataEvidenceRef,
    SafeQueryResult,
)


DATA_QUERY_CAPABILITY_ID = "data.query.safe"
_FORBIDDEN_SQL = re.compile(
    r"\b(?:ALTER|ATTACH|CREATE|DELETE|DETACH|DROP|INSERT|PRAGMA|REPLACE|UPDATE|VACUUM)\b",
    re.IGNORECASE,
)
_LIMIT = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)


class DataAgentDenied(PermissionError):
    pass


class DataSQLSafetyChecker:
    def __init__(self, *, max_rows: int = 1_000) -> None:
        self.max_rows = max_rows

    def check(self, sql: str) -> None:
        normalized = sql.strip()
        if not normalized:
            raise DataAgentDenied("SQL_SAFETY_DENIED:EMPTY_SQL")
        if "--" in normalized or "/*" in normalized or "*/" in normalized:
            raise DataAgentDenied("SQL_SAFETY_DENIED:COMMENTS_FORBIDDEN")
        body = normalized[:-1].rstrip() if normalized.endswith(";") else normalized
        if ";" in body:
            raise DataAgentDenied("SQL_SAFETY_DENIED:MULTI_STATEMENT")
        if not re.match(r"^(?:SELECT|WITH)\b", body, re.IGNORECASE):
            raise DataAgentDenied("SQL_SAFETY_DENIED:READ_ONLY_REQUIRED")
        if _FORBIDDEN_SQL.search(body):
            raise DataAgentDenied("SQL_SAFETY_DENIED:WRITE_KEYWORD")
        if re.search(r"\bSELECT\s+\*", body, re.IGNORECASE):
            raise DataAgentDenied("SQL_SAFETY_DENIED:SELECT_STAR")
        limit = _LIMIT.search(body)
        if limit is None:
            raise DataAgentDenied("SQL_SAFETY_DENIED:LIMIT_REQUIRED")
        if int(limit.group(1)) > self.max_rows:
            raise DataAgentDenied("SQL_SAFETY_DENIED:LIMIT_EXCEEDED")


class SQLiteDataQueryCapability:
    """Read-only Data Agent query adapter behind the shared CapabilityBroker."""

    def __init__(
        self,
        database: str | Path,
        *,
        checker: DataSQLSafetyChecker | None = None,
    ) -> None:
        self._database = Path(database).resolve()
        self._checker = checker or DataSQLSafetyChecker()
        self.execution_count = 0

    def specs(
        self,
        now: datetime | None = None,
        *,
        include_internal: bool = False,
    ) -> Mapping[str, CapabilitySpec]:
        del include_internal
        created_at = now or datetime.now(timezone.utc)
        return {
            DATA_QUERY_CAPABILITY_ID: CapabilitySpec(
                capability_id=DATA_QUERY_CAPABILITY_ID,
                version="1",
                display_name="Data Agent safe read-only query",
                input_contract="DataAgentSafeQueryAction/v1",
                output_contract="DataAgentSafeQueryEffect/v1",
                side_effect_guarantee=SideEffectGuarantee.READ_ONLY,
                idempotency_supported=True,
                credential_class="database-reference",
                data_boundary="tenant-workspace-bound",
                risk_tier=0,
                timeout_seconds=30,
                cancellation_supported=False,
                compensation_supported=False,
                audit_policy="action-receipt-required",
                created_by="domain-pack:data-agent",
                created_at=created_at,
            )
        }

    def execute(self, action: ActionContract) -> CapabilityEffect:
        if action.capability_id != DATA_QUERY_CAPABILITY_ID:
            return CapabilityEffect(
                status=ReceiptStatus.FAILED,
                output={},
                error_code="UNSUPPORTED_CAPABILITY",
                detail_ref="detail:data-query:unsupported-capability",
            )
        payload = json.loads(action.arguments_json)
        sql = payload.get("sql")
        parameters = payload.get("parameters")
        provider_contract_id = payload.get("provider_contract_id")
        if not isinstance(sql, str) or not isinstance(parameters, dict):
            return CapabilityEffect(
                status=ReceiptStatus.FAILED,
                output={},
                error_code="INVALID_QUERY_ARGUMENTS",
                detail_ref="detail:data-query:invalid-arguments",
            )
        if provider_contract_id != "provider:sqlite":
            return CapabilityEffect(
                status=ReceiptStatus.FAILED,
                output={},
                error_code="UNSUPPORTED_PROVIDER_CONTRACT",
                detail_ref="detail:data-query:unsupported-provider",
            )
        self._checker.check(sql)
        connection = sqlite3.connect(
            f"file:{self._database}?mode=ro",
            uri=True,
            timeout=30,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only = ON")
            cursor = connection.execute(sql, parameters)
            rows = [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            return CapabilityEffect(
                status=ReceiptStatus.FAILED,
                output={},
                error_code="QUERY_EXECUTION_FAILED",
                detail_ref=f"detail:data-query:{type(exc).__name__}",
            )
        finally:
            connection.close()
        self.execution_count += 1
        rows_json = canonical_json(rows)
        return CapabilityEffect(
            status=ReceiptStatus.SUCCEEDED,
            output={
                "query_id": str(payload.get("query_id", "query:unknown")),
                "sql_fingerprint": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                "query_result_digest": hashlib.sha256(
                    rows_json.encode("utf-8")
                ).hexdigest(),
                "row_count": len(rows),
                "rows_json": rows_json,
            },
        )


class DataAgentRuntime:
    def __init__(
        self,
        *,
        broker: CapabilityBroker,
        policy: PolicyKernel,
        correction: CorrectionReadPort,
        capability_spec: CapabilitySpec,
        grant: CapabilityGrant,
        checker: DataSQLSafetyChecker | None = None,
    ) -> None:
        self._broker = broker
        self._policy = policy
        self._correction = correction
        self._capability_spec = capability_spec
        self._grant = grant
        self._checker = checker or DataSQLSafetyChecker()

    def execute(self, request: DataAgentRequest) -> DataAgentResult:
        self._checker.check(request.safe_query.sql)
        action = self._build_action(request)
        decision = self._policy.decide(
            action,
            PolicyInput(
                principal=request.principal,
                grant=self._grant,
                capability=self._capability_spec,
                now=datetime.now(timezone.utc),
            ),
        )
        if decision.verdict is not PolicyVerdict.ALLOW:
            raise DataAgentDenied(f"POLICY_DENIED:{','.join(decision.reason_codes)}")
        permit = self._policy.permit(
            action,
            decision,
            self._grant,
            lease_fence=0,
            now=datetime.now(timezone.utc),
        )
        try:
            result = self._broker.invoke(action, permit)
        except CapabilityDenied as exc:
            raise DataAgentDenied(f"CAPABILITY_DENIED:{exc}") from exc
        trace_id = f"trace:{request.request_id}"
        if result.receipt.status is ReceiptStatus.UNKNOWN:
            return DataAgentResult(
                request_id=request.request_id,
                task_id=request.task_id,
                run_id=request.run_id,
                tenant_id=request.tenant_id,
                workspace_id=request.workspace_id,
                status=DataAgentStatus.HELP_REQUIRED,
                trace_id=trace_id,
                failure_code=result.receipt.error_code,
                resend_attempts=0,
            )
        if result.receipt.status is not ReceiptStatus.SUCCEEDED:
            return DataAgentResult(
                request_id=request.request_id,
                task_id=request.task_id,
                run_id=request.run_id,
                tenant_id=request.tenant_id,
                workspace_id=request.workspace_id,
                status=DataAgentStatus.DENIED,
                trace_id=trace_id,
                failure_code=result.receipt.error_code,
                resend_attempts=0,
            )
        query_result = self._validated_query_result(
            result.output,
            expected_query_id=request.safe_query.query_id,
        )
        evidence = DataEvidenceRef(
            evidence_id=f"data-evidence:{request.request_id}",
            generic_evidence_ref=result.receipt.receipt_id,
            metric_contract_digest=request.safe_query.metric.contract_digest,
            query_result_digest=query_result.query_result_digest,
        )
        return DataAgentResult(
            request_id=request.request_id,
            task_id=request.task_id,
            run_id=request.run_id,
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            status=DataAgentStatus.COMPLETED,
            trace_id=trace_id,
            query_result=query_result,
            evidence=evidence,
            observed_outcome_id=f"observed:{request.request_id}",
            resend_attempts=0,
        )

    @staticmethod
    def _validated_query_result(
        output: Mapping[str, object],
        *,
        expected_query_id: str,
    ) -> SafeQueryResult:
        try:
            query_id = output["query_id"]
            sql_fingerprint = output["sql_fingerprint"]
            query_result_digest = output["query_result_digest"]
            row_count = output["row_count"]
            rows_json = output["rows_json"]
            if (
                not isinstance(query_id, str)
                or query_id != expected_query_id
                or not isinstance(sql_fingerprint, str)
                or not isinstance(query_result_digest, str)
                or not isinstance(row_count, int)
                or isinstance(row_count, bool)
                or not isinstance(rows_json, str)
            ):
                raise ValueError("query output types or identity are invalid")
            rows: Any = json.loads(rows_json)
            if not isinstance(rows, list) or len(rows) != row_count:
                raise ValueError("query output row count is invalid")
            if canonical_json(rows) != rows_json:
                raise ValueError("query output rows are not canonical")
            if (
                hashlib.sha256(rows_json.encode("utf-8")).hexdigest()
                != query_result_digest
            ):
                raise ValueError("query output digest is invalid")
            return SafeQueryResult(
                query_id=query_id,
                sql_fingerprint=sql_fingerprint,
                query_result_digest=query_result_digest,
                row_count=row_count,
                rows_json=rows_json,
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            ValidationError,
        ) as exc:
            raise DataAgentDenied("MALFORMED_CAPABILITY_OUTPUT") from exc

    def _build_action(self, request: DataAgentRequest) -> ActionContract:
        query = request.safe_query
        return ActionContract(
            action_id=f"action-{uuid4()}",
            task_id=request.task_id,
            run_id=request.run_id,
            node_id="data-query",
            principal_id=request.principal.principal_id,
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            capability_id=DATA_QUERY_CAPABILITY_ID,
            capability_version="1",
            arguments_json=json.dumps(
                {
                    "query_id": query.query_id,
                    "sql": query.sql,
                    "parameters": json.loads(query.parameters_json),
                    "provider_contract_id": query.provider_contract_id,
                }
            ),
            risk_tier=0,
            idempotency_key=f"{request.run_id}:data-query:{query.query_id}",
            estimated_budget=ResourceBudget(
                max_cost_usd=Decimal("0"),
                max_duration_seconds=30,
                max_provider_tokens=0,
                max_tool_calls=1,
            ),
            policy_version=self._policy.policy_version,
            observed_correction_epochs=self._correction.snapshot(
                request.task_id,
                request.run_id,
                DATA_QUERY_CAPABILITY_ID,
            ),
            expected_outcome_id=request.expected_outcome_id,
            candidate_envelope_id=f"envelope:{request.request_id}",
            created_at=datetime.now(timezone.utc),
        )


__all__ = [
    "DATA_QUERY_CAPABILITY_ID",
    "DataAgentDenied",
    "DataAgentRuntime",
    "DataSQLSafetyChecker",
    "SQLiteDataQueryCapability",
]
