from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import Any

from agent_os_contracts import (
    ActionContract,
    CapabilitySpec,
    ReceiptStatus,
    ResourceBudget,
    RunStatus,
    SideEffectGuarantee,
    TaskEventType,
)
from agent_os_contracts.common import canonical_json
from agent_os_core.capability import (
    CapabilityDenied,
    CapabilityEffect,
    CapabilityEffectUnknown,
    ExecutionLease,
)
from agent_os_core.action_pipeline import ActionPipeline
from agent_os_core.task_service import TaskService
from pydantic import ValidationError

from .contracts import (
    BusinessActionProposalRef,
    BusinessActionProposalRequest,
    DataAgentRequest,
    DataAgentResult,
    DataAgentStatus,
    DataEvidenceRef,
    SafeQueryResult,
)
from .errors import DataAgentDenied
from .evidence import derive_data_confidence
from .sql_safety import DataSQLSafetyChecker


DATA_QUERY_CAPABILITY_ID = "data.query.safe"
DATA_ACTION_PROPOSAL_CAPABILITY_ID = "data.action.propose"
SQLITE_PROVIDER_CONTRACT_ID = "provider:sqlite"
MYSQL_PROVIDER_CONTRACT_ID = "provider:mysql"


class _QueryExecutionError(Exception):
    """Driver-level failure raised by a provider fetch hook."""


class MySqlDataQueryConfig:
    """Composition-time MySQL connection config; secrets never rendered.

    ``from_env`` is the sanctioned loader: the password itself must live in
    an environment variable, and a missing reference fails closed.
    """

    __slots__ = ("host", "port", "database", "username", "password")

    def __init__(
        self,
        *,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
    ) -> None:
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password

    def __repr__(self) -> str:  # pragma: no cover - trivial redaction guard
        return (
            "MySqlDataQueryConfig(host={!r}, port={!r}, database={!r}, "
            "username={!r}, password='***')"
        ).format(self.host, self.port, self.database, self.username)

    @classmethod
    def from_env(
        cls,
        *,
        host: str,
        port: int,
        database: str,
        username: str,
        password_env: str,
    ) -> MySqlDataQueryConfig:
        import os

        password = os.environ.get(password_env)
        if password is None:
            raise ValueError(
                f"MySqlDataQueryConfig references environment variable "
                f"{password_env!r} which is not set; refusing to connect "
                f"without its secret."
            )
        return cls(
            host=host, port=port, database=database, username=username, password=password
        )


class SQLiteDataQueryCapability:
    """Read-only Data Agent query adapter behind the shared CapabilityBroker.

    ADR-0059 connector contract: the broker owns the durable reservation/
    outcome spine, so the adapter exposes outcomes/replay/preflight and the
    execution-lease primitives over the shared Task event store.
    """

    def __init__(
        self,
        database: str | Path,
        *,
        checker: DataSQLSafetyChecker | None = None,
        idempotency_store: Any | None = None,
    ) -> None:
        self._database = Path(database).resolve()
        self._checker = checker or DataSQLSafetyChecker()
        self._execution_count_lock = Lock()
        self.execution_count = 0
        self._idempotency_store = idempotency_store
        self._outcomes = None

    def bind_idempotency_store(self, store: Any) -> None:
        from agent_os_core._action_outcome import (
            DurableActionOutcomeRepository,
        )

        self._idempotency_store = store
        self._outcomes = DurableActionOutcomeRepository(store)

    def outcomes(self) -> Any:
        if self._outcomes is None and self._idempotency_store is not None:
            from agent_os_core._action_outcome import (
                DurableActionOutcomeRepository,
            )

            self._outcomes = DurableActionOutcomeRepository(
                self._idempotency_store
            )
        return self._outcomes

    def replay(self, action: ActionContract) -> Any:
        outcomes = self.outcomes()
        if outcomes is None:
            return None
        return outcomes.replay(action)

    def preflight(
        self,
        capability_id: str,
        args: dict[str, object],
        action_key: str,
    ) -> None:
        return None

    def acquire_execution_lease(
        self, action: ActionContract, owner: str
    ) -> ExecutionLease:
        outcomes = self.outcomes()
        if outcomes is None:
            raise CapabilityDenied(
                "durable idempotency store is required for execution lease"
            )
        return outcomes.acquire_execution_lease(action, owner)

    def release_execution_lease(self, lease: ExecutionLease) -> bool:
        outcomes = self.outcomes()
        if outcomes is None:
            raise CapabilityDenied(
                "durable idempotency store is required for execution lease"
            )
        return outcomes.release_execution_lease(lease)

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

    _provider_contract_id = SQLITE_PROVIDER_CONTRACT_ID

    def _fetch_rows(self, sql: str, parameters: dict[str, object]) -> list[dict]:
        connection = sqlite3.connect(
            f"file:{self._database}?mode=ro",
            uri=True,
            timeout=30,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only = ON")
            cursor = connection.execute(sql, parameters)
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            raise _QueryExecutionError(exc) from exc
        finally:
            connection.close()

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
        if provider_contract_id != self._provider_contract_id:
            return CapabilityEffect(
                status=ReceiptStatus.FAILED,
                output={},
                error_code="UNSUPPORTED_PROVIDER_CONTRACT",
                detail_ref="detail:data-query:unsupported-provider",
            )
        self._checker.assert_safe(sql, parameters)
        try:
            rows = self._fetch_rows(sql, parameters)
        except _QueryExecutionError as exc:
            return CapabilityEffect(
                status=ReceiptStatus.FAILED,
                output={},
                error_code="QUERY_EXECUTION_FAILED",
                detail_ref=f"detail:data-query:{type(exc.__cause__ or exc).__name__}",
            )
        with self._execution_count_lock:
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


class MySqlDataQueryCapability(SQLiteDataQueryCapability):
    """Read-only MySQL query adapter (Customer-0 cloud warehouses).

    Shares the broker-facing receipt/lease/idempotency contract with the
    SQLite capability; only the provider id, dialect and the fetch hook
    differ.  The driver (``pymysql``) is a soft dependency: importing it
    fails loudly at construction, never mid-execution.  ``:name`` bound
    parameters are translated to pymysql ``%(name)s`` style before dispatch;
    the AST gate has already validated the placeholder set.
    """

    _provider_contract_id = MYSQL_PROVIDER_CONTRACT_ID

    def __init__(
        self,
        config: MySqlDataQueryConfig,
        *,
        allowed_schemas: tuple[str, ...] = ("main",),
        checker: DataSQLSafetyChecker | None = None,
        idempotency_store: Any | None = None,
        _connect: Any | None = None,
    ) -> None:
        # Deliberately NOT calling SQLite's __init__ (no database path).
        self._config = config
        self._checker = checker or DataSQLSafetyChecker(
            allowed_schemas, dialect="mysql"
        )
        self._execution_count_lock = Lock()
        self.execution_count = 0
        self._idempotency_store = idempotency_store
        self._outcomes = None
        self._connect = _connect or self._default_connect

    def _default_connect(self) -> Any:
        try:
            import pymysql
            import pymysql.cursors
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise ImportError(
                "MySqlDataQueryCapability requires the 'pymysql' driver "
                "(pure-python); install it separately."
            ) from exc
        return pymysql.connect(
            host=self._config.host,
            port=self._config.port,
            database=self._config.database,
            user=self._config.username,
            password=self._config.password,
            connect_timeout=10,
            read_timeout=30,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )

    def _fetch_rows(self, sql: str, parameters: dict[str, object]) -> list[dict]:
        translated = _translate_named_parameters(sql)
        connection = self._connect()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(translated, dict(parameters))
                rows = list(cursor.fetchall())
            finally:
                cursor.close()
        except Exception as exc:  # pymysql.err.Error and transport errors
            raise _QueryExecutionError(exc) from exc
        finally:
            connection.close()
        return [dict(row) for row in rows]


_PARAMETER_PATTERN = None


def _translate_named_parameters(sql: str) -> str:
    """Translate ``:name`` placeholders to pymysql ``%(name)s`` style."""
    import re

    global _PARAMETER_PATTERN
    if _PARAMETER_PATTERN is None:
        _PARAMETER_PATTERN = re.compile(r"(?<![:\w']):([a-zA-Z_][a-zA-Z0-9_]*)")
    return _PARAMETER_PATTERN.sub(r"%(\1)s", sql)


class DataAgentRuntime:
    def __init__(
        self,
        *,
        tasks: TaskService,
        pipeline: ActionPipeline,
        capability_spec: CapabilitySpec,
        checker: DataSQLSafetyChecker | None = None,
    ) -> None:
        self._tasks = tasks
        self._pipeline = pipeline
        self._capability_spec = capability_spec
        self._checker = checker or DataSQLSafetyChecker()

    def execute(self, request: DataAgentRequest) -> DataAgentResult:
        parameters = json.loads(request.safe_query.parameters_json)
        self._checker.assert_safe(request.safe_query.sql, parameters)
        aggregate = self._tasks.get_task(request.task_id)
        if (
            aggregate.goal is None
            or aggregate.run is None
            or aggregate.expected_outcome is None
            or aggregate.workflow is None
        ):
            raise DataAgentDenied("TASK_BINDING_INCOMPLETE")
        if (
            aggregate.goal.tenant_id != request.tenant_id
            or aggregate.goal.workspace_id != request.workspace_id
            or aggregate.run.run_id != request.run_id
            or aggregate.expected_outcome.expected_outcome_id
            != request.expected_outcome_id
        ):
            raise DataAgentDenied("TASK_BINDING_MISMATCH")
        query_nodes = tuple(
            node
            for node in aggregate.workflow.nodes
            if node.node_id == "data-query"
            and node.capability == DATA_QUERY_CAPABILITY_ID
        )
        if len(query_nodes) != 1:
            raise DataAgentDenied("WORKFLOW_BINDING_MISMATCH")
        query = request.safe_query
        action = self._pipeline.build_action(
            task_id=request.task_id,
            run_id=request.run_id,
            node_id="data-query",
            capability_id=DATA_QUERY_CAPABILITY_ID,
            principal=request.principal,
            args={
                "query_id": query.query_id,
                "sql": query.sql,
                "parameters": parameters,
                "provider_contract_id": query.provider_contract_id,
            },
            expected=aggregate.expected_outcome,
            envelope_id=f"envelope:{request.request_id}",
            risk_tier=0,
            estimated_budget=ResourceBudget(
                max_cost_usd=Decimal("0"),
                max_duration_seconds=30,
                max_provider_tokens=0,
                max_tool_calls=1,
            ),
        )
        self._pipeline.record_action_proposed(action)
        # ADR-0059: every production dispatch carries an execution claim bound
        # to a fenced lease held in the shared Task store (founder P1).
        lease_expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
        acquire = getattr(self._tasks._event_store, "acquire_lease", None)
        if acquire is None:
            raise DataAgentDenied("EXECUTION_LEASE_UNAVAILABLE")
        lease_fence = acquire(
            request.run_id,
            "data-agent-runtime",
            lease_expiry.isoformat(),
        )
        try:
            result = self._pipeline.execute_observed(
                action,
                request.principal,
                capability_spec=self._capability_spec,
                record_artifacts=False,
                execution_claim=ExecutionLease(
                    run_id=request.run_id,
                    owner="data-agent-runtime",
                    fence=lease_fence,
                    expires_at=lease_expiry,
                ),
            )
        except CapabilityEffectUnknown as unknown:
            # ADR-0059: a post-dispatch UNKNOWN is a typed exception, never a
            # sealed FAILED outcome; it surfaces as an operator-help gap and
            # automatic resend stays forbidden.
            trace_id = f"trace:{request.request_id}"
            return DataAgentResult(
                request_id=request.request_id,
                task_id=request.task_id,
                run_id=request.run_id,
                tenant_id=request.tenant_id,
                workspace_id=request.workspace_id,
                status=DataAgentStatus.HELP_REQUIRED,
                trace_id=trace_id,
                failure_code=unknown.reason_code,
                resend_attempts=0,
            )
        except CapabilityDenied as exc:
            raise DataAgentDenied(f"CAPABILITY_DENIED:{exc}") from exc
        except PermissionError as exc:
            raise DataAgentDenied(f"POLICY_DENIED:{exc}") from exc
        trace_id = f"trace:{request.request_id}"
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
        confidence = derive_data_confidence(row_count=query_result.row_count)
        evidence = DataEvidenceRef(
            evidence_id=f"data-evidence:{request.request_id}",
            generic_evidence_ref=result.receipt.receipt_id,
            metric_contract_digest=request.safe_query.metric.contract_digest,
            query_result_digest=query_result.query_result_digest,
            provider_contract_id=request.safe_query.provider_contract_id,
            query_id=query_result.query_id,
            sql_fingerprint=query_result.sql_fingerprint,
            confidence_score=confidence.score,
            confidence_flags=confidence.flags,
            lineage_refs=(
                result.receipt.receipt_id,
                request.safe_query.provider_contract_id,
                query_result.query_id,
                request.safe_query.metric.contract_digest,
                query_result.sql_fingerprint,
                query_result.query_result_digest,
            ),
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

    def propose_action(
        self,
        request: BusinessActionProposalRequest,
    ) -> DataAgentResult:
        aggregate = self._tasks.get_task(request.task_id)
        if (
            aggregate.goal is None
            or aggregate.run is None
            or aggregate.expected_outcome is None
            or aggregate.workflow is None
            or aggregate.commitment is None
        ):
            raise DataAgentDenied("TASK_BINDING_INCOMPLETE")
        if (
            aggregate.goal.tenant_id != request.tenant_id
            or aggregate.goal.workspace_id != request.workspace_id
            or aggregate.run.run_id != request.run_id
            or aggregate.expected_outcome.expected_outcome_id
            != request.expected_outcome_id
        ):
            raise DataAgentDenied("TASK_BINDING_MISMATCH")
        proposal_nodes = tuple(
            node
            for node in aggregate.workflow.nodes
            if node.node_id == "data-action-proposal"
            and node.capability == DATA_ACTION_PROPOSAL_CAPABILITY_ID
        )
        if (
            len(proposal_nodes) != 1
            or DATA_ACTION_PROPOSAL_CAPABILITY_ID
            not in aggregate.commitment.authority_scopes
        ):
            raise DataAgentDenied("ACTION_PROPOSAL_NOT_AUTHORIZED")
        if aggregate.run.status in {RunStatus.CREATED, RunStatus.QUEUED}:
            self._tasks.update_run_status(
                request.task_id,
                RunStatus.RUNNING,
                event_type=TaskEventType.RUN_QUEUED,
                active_node_id="data-action-proposal",
            )
        elif aggregate.run.status is not RunStatus.RUNNING:
            raise DataAgentDenied("ACTION_PROPOSAL_RUN_NOT_EXECUTABLE")
        action = self._pipeline.build_action(
            task_id=request.task_id,
            run_id=request.run_id,
            node_id="data-action-proposal",
            capability_id=DATA_ACTION_PROPOSAL_CAPABILITY_ID,
            principal=request.principal,
            args={
                "target_capability_id": request.target_capability_id,
                "payload": json.loads(request.payload_json),
                "consequence_preview": request.consequence_preview,
                "alternatives": list(request.alternatives),
            },
            expected=aggregate.expected_outcome,
            envelope_id=f"envelope:{request.request_id}",
            risk_tier=request.risk_tier,
            estimated_budget=ResourceBudget(
                max_cost_usd=Decimal("0"),
                max_duration_seconds=30,
                max_provider_tokens=0,
                max_tool_calls=0,
            ),
            approval_requirement="external_exact",
        )
        self._pipeline.record_action_proposed(action)
        self._tasks.update_run_status(
            request.task_id,
            RunStatus.WAITING_APPROVAL,
            event_type=TaskEventType.APPROVAL_REQUESTED,
            active_node_id="data-action-proposal",
        )
        return DataAgentResult(
            request_id=request.request_id,
            task_id=request.task_id,
            run_id=request.run_id,
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            status=DataAgentStatus.AWAITING_APPROVAL,
            trace_id=f"trace:{request.request_id}",
            action_proposal=BusinessActionProposalRef(
                proposal_id=action.action_id,
                action_digest=action.action_digest(),
                capability_id=request.target_capability_id,
                consequence_preview=request.consequence_preview,
                alternatives=request.alternatives,
            ),
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


__all__ = [
    "DATA_QUERY_CAPABILITY_ID",
    "DATA_ACTION_PROPOSAL_CAPABILITY_ID",
    "DataAgentDenied",
    "DataAgentRuntime",
    "DataSQLSafetyChecker",
    "SQLiteDataQueryCapability",
]
