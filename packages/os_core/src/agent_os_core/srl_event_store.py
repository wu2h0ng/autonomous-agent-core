from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import NoReturn, TypeVar
from weakref import WeakKeyDictionary

from agent_os_contracts import (
    EnvironmentEventAdmissionReceipt,
    SituatedEvaluationTrace,
    SituatedTraceReason,
    SituatedTraceStatus,
    canonical_json,
)
from pydantic import BaseModel


class EventAdmissionPersistenceConflict(RuntimeError):
    """Durable event admission state is invalid or conflicts with an existing row."""


_ContractT = TypeVar("_ContractT", bound=BaseModel)
_FACTORY_KEY = object()


def _database_path(database: str | Path) -> str:
    value = str(database)
    if value == ":memory:":
        raise ValueError("SQLite event admission store requires a file-backed database")
    return value


def _connect(database: str) -> sqlite3.Connection:
    connection = sqlite3.connect(database, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _initialize(database: str) -> None:
    connection = _connect(database)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS srl_event_admission_receipts (
                receipt_id TEXT PRIMARY KEY,
                environment_event_id TEXT NOT NULL UNIQUE,
                receipt_digest TEXT NOT NULL UNIQUE,
                canonical_json BLOB NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS srl_situated_evaluation_traces (
                trace_id TEXT PRIMARY KEY,
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
    finally:
        connection.close()


def _canonical_bytes(contract: BaseModel) -> bytes:
    return canonical_json(contract).encode("utf-8")


def _validated_bytes(contract: _ContractT, contract_type: type[_ContractT]) -> bytes:
    payload = _canonical_bytes(contract)
    try:
        decoded = contract_type.model_validate_json(payload)
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
        decoded = contract_type.model_validate_json(payload)
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


class SQLiteEventAdmissionStore:
    """Public file-backed read view for admission receipts and situated traces."""

    durable = True

    def __init__(self, database: str | Path) -> None:
        self._database = _database_path(database)
        _initialize(self._database)

    def _receipt(self, field: str, value: str) -> EnvironmentEventAdmissionReceipt | None:
        connection = _connect(self._database)
        try:
            row = connection.execute(
                f"SELECT * FROM srl_event_admission_receipts WHERE {field} = ?",
                (value,),
            ).fetchone()
        finally:
            connection.close()
        return _decode_receipt(row) if row is not None else None

    def by_receipt_id(self, receipt_id: str) -> EnvironmentEventAdmissionReceipt | None:
        return self._receipt("receipt_id", receipt_id)

    def by_event_id(
        self, environment_event_id: str
    ) -> EnvironmentEventAdmissionReceipt | None:
        return self._receipt("environment_event_id", environment_event_id)

    def by_trace_id(self, trace_id: str) -> SituatedEvaluationTrace | None:
        connection = _connect(self._database)
        try:
            row = connection.execute(
                "SELECT * FROM srl_situated_evaluation_traces WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()
        finally:
            connection.close()
        return _decode_trace(row) if row is not None else None


class _EventAdmissionBackend:
    __slots__ = ("_database", "__bound_token")

    def __init__(self, database: str | Path, token: object, *, factory_key: object) -> None:
        if factory_key is not _FACTORY_KEY:
            raise TypeError("event admission backend is factory-bound")
        self._database = _database_path(database)
        self.__bound_token = token
        _initialize(self._database)

    def _require_token(self, token: object) -> None:
        if token is not self.__bound_token:
            raise EventAdmissionPersistenceConflict(
                "event admission write capability identity is invalid"
            )

    def persist_receipt(
        self,
        token: object,
        receipt: EnvironmentEventAdmissionReceipt,
    ) -> EnvironmentEventAdmissionReceipt:
        self._require_token(token)
        payload = _validated_bytes(receipt, EnvironmentEventAdmissionReceipt)
        connection = _connect(self._database)
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM srl_event_admission_receipts
                WHERE receipt_id = ? OR environment_event_id = ? OR receipt_digest = ?
                """,
                (
                    receipt.receipt_id,
                    receipt.environment_event_id,
                    receipt.receipt_digest,
                ),
            ).fetchall()
            if rows:
                existing = tuple(_decode_receipt(row) for row in rows)
                if (
                    len(existing) == 1
                    and existing[0] == receipt
                    and bytes(rows[0]["canonical_json"]) == payload
                ):
                    connection.rollback()
                    return existing[0]
                raise EventAdmissionPersistenceConflict(
                    "receipt id, event id, digest, or content conflicts with durable state"
                )
            connection.execute(
                """
                INSERT INTO srl_event_admission_receipts (
                    receipt_id, environment_event_id, receipt_digest, canonical_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    receipt.receipt_id,
                    receipt.environment_event_id,
                    receipt.receipt_digest,
                    payload,
                ),
            )
            connection.commit()
            return receipt
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def begin_trace(
        self,
        token: object,
        trace: SituatedEvaluationTrace,
    ) -> SituatedEvaluationTrace:
        self._require_token(token)
        payload = _validated_bytes(trace, SituatedEvaluationTrace)
        if (
            trace.status is not SituatedTraceStatus.PENDING
            or trace.reason is not SituatedTraceReason.ASSESSMENT_PENDING
            or trace.result_binding_digest is not None
        ):
            raise EventAdmissionPersistenceConflict(
                "trace must begin as PENDING with ASSESSMENT_PENDING and no result"
            )
        connection = _connect(self._database)
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM srl_situated_evaluation_traces
                WHERE trace_id = ?
                   OR (admission_receipt_digest = ? AND projection_id = ?)
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
                    connection.rollback()
                    return existing[0]
                raise EventAdmissionPersistenceConflict(
                    "trace id, receipt projection binding, or content conflicts"
                )
            try:
                connection.execute(
                    """
                    INSERT INTO srl_situated_evaluation_traces (
                        trace_id, admission_receipt_digest, projection_id,
                        status, reason, result_binding_digest,
                        delegation_attempt_count, canonical_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace.trace_id,
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
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def increment_delegation_attempt(
        self,
        token: object,
        trace_id: str,
        *,
        recorded_at: datetime | None = None,
    ) -> SituatedEvaluationTrace:
        self._require_token(token)
        connection = _connect(self._database)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM srl_situated_evaluation_traces WHERE trace_id = ?",
                (trace_id,),
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
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def transition_trace(
        self,
        token: object,
        terminal: SituatedEvaluationTrace,
    ) -> SituatedEvaluationTrace:
        self._require_token(token)
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

        connection = _connect(self._database)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM srl_situated_evaluation_traces WHERE trace_id = ?",
                (terminal.trace_id,),
            ).fetchone()
            if row is None:
                raise EventAdmissionPersistenceConflict("pending trace does not exist")
            current = _decode_trace(row)
            if current.status is not SituatedTraceStatus.PENDING:
                if current == terminal and bytes(row["canonical_json"]) == payload:
                    connection.rollback()
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
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


class _EventAdmissionWriter:
    __slots__ = ("_backend", "__weakref__")

    def __init__(
        self,
        backend: _EventAdmissionBackend,
        token: object,
        *,
        factory_key: object,
    ) -> None:
        if factory_key is not _FACTORY_KEY:
            raise TypeError("event admission writer is factory-bound")
        self._backend = backend
        _WRITER_TOKENS[self] = token

    def __copy__(self) -> None:
        raise TypeError("event admission writer cannot be copied")

    def __deepcopy__(self, memo: object) -> None:
        del memo
        raise TypeError("event admission writer cannot be copied")

    def __reduce__(self) -> NoReturn:
        raise TypeError("event admission writer cannot be serialized")

    def _token(self) -> object:
        token = _WRITER_TOKENS.get(self)
        if token is None:
            raise EventAdmissionPersistenceConflict(
                "event admission write capability identity is invalid"
            )
        return token

    def persist_receipt(
        self, receipt: EnvironmentEventAdmissionReceipt
    ) -> EnvironmentEventAdmissionReceipt:
        return self._backend.persist_receipt(self._token(), receipt)

    def begin_trace(self, trace: SituatedEvaluationTrace) -> SituatedEvaluationTrace:
        return self._backend.begin_trace(self._token(), trace)

    def increment_delegation_attempt(
        self,
        trace_id: str,
        *,
        recorded_at: datetime | None = None,
    ) -> SituatedEvaluationTrace:
        return self._backend.increment_delegation_attempt(
            self._token(), trace_id, recorded_at=recorded_at
        )

    def transition_trace(
        self, terminal: SituatedEvaluationTrace
    ) -> SituatedEvaluationTrace:
        return self._backend.transition_trace(self._token(), terminal)


_WRITER_TOKENS: WeakKeyDictionary[_EventAdmissionWriter, object] = WeakKeyDictionary()


def _create_event_admission_store(
    database: str | Path,
) -> tuple[SQLiteEventAdmissionStore, _EventAdmissionWriter]:
    token = object()
    backend = _EventAdmissionBackend(database, token, factory_key=_FACTORY_KEY)
    writer = _EventAdmissionWriter(
        backend,
        token,
        factory_key=_FACTORY_KEY,
    )
    return SQLiteEventAdmissionStore(database), writer
