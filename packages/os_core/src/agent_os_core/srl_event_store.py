from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import NoReturn, TypeVar

from agent_os_contracts import (
    EnvironmentEventAdmissionReceipt,
    LedgerAccessScope,
    SituatedEvaluationTrace,
    SituatedTraceReason,
    SituatedTraceStatus,
    canonical_json,
)
from pydantic import BaseModel


class EventAdmissionPersistenceConflict(RuntimeError):
    """Durable event admission state is invalid or conflicts with an existing row."""


_ContractT = TypeVar("_ContractT", bound=BaseModel)


def _database_path(database: str | Path) -> str:
    value = str(database)
    normalized = value.strip().lower()
    if (
        not normalized
        or normalized == ":memory:"
        or normalized.startswith("file:")
        or "mode=memory" in normalized
    ):
        raise ValueError("SQLite event admission store requires a file-backed database")
    path = Path(value).expanduser().resolve()
    if path.exists() and not path.is_file():
        raise ValueError("SQLite event admission store requires a file-backed database")
    return str(path)


def _sqlite_conflict(operation: str) -> EventAdmissionPersistenceConflict:
    return EventAdmissionPersistenceConflict(
        f"SQLite event admission {operation} failed"
    )


def _rollback(connection: sqlite3.Connection) -> None:
    try:
        connection.rollback()
    except sqlite3.Error:
        pass


def _connect(database: str) -> sqlite3.Connection:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(database, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
    except sqlite3.Error:
        if connection is not None:
            connection.close()
        raise _sqlite_conflict("connection") from None


def _connect_read_only(database: str) -> sqlite3.Connection:
    path = Path(database)
    if not path.is_file():
        raise EventAdmissionPersistenceConflict(
            "existing SQLite event admission store is required"
        )
    try:
        connection = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=10,
            isolation_level=None,
        )
    except sqlite3.Error:
        raise _sqlite_conflict("read-only connection") from None
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
    except sqlite3.Error:
        connection.close()
        raise _sqlite_conflict("read-only connection") from None


def _initialize(database: str) -> None:
    connection = _connect(database)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS srl_event_admission_receipts (
                receipt_id TEXT PRIMARY KEY,
                principal_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                environment_event_id TEXT NOT NULL,
                receipt_digest TEXT NOT NULL UNIQUE,
                canonical_json BLOB NOT NULL,
                UNIQUE (principal_id, tenant_id, workspace_id, environment_event_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS srl_situated_evaluation_traces (
                trace_id TEXT PRIMARY KEY,
                principal_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                admission_receipt_digest TEXT NOT NULL,
                projection_id TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT NOT NULL,
                result_binding_digest TEXT,
                delegation_attempt_count INTEGER NOT NULL,
                canonical_json BLOB NOT NULL,
                UNIQUE (admission_receipt_digest, projection_id),
                FOREIGN KEY (admission_receipt_digest)
                    REFERENCES srl_event_admission_receipts(receipt_digest)
            )
            """
        )
    except sqlite3.Error:
        raise _sqlite_conflict("schema initialization") from None
    finally:
        connection.close()


def _canonical_bytes(contract: BaseModel) -> bytes:
    return canonical_json(contract).encode("utf-8")


def _validated_bytes(contract: _ContractT, contract_type: type[_ContractT]) -> bytes:
    payload = _canonical_bytes(contract)
    try:
        decoded = contract_type.model_validate_json(payload, strict=True)
    except Exception:
        raise EventAdmissionPersistenceConflict(
            "contract content is invalid for durable persistence"
        ) from None
    if decoded != contract or _canonical_bytes(decoded) != payload:
        raise EventAdmissionPersistenceConflict(
            "contract content is not an exact canonical contract"
        )
    return payload


def _decode(
    raw_payload: object,
    contract_type: type[_ContractT],
    *,
    label: str,
) -> _ContractT:
    if isinstance(raw_payload, memoryview):
        payload = raw_payload.tobytes()
    elif isinstance(raw_payload, bytes):
        payload = raw_payload
    else:
        raise EventAdmissionPersistenceConflict(
            f"durable {label} state is invalid"
        )
    try:
        decoded = contract_type.model_validate_json(payload, strict=True)
    except Exception:
        raise EventAdmissionPersistenceConflict(
            f"durable {label} state is invalid"
        ) from None
    if _canonical_bytes(decoded) != payload:
        raise EventAdmissionPersistenceConflict(
            f"durable {label} bytes are not canonical"
        )
    return decoded


def _decode_receipt(row: sqlite3.Row) -> EnvironmentEventAdmissionReceipt:
    receipt = _decode(
        row["canonical_json"],
        EnvironmentEventAdmissionReceipt,
        label="event admission receipt",
    )
    if (
        row["principal_id"] != receipt.principal_id
        or row["tenant_id"] != receipt.tenant_id
        or row["workspace_id"] != receipt.workspace_id
    ):
        raise EventAdmissionPersistenceConflict(
            "durable event admission receipt scope conflicts with canonical bytes"
        )
    if (
        row["receipt_id"] != receipt.receipt_id
        or row["environment_event_id"] != receipt.environment_event_id
        or row["receipt_digest"] != receipt.receipt_digest
    ):
        raise EventAdmissionPersistenceConflict(
            "durable event admission receipt indexes conflict with canonical bytes"
        )
    return receipt


def _decode_trace(row: sqlite3.Row) -> SituatedEvaluationTrace:
    trace = _decode(
        row["canonical_json"],
        SituatedEvaluationTrace,
        label="situated evaluation trace",
    )
    if (
        row["trace_id"] != trace.trace_id
        or row["tenant_id"] != trace.tenant_id
        or row["workspace_id"] != trace.workspace_id
        or row["receipt_principal_id"] != row["principal_id"]
        or row["receipt_tenant_id"] != row["tenant_id"]
        or row["receipt_workspace_id"] != row["workspace_id"]
        or row["admission_receipt_digest"] != trace.admission_receipt_digest
        or row["projection_id"] != trace.projection_id
        or row["status"] != trace.status.value
        or row["reason"] != trace.reason.value
        or row["result_binding_digest"] != trace.result_binding_digest
        or row["delegation_attempt_count"] != trace.delegation_attempt_count
    ):
        raise EventAdmissionPersistenceConflict(
            "durable situated evaluation trace indexes conflict with canonical bytes"
        )
    return trace


class ScopedEventAdmissionReader:
    """File-backed read view confined to one authenticated ledger scope."""

    durable = True

    def __init__(self, database: str | Path, *, scope: LedgerAccessScope) -> None:
        self._database = _database_path(database)
        self.scope = scope
        connection = _connect_read_only(self._database)
        try:
            expected_columns = {
                "srl_event_admission_receipts": (
                    ("receipt_id", "TEXT", 0, 1),
                    ("principal_id", "TEXT", 1, 0),
                    ("tenant_id", "TEXT", 1, 0),
                    ("workspace_id", "TEXT", 1, 0),
                    ("environment_event_id", "TEXT", 1, 0),
                    ("receipt_digest", "TEXT", 1, 0),
                    ("canonical_json", "BLOB", 1, 0),
                ),
                "srl_situated_evaluation_traces": (
                    ("trace_id", "TEXT", 0, 1),
                    ("principal_id", "TEXT", 1, 0),
                    ("tenant_id", "TEXT", 1, 0),
                    ("workspace_id", "TEXT", 1, 0),
                    ("admission_receipt_digest", "TEXT", 1, 0),
                    ("projection_id", "TEXT", 1, 0),
                    ("status", "TEXT", 1, 0),
                    ("reason", "TEXT", 1, 0),
                    ("result_binding_digest", "TEXT", 0, 0),
                    ("delegation_attempt_count", "INTEGER", 1, 0),
                    ("canonical_json", "BLOB", 1, 0),
                ),
            }
            actual_columns = {
                table: tuple(
                    (
                        str(row["name"]),
                        str(row["type"]),
                        int(row["notnull"]),
                        int(row["pk"]),
                    )
                    for row in connection.execute(
                        f"PRAGMA table_info({table})"
                    ).fetchall()
                )
                for table in expected_columns
            }
            if actual_columns != expected_columns:
                raise EventAdmissionPersistenceConflict(
                    "existing SQLite event admission store schema is invalid"
                )
            unique_columns: dict[str, set[tuple[str, ...]]] = {}
            for table in expected_columns:
                unique_columns[table] = {
                    tuple(
                        str(column["name"])
                        for column in connection.execute(
                            f"PRAGMA index_info({row['name']})"
                        ).fetchall()
                    )
                    for row in connection.execute(
                        f"PRAGMA index_list({table})"
                    ).fetchall()
                    if int(row["unique"]) == 1
                }
            if unique_columns != {
                "srl_event_admission_receipts": {
                    ("receipt_id",),
                    ("receipt_digest",),
                    (
                        "principal_id",
                        "tenant_id",
                        "workspace_id",
                        "environment_event_id",
                    ),
                },
                "srl_situated_evaluation_traces": {
                    ("trace_id",),
                    ("admission_receipt_digest", "projection_id"),
                },
            }:
                raise EventAdmissionPersistenceConflict(
                    "existing SQLite event admission store schema is invalid"
                )
            foreign_keys = tuple(
                (
                    str(row["table"]),
                    str(row["from"]),
                    str(row["to"]),
                )
                for row in connection.execute(
                    "PRAGMA foreign_key_list(srl_situated_evaluation_traces)"
                ).fetchall()
            )
            if foreign_keys != (
                (
                    "srl_event_admission_receipts",
                    "admission_receipt_digest",
                    "receipt_digest",
                ),
            ):
                raise EventAdmissionPersistenceConflict(
                    "existing SQLite event admission store schema is invalid"
                )
        except sqlite3.Error:
            raise EventAdmissionPersistenceConflict(
                "existing SQLite event admission store schema is invalid"
            ) from None
        finally:
            connection.close()

    def _receipt(self, field: str, value: str) -> EnvironmentEventAdmissionReceipt | None:
        connection = _connect_read_only(self._database)
        try:
            if field == "environment_event_id":
                row = connection.execute(
                    """
                    SELECT * FROM srl_event_admission_receipts
                    WHERE environment_event_id = ? AND principal_id = ?
                      AND tenant_id = ? AND workspace_id = ?
                    """,
                    (
                        value,
                        self.scope.principal_id,
                        self.scope.tenant_id,
                        self.scope.workspace_id,
                    ),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM srl_event_admission_receipts WHERE receipt_id = ?",
                    (value,),
                ).fetchone()
        except sqlite3.Error:
            raise _sqlite_conflict("receipt read") from None
        finally:
            connection.close()
        if row is None:
            return None
        receipt = _decode_receipt(row)
        if (
            receipt.principal_id != self.scope.principal_id
            or receipt.tenant_id != self.scope.tenant_id
            or receipt.workspace_id != self.scope.workspace_id
        ):
            return None
        return receipt

    def by_receipt_id(self, receipt_id: str) -> EnvironmentEventAdmissionReceipt | None:
        return self._receipt("receipt_id", receipt_id)

    def by_event_id(
        self, environment_event_id: str
    ) -> EnvironmentEventAdmissionReceipt | None:
        return self._receipt("environment_event_id", environment_event_id)

    def by_trace_id(self, trace_id: str) -> SituatedEvaluationTrace | None:
        connection = _connect_read_only(self._database)
        try:
            row = connection.execute(
                """
                SELECT t.*,
                       r.principal_id AS receipt_principal_id,
                       r.tenant_id AS receipt_tenant_id,
                       r.workspace_id AS receipt_workspace_id
                FROM srl_situated_evaluation_traces AS t
                JOIN srl_event_admission_receipts AS r
                  ON r.receipt_digest = t.admission_receipt_digest
                WHERE t.trace_id = ?
                """,
                (trace_id,),
            ).fetchone()
        except sqlite3.Error:
            raise _sqlite_conflict("trace read") from None
        finally:
            connection.close()
        if row is None:
            return None
        trace = _decode_trace(row)
        if (
            row["principal_id"] != self.scope.principal_id
            or trace.tenant_id != self.scope.tenant_id
            or trace.workspace_id != self.scope.workspace_id
        ):
            return None
        return trace


class _EventAdmissionWriter:
    __slots__ = (
        "__persist_receipt_call",
        "__begin_trace_call",
        "__increment_attempt_call",
        "__transition_trace_call",
    )

    def __init__(self) -> None:
        raise TypeError("event admission writer is factory-bound")

    def __copy__(self) -> None:
        raise TypeError("event admission writer cannot be copied")

    def __deepcopy__(self, memo: object) -> None:
        del memo
        raise TypeError("event admission writer cannot be copied")

    def __reduce__(self) -> NoReturn:
        raise TypeError("event admission writer cannot be serialized")

    def _bound_call(self, attribute: str) -> Callable[..., object]:
        try:
            value = object.__getattribute__(self, attribute)
        except AttributeError:
            raise EventAdmissionPersistenceConflict(
                "event admission writer is unbound"
            ) from None
        if not callable(value):
            raise EventAdmissionPersistenceConflict(
                "event admission writer is unbound"
            )
        return value

    def persist_receipt(
        self, receipt: EnvironmentEventAdmissionReceipt
    ) -> EnvironmentEventAdmissionReceipt:
        call = self._bound_call("_EventAdmissionWriter__persist_receipt_call")
        result = call(receipt)
        if not isinstance(result, EnvironmentEventAdmissionReceipt):
            raise EventAdmissionPersistenceConflict("receipt write result is invalid")
        return result

    def begin_trace(self, trace: SituatedEvaluationTrace) -> SituatedEvaluationTrace:
        call = self._bound_call("_EventAdmissionWriter__begin_trace_call")
        result = call(trace)
        if not isinstance(result, SituatedEvaluationTrace):
            raise EventAdmissionPersistenceConflict("trace write result is invalid")
        return result

    def increment_delegation_attempt(
        self,
        trace_id: str,
        *,
        recorded_at: datetime | None = None,
    ) -> SituatedEvaluationTrace:
        call = self._bound_call("_EventAdmissionWriter__increment_attempt_call")
        result = call(trace_id, recorded_at=recorded_at)
        if not isinstance(result, SituatedEvaluationTrace):
            raise EventAdmissionPersistenceConflict("trace write result is invalid")
        return result

    def transition_trace(
        self, terminal: SituatedEvaluationTrace
    ) -> SituatedEvaluationTrace:
        call = self._bound_call("_EventAdmissionWriter__transition_trace_call")
        result = call(terminal)
        if not isinstance(result, SituatedEvaluationTrace):
            raise EventAdmissionPersistenceConflict("trace write result is invalid")
        return result


def _create_event_admission_store(
    database: str | Path,
    *,
    scope: LedgerAccessScope,
) -> tuple[ScopedEventAdmissionReader, _EventAdmissionWriter]:
    database_path = _database_path(database)
    _initialize(database_path)

    def persist_receipt(
        receipt: EnvironmentEventAdmissionReceipt,
    ) -> EnvironmentEventAdmissionReceipt:
        payload = _validated_bytes(receipt, EnvironmentEventAdmissionReceipt)
        if (
            receipt.principal_id != scope.principal_id
            or receipt.tenant_id != scope.tenant_id
            or receipt.workspace_id != scope.workspace_id
        ):
            raise EventAdmissionPersistenceConflict("receipt scope is not authorized")
        connection = _connect(database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM srl_event_admission_receipts
                WHERE receipt_id = ?
                   OR receipt_digest = ?
                   OR (
                       principal_id = ? AND tenant_id = ? AND workspace_id = ?
                       AND environment_event_id = ?
                   )
                """,
                (
                    receipt.receipt_id,
                    receipt.receipt_digest,
                    scope.principal_id,
                    scope.tenant_id,
                    scope.workspace_id,
                    receipt.environment_event_id,
                ),
            ).fetchall()
            if rows:
                existing = tuple(_decode_receipt(row) for row in rows)
                if (
                    len(existing) == 1
                    and existing[0] == receipt
                    and bytes(rows[0]["canonical_json"]) == payload
                ):
                    _rollback(connection)
                    return existing[0]
                raise EventAdmissionPersistenceConflict(
                    "receipt id, event id, digest, or content conflicts with durable state"
                )
            connection.execute(
                """
                INSERT INTO srl_event_admission_receipts (
                    receipt_id, principal_id, tenant_id, workspace_id,
                    environment_event_id, receipt_digest, canonical_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.receipt_id,
                    scope.principal_id,
                    scope.tenant_id,
                    scope.workspace_id,
                    receipt.environment_event_id,
                    receipt.receipt_digest,
                    payload,
                ),
            )
            connection.commit()
            return receipt
        except EventAdmissionPersistenceConflict:
            _rollback(connection)
            raise
        except sqlite3.Error:
            _rollback(connection)
            raise _sqlite_conflict("receipt write") from None
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()

    def begin_trace(trace: SituatedEvaluationTrace) -> SituatedEvaluationTrace:
        payload = _validated_bytes(trace, SituatedEvaluationTrace)
        if trace.tenant_id != scope.tenant_id or trace.workspace_id != scope.workspace_id:
            raise EventAdmissionPersistenceConflict("trace scope is not authorized")
        if (
            trace.status is not SituatedTraceStatus.PENDING
            or trace.reason is not SituatedTraceReason.ASSESSMENT_PENDING
            or trace.result_binding_digest is not None
        ):
            raise EventAdmissionPersistenceConflict(
                "trace must begin as PENDING with ASSESSMENT_PENDING and no result"
            )
        connection = _connect(database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            receipt_row = connection.execute(
                "SELECT * FROM srl_event_admission_receipts WHERE receipt_digest = ?",
                (trace.admission_receipt_digest,),
            ).fetchone()
            if receipt_row is None:
                raise EventAdmissionPersistenceConflict(
                    "trace admission receipt scope is unavailable"
                )
            receipt = _decode_receipt(receipt_row)
            if (
                receipt.principal_id != scope.principal_id
                or receipt.tenant_id != scope.tenant_id
                or receipt.workspace_id != scope.workspace_id
                or trace.event_id != receipt.environment_event_id
                or trace.mandate_id != receipt.mandate_id
            ):
                raise EventAdmissionPersistenceConflict(
                    "trace admission receipt scope is not authorized"
                )
            rows = connection.execute(
                """
                SELECT t.*,
                       r.principal_id AS receipt_principal_id,
                       r.tenant_id AS receipt_tenant_id,
                       r.workspace_id AS receipt_workspace_id
                FROM srl_situated_evaluation_traces AS t
                JOIN srl_event_admission_receipts AS r
                  ON r.receipt_digest = t.admission_receipt_digest
                WHERE (trace_id = ?
                   OR (admission_receipt_digest = ? AND projection_id = ?)
                )
                """,
                (
                    trace.trace_id,
                    trace.admission_receipt_digest,
                    trace.projection_id,
                ),
            ).fetchall()
            if rows:
                existing = tuple(_decode_trace(row) for row in rows)
                if len(existing) == 1 and existing[0].status is not SituatedTraceStatus.PENDING:
                    raise EventAdmissionPersistenceConflict(
                        "terminal trace is immutable and cannot return to PENDING"
                    )
                if (
                    len(existing) == 1
                    and existing[0] == trace
                    and bytes(rows[0]["canonical_json"]) == payload
                ):
                    _rollback(connection)
                    return existing[0]
                raise EventAdmissionPersistenceConflict(
                    "trace id, receipt projection binding, or content conflicts"
                )
            try:
                connection.execute(
                    """
                    INSERT INTO srl_situated_evaluation_traces (
                        trace_id, principal_id, tenant_id, workspace_id,
                        admission_receipt_digest, projection_id,
                        status, reason, result_binding_digest,
                        delegation_attempt_count, canonical_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace.trace_id,
                        scope.principal_id,
                        scope.tenant_id,
                        scope.workspace_id,
                        trace.admission_receipt_digest,
                        trace.projection_id,
                        trace.status.value,
                        trace.reason.value,
                        trace.result_binding_digest,
                        trace.delegation_attempt_count,
                        payload,
                    ),
                )
            except sqlite3.IntegrityError:
                raise EventAdmissionPersistenceConflict(
                    "trace admission receipt binding is unavailable or conflicts"
                ) from None
            connection.commit()
            return trace
        except EventAdmissionPersistenceConflict:
            _rollback(connection)
            raise
        except sqlite3.Error:
            _rollback(connection)
            raise _sqlite_conflict("trace begin") from None
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()

    def increment_delegation_attempt(
        trace_id: str,
        *,
        recorded_at: datetime | None = None,
    ) -> SituatedEvaluationTrace:
        connection = _connect(database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT t.*,
                       r.principal_id AS receipt_principal_id,
                       r.tenant_id AS receipt_tenant_id,
                       r.workspace_id AS receipt_workspace_id
                FROM srl_situated_evaluation_traces AS t
                JOIN srl_event_admission_receipts AS r
                  ON r.receipt_digest = t.admission_receipt_digest
                WHERE t.trace_id = ? AND t.principal_id = ?
                  AND t.tenant_id = ? AND t.workspace_id = ?
                """,
                (trace_id, scope.principal_id, scope.tenant_id, scope.workspace_id),
            ).fetchone()
            if row is None:
                raise EventAdmissionPersistenceConflict("pending trace does not exist")
            current = _decode_trace(row)
            if current.status is not SituatedTraceStatus.PENDING:
                raise EventAdmissionPersistenceConflict(
                    "terminal trace attempt history is immutable"
                )
            updated = current.model_copy(
                update={
                    "delegation_attempt_count": current.delegation_attempt_count + 1,
                    "recorded_at": recorded_at or current.recorded_at,
                }
            )
            payload = _validated_bytes(updated, SituatedEvaluationTrace)
            cursor = connection.execute(
                """
                UPDATE srl_situated_evaluation_traces
                SET delegation_attempt_count = ?, canonical_json = ?
                WHERE trace_id = ? AND status = 'PENDING'
                  AND delegation_attempt_count = ?
                """,
                (
                    updated.delegation_attempt_count,
                    payload,
                    trace_id,
                    current.delegation_attempt_count,
                ),
            )
            if cursor.rowcount != 1:
                raise EventAdmissionPersistenceConflict(
                    "pending trace attempt history changed concurrently"
                )
            connection.commit()
            return updated
        except EventAdmissionPersistenceConflict:
            _rollback(connection)
            raise
        except sqlite3.Error:
            _rollback(connection)
            raise _sqlite_conflict("trace attempt increment") from None
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()

    def transition_trace(
        terminal: SituatedEvaluationTrace,
    ) -> SituatedEvaluationTrace:
        payload = _validated_bytes(terminal, SituatedEvaluationTrace)
        completed_reasons = {
            SituatedTraceReason.TASK_DRAFT,
            SituatedTraceReason.HELP_REQUEST,
            SituatedTraceReason.NO_PROPOSAL,
        }
        denied_reasons = {
            SituatedTraceReason.ADMISSION_DENIED,
            SituatedTraceReason.AUTHORITY_CHANGED,
            SituatedTraceReason.PROVIDER_FAILED,
        }
        if terminal.status is SituatedTraceStatus.COMPLETED:
            legal = (
                terminal.reason in completed_reasons
                and terminal.result_binding_digest is not None
            )
        elif terminal.status is SituatedTraceStatus.DENIED:
            legal = terminal.reason in denied_reasons and terminal.result_binding_digest is None
        else:
            legal = False
        if not legal:
            raise EventAdmissionPersistenceConflict(
                "trace terminal status, reason, and result binding are illegal"
            )

        connection = _connect(database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT t.*,
                       r.principal_id AS receipt_principal_id,
                       r.tenant_id AS receipt_tenant_id,
                       r.workspace_id AS receipt_workspace_id
                FROM srl_situated_evaluation_traces AS t
                JOIN srl_event_admission_receipts AS r
                  ON r.receipt_digest = t.admission_receipt_digest
                WHERE t.trace_id = ? AND t.principal_id = ?
                  AND t.tenant_id = ? AND t.workspace_id = ?
                """,
                (
                    terminal.trace_id,
                    scope.principal_id,
                    scope.tenant_id,
                    scope.workspace_id,
                ),
            ).fetchone()
            if row is None:
                raise EventAdmissionPersistenceConflict("pending trace does not exist")
            current = _decode_trace(row)
            if current.status is not SituatedTraceStatus.PENDING:
                if current == terminal and bytes(row["canonical_json"]) == payload:
                    _rollback(connection)
                    return current
                raise EventAdmissionPersistenceConflict(
                    "terminal trace bytes and result binding are immutable"
                )

            immutable_fields = (
                "trace_id",
                "admission_receipt_digest",
                "event_id",
                "projection_id",
                "mandate_id",
                "tenant_id",
                "workspace_id",
                "delegation_attempt_count",
                "measurement_scope",
            )
            changed = tuple(
                field
                for field in immutable_fields
                if getattr(current, field) != getattr(terminal, field)
            )
            if changed:
                detail = "attempt history" if "delegation_attempt_count" in changed else "scope"
                raise EventAdmissionPersistenceConflict(
                    f"terminal trace {detail} conflicts with PENDING trace"
                )
            cursor = connection.execute(
                """
                UPDATE srl_situated_evaluation_traces
                SET status = ?, reason = ?, result_binding_digest = ?, canonical_json = ?
                WHERE trace_id = ? AND status = 'PENDING'
                  AND delegation_attempt_count = ?
                """,
                (
                    terminal.status.value,
                    terminal.reason.value,
                    terminal.result_binding_digest,
                    payload,
                    terminal.trace_id,
                    terminal.delegation_attempt_count,
                ),
            )
            if cursor.rowcount != 1:
                raise EventAdmissionPersistenceConflict(
                    "pending trace changed before terminal transition"
                )
            connection.commit()
            return terminal
        except EventAdmissionPersistenceConflict:
            _rollback(connection)
            raise
        except sqlite3.Error:
            _rollback(connection)
            raise _sqlite_conflict("trace transition") from None
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()

    writer = object.__new__(_EventAdmissionWriter)
    object.__setattr__(
        writer,
        "_EventAdmissionWriter__persist_receipt_call",
        persist_receipt,
    )
    object.__setattr__(
        writer,
        "_EventAdmissionWriter__begin_trace_call",
        begin_trace,
    )
    object.__setattr__(
        writer,
        "_EventAdmissionWriter__increment_attempt_call",
        increment_delegation_attempt,
    )
    object.__setattr__(
        writer,
        "_EventAdmissionWriter__transition_trace_call",
        transition_trace,
    )
    return ScopedEventAdmissionReader(database_path, scope=scope), writer
