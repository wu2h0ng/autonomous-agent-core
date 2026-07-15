"""PostgreSQL/SQLAlchemy-Core implementations of the OS Core store Ports.

These adapters live OUTSIDE OS Core (which only owns the Port ABCs). They take an
injected SQLAlchemy *bind* — an ``Engine`` (each call its own transaction) or a
``Connection`` (transaction owned by a caller, e.g. a unit of work). This lets the
same store classes run standalone or inside :class:`SqlUnitOfWork` for atomic
multi-store writes. The code is dialect-portable: tests run it on SQLite;
production wires a PostgreSQL engine.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from agent_os_contracts import (
    FeedbackEvent,
    KnowledgeAsset,
    PolicyApprovalRecord,
    RunTrace,
    StateSnapshot,
    ApprovalWorkflow,
    AutoExecutionPolicy,
)
from agent_os_core import (
    ApprovalContextStorePort,
    ApprovalOperationContext,
    ApprovalRecord,
    ApprovalStorePort,
    CheckpointStorePort,
    FeedbackStorePort,
    KnowledgeStorePort,
    RunStateSnapshot,
    SnapshotStore,
    PolicyApprovalRecordStorePort,
    TraceStorePort,
)
from agent_os_core.policy_engine import AutoExecutionPolicyStorePort
from agent_os_core.workflow_store import WorkflowInstanceRecord, WorkflowStorePort
from sqlalchemy import Connection, Engine, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from . import mappers, schema


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _report_snapshot_digest(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _report_event_id(
    *,
    tenant_id: str,
    trace_id: str,
    revision: int,
    report_digest: str,
) -> str:
    identity_digest = _report_snapshot_digest(
        {
            "tenant_id": tenant_id,
            "trace_id": trace_id,
            "revision": revision,
            "report_digest": report_digest,
        }
    )
    return f"report-event:{identity_digest}"


def _conflict_summary(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation_id": payload["operation_id"],
        "action_type": payload["action_type"],
        "parameters_fingerprint": _fingerprint(dict(payload["parameters"])),
    }


def _uncertain_execution_summary(
    *,
    operation_id: str,
    action_type: str,
    parameters: dict[str, object],
    idempotency_key: str | None,
    reason_code: str,
    error_type: str,
) -> dict[str, object]:
    return {
        "operation_id": operation_id,
        "action_type": action_type,
        "idempotency_key": idempotency_key,
        "reason_code": reason_code,
        "error_type": error_type,
        "parameters_fingerprint": _fingerprint(parameters),
        "ack_status": "lost_after_write",
        "execution_certainty": "uncertain",
        "recorded_at": _utc_now().isoformat(),
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class _SqlStoreBase:
    """Bind-aware base: works against an Engine or an externally-managed Connection."""

    def __init__(self, bind: Engine | Connection) -> None:
        self._bind = bind

    @contextmanager
    def _write(self) -> Iterator[Connection]:
        if isinstance(self._bind, Connection):
            yield self._bind  # caller (unit of work) owns the transaction
        else:
            with self._bind.begin() as conn:
                yield conn

    @contextmanager
    def _read(self) -> Iterator[Connection]:
        if isinstance(self._bind, Connection):
            yield self._bind
        else:
            with self._bind.connect() as conn:
                yield conn


class SqlFeedbackStore(_SqlStoreBase, FeedbackStorePort):
    """Append-only feedback store backed by SQLAlchemy Core."""

    def record(self, event: FeedbackEvent, *, tenant_id: str = "default") -> FeedbackEvent:
        with self._write() as conn:
            conn.execute(
                schema.feedback_events.insert().values(
                    tenant_id=tenant_id,
                    feedback_id=event.feedback_id,
                    trace_id=event.trace_id,
                    payload=mappers.feedback_to_payload(event),
                )
            )
        return event

    def get_by_trace(
        self, trace_id: str, *, tenant_id: str = "default"
    ) -> tuple[FeedbackEvent, ...]:
        table = schema.feedback_events
        stmt = (
            select(table.c.payload)
            .where(table.c.tenant_id == tenant_id)
            .where(table.c.trace_id == trace_id)
            .order_by(table.c.id)
        )
        with self._read() as conn:
            rows = conn.execute(stmt).fetchall()
        return tuple(mappers.feedback_from_payload(row[0]) for row in rows)

    def all_events(self, *, tenant_id: str = "default") -> tuple[FeedbackEvent, ...]:
        table = schema.feedback_events
        stmt = select(table.c.payload).where(table.c.tenant_id == tenant_id).order_by(table.c.id)
        with self._read() as conn:
            rows = conn.execute(stmt).fetchall()
        return tuple(mappers.feedback_from_payload(row[0]) for row in rows)

    def outcome_counts(self, *, tenant_id: str = "default") -> dict[str, int]:
        return dict(Counter(event.outcome for event in self.all_events(tenant_id=tenant_id)))


class SqlKnowledgeStore(_SqlStoreBase, KnowledgeStorePort):
    """Knowledge-asset store with dedup/versioning backed by SQLAlchemy Core."""

    def register(self, asset: KnowledgeAsset, *, tenant_id: str = "default") -> KnowledgeAsset:
        key = asset.source_trace_id
        if key is None:
            raise ValueError("KnowledgeAsset.source_trace_id is required for dedup")
        table = schema.knowledge_assets
        with self._write() as conn:
            existing = conn.execute(
                select(table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.source_trace_id == key)
            ).fetchone()
            if existing is not None:
                return mappers.knowledge_from_payload(existing[0])
            conn.execute(
                table.insert().values(
                    tenant_id=tenant_id,
                    source_trace_id=key,
                    version=1,
                    payload=mappers.knowledge_to_payload(asset),
                )
            )
        return asset

    def register_version(
        self, asset: KnowledgeAsset, *, tenant_id: str = "default"
    ) -> KnowledgeAsset:
        key = asset.source_trace_id
        if key is None:
            raise ValueError("KnowledgeAsset.source_trace_id is required for dedup")
        table = schema.knowledge_assets
        payload = mappers.knowledge_to_payload(asset)
        with self._write() as conn:
            updated = conn.execute(
                table.update()
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.source_trace_id == key)
                .values(version=table.c.version + 1, payload=payload)
            )
            if updated.rowcount == 0:
                conn.execute(
                    table.insert().values(
                        tenant_id=tenant_id,
                        source_trace_id=key,
                        version=1,
                        payload=payload,
                    )
                )
        return asset

    def get_by_trace(self, trace_id: str, *, tenant_id: str = "default") -> KnowledgeAsset | None:
        table = schema.knowledge_assets
        with self._read() as conn:
            stmt = (
                select(table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.source_trace_id == trace_id)
            )
            if isinstance(self._bind, Connection):
                stmt = stmt.with_for_update()
            row = conn.execute(stmt).fetchone()
        return mappers.knowledge_from_payload(row[0]) if row is not None else None

    def version_of(self, trace_id: str, *, tenant_id: str = "default") -> int:
        table = schema.knowledge_assets
        with self._read() as conn:
            row = conn.execute(
                select(table.c.version)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.source_trace_id == trace_id)
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def all_assets(self, *, tenant_id: str = "default") -> tuple[KnowledgeAsset, ...]:
        table = schema.knowledge_assets
        with self._read() as conn:
            rows = conn.execute(
                select(table.c.payload).where(table.c.tenant_id == tenant_id)
            ).fetchall()
        return tuple(mappers.knowledge_from_payload(row[0]) for row in rows)


class SqlSnapshotStore(_SqlStoreBase, SnapshotStore):
    """State-snapshot store backed by SQLAlchemy Core."""

    def save(self, snapshot: StateSnapshot, *, tenant_id: str = "default") -> StateSnapshot:
        table = schema.state_snapshots
        payload = mappers.snapshot_to_payload(snapshot)
        with self._write() as conn:
            exists = conn.execute(
                select(table.c.snapshot_id)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.snapshot_id == snapshot.snapshot_id)
            ).fetchone()
            if exists is None:
                conn.execute(
                    table.insert().values(
                        tenant_id=tenant_id,
                        snapshot_id=snapshot.snapshot_id,
                        operation_id=snapshot.operation_id,
                        payload=payload,
                    )
                )
            else:
                conn.execute(
                    table.update()
                    .where(table.c.tenant_id == tenant_id)
                    .where(table.c.snapshot_id == snapshot.snapshot_id)
                    .values(operation_id=snapshot.operation_id, payload=payload)
                )
        return snapshot

    def get(self, snapshot_id: str, *, tenant_id: str = "default") -> StateSnapshot | None:
        table = schema.state_snapshots
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.snapshot_id == snapshot_id)
            ).fetchone()
        return mappers.snapshot_from_payload(row[0]) if row is not None else None

    def list_for_operation(
        self, operation_id: str, *, tenant_id: str = "default"
    ) -> tuple[StateSnapshot, ...]:
        table = schema.state_snapshots
        stmt = (
            select(table.c.payload)
            .where(table.c.tenant_id == tenant_id)
            .where(table.c.operation_id == operation_id)
            .order_by(table.c.snapshot_id)
        )
        with self._read() as conn:
            rows = conn.execute(stmt).fetchall()
        return tuple(mappers.snapshot_from_payload(row[0]) for row in rows)


class SqlAgentCheckpointStore(_SqlStoreBase, CheckpointStorePort):
    """Durable Agent Runtime checkpoint store backed by SQLAlchemy Core."""

    def save(self, snapshot: RunStateSnapshot, *, tenant_id: str = "default") -> None:
        table = schema.agent_runtime_checkpoints
        payload = mappers.run_state_snapshot_to_payload(snapshot)
        with self._write() as conn:
            exists = conn.execute(
                select(table.c.run_id)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.run_id == snapshot.run_id)
            ).fetchone()
            values = {
                "tenant_id": tenant_id,
                "run_id": snapshot.run_id,
                "trace_id": snapshot.trace_id,
                "step_id": snapshot.step_id,
                "status": snapshot.status,
                "payload": payload,
            }
            if exists is None:
                conn.execute(table.insert().values(**values))
            else:
                conn.execute(
                    table.update()
                    .where(table.c.tenant_id == tenant_id)
                    .where(table.c.run_id == snapshot.run_id)
                    .values(**values)
                )

    def get(self, run_id: str, *, tenant_id: str = "default") -> RunStateSnapshot | None:
        table = schema.agent_runtime_checkpoints
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.run_id == run_id)
            ).fetchone()
        return mappers.run_state_snapshot_from_payload(row[0]) if row is not None else None


class SqlReportSnapshotStore(_SqlStoreBase):
    """Durable read-side store for already-built report projections."""

    _audiences = {"internal", "external"}

    @staticmethod
    def _lock_revision_state(conn: Connection, *, tenant_id: str, trace_id: str) -> int:
        """Serialize report revision comparison/allocation for one tenant trace."""

        table = schema.report_snapshot_event_revisions
        values = {"tenant_id": tenant_id, "trace_id": trace_id, "last_revision": 0}
        if conn.dialect.name == "postgresql":
            statement = (
                postgresql_insert(table)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[table.c.tenant_id, table.c.trace_id],
                    set_={"last_revision": table.c.last_revision},
                )
            )
        elif conn.dialect.name == "sqlite":
            statement = (
                sqlite_insert(table)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[table.c.tenant_id, table.c.trace_id],
                    set_={"last_revision": table.c.last_revision},
                )
            )
        else:
            raise RuntimeError("report revision serialization supports only PostgreSQL and SQLite")
        # The conflict-update path obtains a row lock on PostgreSQL. SQLite
        # serializes this write transaction. Both locks live until commit.
        conn.execute(statement)
        return int(
            conn.execute(
                select(table.c.last_revision)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.trace_id == trace_id)
            ).scalar_one()
        )

    def save(
        self,
        trace_id: str,
        snapshots_by_audience: dict[str, dict[str, object]],
        *,
        tenant_id: str = "default",
    ) -> None:
        table = schema.report_snapshots
        events = schema.report_snapshot_events
        with self._write() as conn:
            last_revision = None
            if "external" in snapshots_by_audience:
                last_revision = self._lock_revision_state(
                    conn,
                    tenant_id=tenant_id,
                    trace_id=trace_id,
                )
            for audience, snapshot in snapshots_by_audience.items():
                if audience not in self._audiences:
                    continue
                payload = copy.deepcopy(snapshot)
                existing = conn.execute(
                    select(table.c.payload)
                    .where(table.c.tenant_id == tenant_id)
                    .where(table.c.trace_id == trace_id)
                    .where(table.c.audience == audience)
                ).fetchone()
                if audience == "external":
                    report_digest = _report_snapshot_digest(payload)
                    previous_digest = (
                        _report_snapshot_digest(dict(existing[0])) if existing is not None else None
                    )
                    if report_digest != previous_digest:
                        if last_revision is None:
                            raise RuntimeError("report revision state was not locked")
                        revision = last_revision + 1
                        event_id = _report_event_id(
                            tenant_id=tenant_id,
                            trace_id=trace_id,
                            revision=revision,
                            report_digest=report_digest,
                        )
                        conn.execute(
                            events.insert().values(
                                tenant_id=tenant_id,
                                event_id=event_id,
                                trace_id=trace_id,
                                revision=revision,
                                report_digest=report_digest,
                                report_payload=payload,
                                recorded_at=_utc_now(),
                            )
                        )
                        conn.execute(
                            schema.report_snapshot_event_revisions.update()
                            .where(schema.report_snapshot_event_revisions.c.tenant_id == tenant_id)
                            .where(schema.report_snapshot_event_revisions.c.trace_id == trace_id)
                            .values(last_revision=revision)
                        )
                        last_revision = revision
                values = {
                    "tenant_id": tenant_id,
                    "trace_id": trace_id,
                    "audience": audience,
                    "payload": payload,
                }
                if existing is None:
                    conn.execute(table.insert().values(**values))
                else:
                    conn.execute(
                        table.update()
                        .where(table.c.tenant_id == tenant_id)
                        .where(table.c.trace_id == trace_id)
                        .where(table.c.audience == audience)
                        .values(payload=payload)
                    )

    def get(
        self, trace_id: str, audience: str, *, tenant_id: str = "default"
    ) -> dict[str, object] | None:
        table = schema.report_snapshots
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.trace_id == trace_id)
                .where(table.c.audience == audience)
            ).fetchone()
        return copy.deepcopy(dict(row[0])) if row is not None else None

    def list_events(
        self,
        *,
        after_sequence: int,
        limit: int,
        tenant_id: str = "default",
    ) -> tuple[tuple[dict[str, object], ...], bool]:
        if after_sequence < 0:
            raise ValueError("after_sequence cannot be negative")
        if limit <= 0:
            raise ValueError("limit must be positive")
        table = schema.report_snapshot_events
        with self._read() as conn:
            rows = conn.execute(
                select(
                    table.c.sequence,
                    table.c.event_id,
                    table.c.trace_id,
                    table.c.revision,
                    table.c.report_digest,
                    table.c.report_payload,
                    table.c.recorded_at,
                )
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.sequence > after_sequence)
                .order_by(table.c.sequence.asc())
                .limit(limit + 1)
            ).fetchall()
        page = []
        for row in rows[:limit]:
            if row.report_payload is None:
                raise RuntimeError(
                    "legacy report event lacks an immutable payload; replay is required"
                )
            page.append(
                {
                    "sequence": int(row.sequence),
                    "event_id": str(row.event_id),
                    "trace_id": str(row.trace_id),
                    "revision": int(row.revision),
                    "report_digest": str(row.report_digest),
                    "report": copy.deepcopy(dict(row.report_payload)),
                    "recorded_at": row.recorded_at,
                }
            )
        return tuple(page), len(rows) > limit


class SqlActionRecordStore(_SqlStoreBase):
    """Durable side-effect ledger for the action_record connector.

    This class intentionally implements the connector store interface
    (``add/records/snapshot_state/restore``) rather than an OS Core Port: the
    ledger is connector-specific state and OS Core must stay unaware of it.
    """

    def add(
        self,
        *,
        operation_id: str,
        action_type: str,
        parameters: dict[str, object],
        idempotency_key: str | None = None,
        tenant_id: str = "default",
    ) -> dict[str, object]:
        table = schema.action_records
        request_payload: dict[str, object] = {
            "operation_id": operation_id,
            "action_type": action_type,
            "parameters": copy.deepcopy(parameters),
        }
        conflict_error: ValueError | None = None

        with self._write() as conn:
            if idempotency_key is not None:
                existing = conn.execute(
                    select(table.c.id, table.c.payload)
                    .where(table.c.tenant_id == tenant_id)
                    .where(table.c.idempotency_key == idempotency_key)
                ).fetchone()
                if existing is not None:
                    row_id = existing[0]
                    original_record = copy.deepcopy(dict(existing[1]))
                    original_payload = {
                        "operation_id": original_record["operation_id"],
                        "action_type": original_record["action_type"],
                        "parameters": copy.deepcopy(original_record["parameters"]),
                    }
                    if original_payload != request_payload:
                        original_record["conflict_count"] = (
                            int(original_record.get("conflict_count", 0)) + 1
                        )
                        original_record["last_conflict"] = _conflict_summary(request_payload)
                        conn.execute(
                            table.update()
                            .where(table.c.id == row_id)
                            .values(payload=copy.deepcopy(original_record))
                        )
                        conflict_error = ValueError(
                            "idempotency_key was reused with a different operation/action payload"
                        )
                    else:
                        original_record["replay_count"] = (
                            int(original_record.get("replay_count", 0)) + 1
                        )
                        original_record["last_replay_status"] = "idempotent_replay"
                        if int(original_record.get("uncertain_execution_count", 0)) > 0:
                            original_record["last_replay_status"] = (
                                "idempotent_replay_after_uncertain"
                            )
                        conn.execute(
                            table.update()
                            .where(table.c.id == row_id)
                            .values(payload=copy.deepcopy(original_record))
                        )
                        original_record["status"] = "idempotent_replay"
                        if int(original_record.get("uncertain_execution_count", 0)) > 0:
                            original_record["execution_certainty"] = "uncertain_recovered"
                            original_record["ack_status"] = (
                                "lost_after_write_recovered_by_idempotency"
                            )
                        return original_record

            if conflict_error is None:
                record: dict[str, object] = {
                    "record_id": f"record-{uuid4().hex[:12]}",
                    **request_payload,
                    "replay_count": 0,
                    "conflict_count": 0,
                    "uncertain_execution_count": 0,
                }
                if idempotency_key is not None:
                    record["idempotency_key"] = idempotency_key
                conn.execute(
                    table.insert().values(
                        tenant_id=tenant_id,
                        record_id=record["record_id"],
                        operation_id=operation_id,
                        action_type=action_type,
                        idempotency_key=idempotency_key,
                        payload=copy.deepcopy(record),
                    )
                )
        if conflict_error is not None:
            raise conflict_error
        return copy.deepcopy(record)

    def records(self, *, tenant_id: str = "default") -> tuple[dict[str, object], ...]:
        table = schema.action_records
        with self._read() as conn:
            rows = conn.execute(
                select(table.c.payload).where(table.c.tenant_id == tenant_id).order_by(table.c.id)
            ).fetchall()
        return tuple(copy.deepcopy(dict(row[0])) for row in rows)

    def mark_execution_uncertain(
        self,
        *,
        record_id: str,
        operation_id: str,
        action_type: str,
        idempotency_key: str | None,
        parameters: dict[str, object],
        reason_code: str,
        error_type: str,
        tenant_id: str = "default",
    ) -> dict[str, object]:
        table = schema.action_records
        with self._write() as conn:
            row = conn.execute(
                select(table.c.id, table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.record_id == record_id)
            ).fetchone()
            if row is None:
                raise KeyError(f"record_id '{record_id}' is not present in the store")
            row_id = row[0]
            record = copy.deepcopy(dict(row[1]))
            record["uncertain_execution_count"] = (
                int(record.get("uncertain_execution_count", 0)) + 1
            )
            record["last_uncertain_execution"] = _uncertain_execution_summary(
                operation_id=operation_id,
                action_type=action_type,
                parameters=parameters,
                idempotency_key=idempotency_key,
                reason_code=reason_code,
                error_type=error_type,
            )
            conn.execute(
                table.update().where(table.c.id == row_id).values(payload=copy.deepcopy(record))
            )
        return copy.deepcopy(record)

    def snapshot_state(self, *, tenant_id: str = "default") -> dict[str, object]:
        return {"records": [copy.deepcopy(record) for record in self.records(tenant_id=tenant_id)]}

    def restore(self, state_payload: dict[str, object], *, tenant_id: str = "default") -> None:
        table = schema.action_records
        raw_records = state_payload.get("records") or []
        records = [copy.deepcopy(dict(record)) for record in raw_records]
        rollback_operation_id = state_payload.get("rollback_operation_id")
        with self._write() as conn:
            if rollback_operation_id is None:
                conn.execute(table.delete().where(table.c.tenant_id == tenant_id))
            else:
                snapshot_record_ids = {record["record_id"] for record in records}
                conn.execute(
                    table.delete()
                    .where(table.c.tenant_id == tenant_id)
                    .where(table.c.operation_id == rollback_operation_id)
                    .where(table.c.record_id.not_in(snapshot_record_ids))
                )
                return
            for record in records:
                conn.execute(
                    table.insert().values(
                        tenant_id=tenant_id,
                        record_id=record["record_id"],
                        operation_id=record["operation_id"],
                        action_type=record["action_type"],
                        idempotency_key=record.get("idempotency_key"),
                        payload=copy.deepcopy(record),
                    )
                )


class SqlApprovalStore(_SqlStoreBase, ApprovalStorePort):
    """Approval-record store (upsert by approval_id) backed by SQLAlchemy Core."""

    def save(self, record: ApprovalRecord, *, tenant_id: str = "default") -> ApprovalRecord:
        table = schema.approval_records
        payload = mappers.approval_to_payload(record)
        with self._write() as conn:
            exists = conn.execute(
                select(table.c.approval_id)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.approval_id == record.approval_id)
            ).fetchone()
            if exists is None:
                conn.execute(
                    table.insert().values(
                        tenant_id=tenant_id,
                        approval_id=record.approval_id,
                        proposal_id=record.proposal_id,
                        payload=payload,
                    )
                )
            else:
                conn.execute(
                    table.update()
                    .where(table.c.tenant_id == tenant_id)
                    .where(table.c.approval_id == record.approval_id)
                    .values(proposal_id=record.proposal_id, payload=payload)
                )
        return record

    def get(self, approval_id: str, *, tenant_id: str = "default") -> ApprovalRecord | None:
        table = schema.approval_records
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.approval_id == approval_id)
            ).fetchone()
        return mappers.approval_from_payload(row[0]) if row is not None else None

    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        tenant_id: str = "default",
    ) -> tuple[ApprovalRecord, ...]:
        table = schema.approval_records
        with self._read() as conn:
            query = select(table.c.payload).where(table.c.tenant_id == tenant_id)
            if status is not None:
                query = query.where(table.c.payload["status"].as_string() == status)
            query = query.order_by(table.c.approval_id.asc())
            rows = conn.execute(query.limit(limit).offset(offset)).fetchall()
        return tuple(mappers.approval_from_payload(row[0]) for row in rows)


class SqlApprovalContextStore(_SqlStoreBase, ApprovalContextStorePort):
    """Approval-resume context store backed by SQLAlchemy Core."""

    def __init__(self, bind: Engine | Connection, *, clock: Callable[[], datetime] | None = None):
        super().__init__(bind)
        self._clock = clock or _utc_now

    def save(
        self, context: ApprovalOperationContext, *, tenant_id: str = "default"
    ) -> ApprovalOperationContext:
        table = schema.approval_operation_contexts
        payload = mappers.approval_context_to_payload(context)
        with self._write() as conn:
            exists = conn.execute(
                select(table.c.approval_id)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.approval_id == context.approval_id)
            ).fetchone()
            values = {
                "tenant_id": tenant_id,
                "approval_id": context.approval_id,
                "proposal_id": context.proposal_id,
                "operation_id": context.operation.operation_id,
                "trace_id": context.evidence_chain.trace_id,
                "status": "pending",
                "payload": payload,
            }
            if exists is None:
                conn.execute(table.insert().values(**values))
            else:
                conn.execute(
                    table.update()
                    .where(table.c.tenant_id == tenant_id)
                    .where(table.c.approval_id == context.approval_id)
                    .values(**values)
                )
        return context

    def get(
        self, approval_id: str, *, tenant_id: str = "default"
    ) -> ApprovalOperationContext | None:
        table = schema.approval_operation_contexts
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.approval_id == approval_id)
            ).fetchone()
        return mappers.approval_context_from_payload(row[0]) if row is not None else None

    def claim(
        self,
        approval_id: str,
        *,
        reclaim_stale_after_seconds: float | None = None,
        tenant_id: str = "default",
    ) -> ApprovalOperationContext | None:
        table = schema.approval_operation_contexts
        with self._write() as conn:
            row = conn.execute(
                select(table.c.status, table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.approval_id == approval_id)
            ).fetchone()
            if row is None:
                return None
            status = row.status
            payload = copy.deepcopy(dict(row.payload))
            if status == "executing":
                if not self._is_stale_claim(
                    payload,
                    reclaim_stale_after_seconds=reclaim_stale_after_seconds,
                ):
                    return None
            elif status != "pending":
                return None

            claimed_payload = self._with_claim(payload)
            update = (
                table.update()
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.approval_id == approval_id)
                .where(table.c.status == status)
            )
            if status == "executing":
                update = update.where(
                    table.c.payload["_claim"]["claimed_at"].as_string()
                    == self._claim_token(payload)
                )
            result = conn.execute(update.values(status="executing", payload=claimed_payload))
            if result.rowcount != 1:
                return None
        return mappers.approval_context_from_payload(claimed_payload)

    def release_claim(self, approval_id: str, *, tenant_id: str = "default") -> None:
        table = schema.approval_operation_contexts
        with self._write() as conn:
            row = conn.execute(
                select(table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.approval_id == approval_id)
            ).fetchone()
            payload = copy.deepcopy(dict(row.payload)) if row is not None else {}
            payload.pop("_claim", None)
            conn.execute(
                table.update()
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.approval_id == approval_id)
                .where(table.c.status == "executing")
                .values(status="pending", payload=payload)
            )

    def delete(self, approval_id: str, *, tenant_id: str = "default") -> None:
        table = schema.approval_operation_contexts
        with self._write() as conn:
            conn.execute(
                table.delete()
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.approval_id == approval_id)
            )

    def _with_claim(self, payload: dict[str, object]) -> dict[str, object]:
        updated = copy.deepcopy(payload)
        updated["_claim"] = {"claimed_at": self._clock().astimezone(timezone.utc).isoformat()}
        return updated

    def _claim_token(self, payload: dict[str, object]) -> str | None:
        claim = payload.get("_claim")
        if not isinstance(claim, dict):
            return None
        claimed_at = claim.get("claimed_at")
        return claimed_at if isinstance(claimed_at, str) else None

    def _is_stale_claim(
        self,
        payload: dict[str, object],
        *,
        reclaim_stale_after_seconds: float | None,
    ) -> bool:
        if reclaim_stale_after_seconds is None:
            return False
        claim = payload.get("_claim")
        if not isinstance(claim, dict):
            return False
        claimed_at_raw = claim.get("claimed_at")
        if not isinstance(claimed_at_raw, str):
            return False
        claimed_at = datetime.fromisoformat(claimed_at_raw)
        if claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=timezone.utc)
        elapsed = (self._clock().astimezone(timezone.utc) - claimed_at).total_seconds()
        return elapsed >= reclaim_stale_after_seconds


class SqlUnitOfWork:
    """One-transaction unit of work over a feedback + knowledge store pair.

    Calling the instance opens a single connection+transaction and yields
    connection-bound stores; the transaction commits on clean exit and rolls back
    on exception. P5.1b uses this unit for adoption-driven knowledge promotion
    (knowledge version bump + optional re-index), not for runtime self-report
    feedback, which is observation-only.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        feedback_store_factory: Callable[[Connection], FeedbackStorePort] | None = None,
        knowledge_store_factory: Callable[[Connection], KnowledgeStorePort] | None = None,
    ) -> None:
        self._engine = engine
        # Default to the plain stores; the composition layer can pass a factory that
        # binds an embedding-aware knowledge store to the connection so adoption
        # promotion re-indexes inside the same transaction.
        self._feedback_factory = feedback_store_factory or SqlFeedbackStore
        self._knowledge_factory = knowledge_store_factory or SqlKnowledgeStore

    @contextmanager
    def __call__(self) -> Iterator[tuple[FeedbackStorePort, KnowledgeStorePort]]:
        conn = self._engine.connect()
        tx = conn.begin()
        try:
            yield self._feedback_factory(conn), self._knowledge_factory(conn)
        except Exception:
            tx.rollback()
            raise
        else:
            tx.commit()
        finally:
            conn.close()


class SqlTraceStore(_SqlStoreBase, TraceStorePort):
    """RunTrace store backed by SQLAlchemy Core (observability v1, AR-20260611)."""

    def save(self, run_trace: RunTrace, *, tenant_id: str = "default") -> None:
        table = schema.run_traces
        payload = mappers.run_trace_to_payload(run_trace)
        with self._write() as conn:
            exists = conn.execute(
                select(table.c.trace_id)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.trace_id == run_trace.trace_id)
            ).fetchone()
            if exists is None:
                conn.execute(
                    table.insert().values(
                        tenant_id=tenant_id,
                        trace_id=run_trace.trace_id,
                        status=run_trace.status,
                        payload=payload,
                    )
                )
            else:
                conn.execute(
                    table.update()
                    .where(table.c.tenant_id == tenant_id)
                    .where(table.c.trace_id == run_trace.trace_id)
                    .values(status=run_trace.status, payload=payload)
                )

    def get(self, trace_id: str, *, tenant_id: str = "default") -> RunTrace | None:
        table = schema.run_traces
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.trace_id == trace_id)
            ).fetchone()
        if row is None:
            return None
        return mappers.run_trace_from_payload(row.payload)

    def all_traces(self, *, tenant_id: str = "default") -> tuple[RunTrace, ...]:
        table = schema.run_traces
        with self._read() as conn:
            rows = conn.execute(
                select(table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .order_by(table.c.trace_id)
            ).fetchall()
        return tuple(mappers.run_trace_from_payload(row.payload) for row in rows)


class SqlPolicyApprovalRecordStore(_SqlStoreBase, PolicyApprovalRecordStorePort):
    """Durable policy-approval-record store (upsert by record_id) backed by
    SQLAlchemy Core. Dialect-portable: tests run on SQLite, production on PostgreSQL.

    Revoked/consumed records are persisted (not deleted) so the decision lineage
    remains auditable. ``is_active`` is computed from the stored status + version.
    """

    def save(self, record: PolicyApprovalRecord) -> PolicyApprovalRecord:
        table = schema.policy_approval_records
        payload = mappers.policy_approval_to_payload(record)
        # tenant scoping uses the record's own tenant_id (default fallback)
        tenant_id = record.tenant_id or "default"
        with self._write() as conn:
            exists = conn.execute(
                select(table.c.record_id)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.record_id == record.record_id)
            ).fetchone()
            if exists is None:
                conn.execute(
                    table.insert().values(
                        tenant_id=tenant_id,
                        record_id=record.record_id,
                        proposal_id=record.proposal_id,
                        policy_version=record.policy_version,
                        status=record.status,
                        payload=payload,
                    )
                )
            else:
                conn.execute(
                    table.update()
                    .where(table.c.tenant_id == tenant_id)
                    .where(table.c.record_id == record.record_id)
                    .values(
                        proposal_id=record.proposal_id,
                        policy_version=record.policy_version,
                        status=record.status,
                        payload=payload,
                    )
                )
        return record

    def _load(self, record_id: str, tenant_id: str) -> PolicyApprovalRecord:
        table = schema.policy_approval_records
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.record_id == record_id)
            ).fetchone()
        if row is None:
            raise KeyError(f"policy approval record not found: {record_id}")
        return mappers.policy_approval_from_payload(row[0])

    def get(self, record_id: str, *, tenant_id: str = "default") -> PolicyApprovalRecord | None:
        table = schema.policy_approval_records
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.record_id == record_id)
            ).fetchone()
        return mappers.policy_approval_from_payload(row[0]) if row is not None else None

    def revoke(
        self, record_id: str, revoked_at: str, *, tenant_id: str = "default"
    ) -> PolicyApprovalRecord:
        record = self.get(record_id, tenant_id=tenant_id)
        if record is None:
            raise KeyError(f"policy approval record not found: {record_id}")
        return self.save(record.revoke(revoked_at))

    def consume(self, record_id: str, *, tenant_id: str = "default") -> PolicyApprovalRecord:
        record = self.get(record_id, tenant_id=tenant_id)
        if record is None:
            raise KeyError(f"policy approval record not found: {record_id}")
        from dataclasses import replace

        return self.save(replace(record, status="consumed"))

    def is_active(self, record_id: str, *, tenant_id: str = "default", policy_version: str) -> bool:
        record = self.get(record_id, tenant_id=tenant_id)
        if record is None:
            return False
        if record.status != "active":
            return False
        return record.policy_version == policy_version

    def active_for_proposal(
        self, proposal_id: str, *, tenant_id: str, policy_version: str
    ) -> PolicyApprovalRecord | None:
        table = schema.policy_approval_records
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload)
                .where(table.c.proposal_id == proposal_id)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.status == "active")
                .where(table.c.policy_version == policy_version)
            ).fetchone()
        return mappers.policy_approval_from_payload(row[0]) if row is not None else None


class SqlWorkflowStore(_SqlStoreBase, WorkflowStorePort):
    def save_workflow(self, tenant_id: str, workflow: ApprovalWorkflow) -> ApprovalWorkflow:
        table = schema.approval_workflows
        payload = mappers.approval_workflow_to_payload(workflow)
        with self._write() as conn:
            exists = conn.execute(
                select(table.c.workflow_id)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.workflow_id == workflow.workflow_id)
            ).fetchone()
            if exists is None:
                conn.execute(
                    table.insert().values(
                        tenant_id=tenant_id,
                        workflow_id=workflow.workflow_id,
                        state=workflow.state,
                        payload=payload,
                    )
                )
            else:
                conn.execute(
                    table.update()
                    .where(table.c.tenant_id == tenant_id)
                    .where(table.c.workflow_id == workflow.workflow_id)
                    .values(state=workflow.state, payload=payload)
                )
        return workflow

    def get_workflow(self, tenant_id: str, workflow_id: str) -> ApprovalWorkflow | None:
        table = schema.approval_workflows
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.workflow_id == workflow_id)
            ).fetchone()
        return mappers.approval_workflow_from_payload(row[0]) if row is not None else None

    def list_workflows(self, tenant_id: str) -> tuple[ApprovalWorkflow, ...]:
        table = schema.approval_workflows
        with self._read() as conn:
            rows = conn.execute(
                select(table.c.payload).where(table.c.tenant_id == tenant_id)
            ).fetchall()
        return tuple(mappers.approval_workflow_from_payload(row[0]) for row in rows)

    def save_instance(self, record: WorkflowInstanceRecord) -> WorkflowInstanceRecord:
        table = schema.workflow_instances
        payload = mappers.workflow_instance_record_to_payload(
            tenant_id=record.tenant_id,
            instance=record.instance,
            assigned_role=record.assigned_role,
            step_started_at=record.step_started_at,
        )
        inst = record.instance
        with self._write() as conn:
            exists = conn.execute(
                select(table.c.instance_id)
                .where(table.c.tenant_id == record.tenant_id)
                .where(table.c.instance_id == inst.instance_id)
            ).fetchone()
            values = {
                "workflow_id": inst.workflow_id,
                "proposal_id": inst.proposal_id,
                "state": inst.state,
                "payload": payload,
            }
            if exists is None:
                conn.execute(
                    table.insert().values(
                        tenant_id=record.tenant_id,
                        instance_id=inst.instance_id,
                        **values,
                    )
                )
            else:
                conn.execute(
                    table.update()
                    .where(table.c.tenant_id == record.tenant_id)
                    .where(table.c.instance_id == inst.instance_id)
                    .values(**values)
                )
        return record

    def get_instance(self, tenant_id: str, instance_id: str) -> WorkflowInstanceRecord | None:
        table = schema.workflow_instances
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.instance_id == instance_id)
            ).fetchone()
        if row is None:
            return None
        fields = mappers.workflow_instance_record_from_payload(row[0])
        return WorkflowInstanceRecord(**fields)


class SqlAutoExecutionPolicyStore(_SqlStoreBase, AutoExecutionPolicyStorePort):
    def save(self, policy: AutoExecutionPolicy) -> AutoExecutionPolicy:
        table = schema.auto_execution_policies
        payload = mappers.auto_execution_policy_to_payload(policy)
        tenant_id = policy.tenant_id or "default"
        with self._write() as conn:
            exists = conn.execute(
                select(table.c.tenant_id).where(table.c.tenant_id == tenant_id)
            ).fetchone()
            if exists is None:
                conn.execute(
                    table.insert().values(
                        tenant_id=tenant_id,
                        policy_version=policy.version,
                        payload=payload,
                    )
                )
            else:
                conn.execute(
                    table.update()
                    .where(table.c.tenant_id == tenant_id)
                    .values(policy_version=policy.version, payload=payload)
                )
        return policy

    def get(self, tenant_id: str) -> AutoExecutionPolicy | None:
        table = schema.auto_execution_policies
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload).where(table.c.tenant_id == tenant_id)
            ).fetchone()
        return mappers.auto_execution_policy_from_payload(row[0]) if row is not None else None
