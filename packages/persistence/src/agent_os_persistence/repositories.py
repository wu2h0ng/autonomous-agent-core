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

from agent_os_contracts import FeedbackEvent, KnowledgeAsset, RunTrace, StateSnapshot
from agent_os_core import (
    ApprovalContextStorePort,
    ApprovalOperationContext,
    ApprovalRecord,
    ApprovalStorePort,
    FeedbackStorePort,
    KnowledgeStorePort,
    SnapshotStore,
    TraceStorePort,
)
from sqlalchemy import Connection, Engine, select

from . import mappers, schema


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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

    def record(self, event: FeedbackEvent) -> FeedbackEvent:
        with self._write() as conn:
            conn.execute(
                schema.feedback_events.insert().values(
                    feedback_id=event.feedback_id,
                    trace_id=event.trace_id,
                    payload=mappers.feedback_to_payload(event),
                )
            )
        return event

    def get_by_trace(self, trace_id: str) -> tuple[FeedbackEvent, ...]:
        stmt = (
            select(schema.feedback_events.c.payload)
            .where(schema.feedback_events.c.trace_id == trace_id)
            .order_by(schema.feedback_events.c.id)
        )
        with self._read() as conn:
            rows = conn.execute(stmt).fetchall()
        return tuple(mappers.feedback_from_payload(row[0]) for row in rows)

    def all_events(self) -> tuple[FeedbackEvent, ...]:
        stmt = select(schema.feedback_events.c.payload).order_by(schema.feedback_events.c.id)
        with self._read() as conn:
            rows = conn.execute(stmt).fetchall()
        return tuple(mappers.feedback_from_payload(row[0]) for row in rows)

    def outcome_counts(self) -> dict[str, int]:
        return dict(Counter(event.outcome for event in self.all_events()))


class SqlKnowledgeStore(_SqlStoreBase, KnowledgeStorePort):
    """Knowledge-asset store with dedup/versioning backed by SQLAlchemy Core."""

    def register(self, asset: KnowledgeAsset) -> KnowledgeAsset:
        key = asset.source_trace_id
        if key is None:
            raise ValueError("KnowledgeAsset.source_trace_id is required for dedup")
        table = schema.knowledge_assets
        with self._write() as conn:
            existing = conn.execute(
                select(table.c.payload).where(table.c.source_trace_id == key)
            ).fetchone()
            if existing is not None:
                return mappers.knowledge_from_payload(existing[0])
            conn.execute(
                table.insert().values(
                    source_trace_id=key,
                    version=1,
                    payload=mappers.knowledge_to_payload(asset),
                )
            )
        return asset

    def register_version(self, asset: KnowledgeAsset) -> KnowledgeAsset:
        key = asset.source_trace_id
        if key is None:
            raise ValueError("KnowledgeAsset.source_trace_id is required for dedup")
        table = schema.knowledge_assets
        payload = mappers.knowledge_to_payload(asset)
        with self._write() as conn:
            updated = conn.execute(
                table.update()
                .where(table.c.source_trace_id == key)
                .values(version=table.c.version + 1, payload=payload)
            )
            if updated.rowcount == 0:
                conn.execute(table.insert().values(source_trace_id=key, version=1, payload=payload))
        return asset

    def get_by_trace(self, trace_id: str) -> KnowledgeAsset | None:
        table = schema.knowledge_assets
        with self._read() as conn:
            stmt = select(table.c.payload).where(table.c.source_trace_id == trace_id)
            if isinstance(self._bind, Connection):
                stmt = stmt.with_for_update()
            row = conn.execute(stmt).fetchone()
        return mappers.knowledge_from_payload(row[0]) if row is not None else None

    def version_of(self, trace_id: str) -> int:
        table = schema.knowledge_assets
        with self._read() as conn:
            row = conn.execute(
                select(table.c.version).where(table.c.source_trace_id == trace_id)
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def all_assets(self) -> tuple[KnowledgeAsset, ...]:
        table = schema.knowledge_assets
        with self._read() as conn:
            rows = conn.execute(select(table.c.payload)).fetchall()
        return tuple(mappers.knowledge_from_payload(row[0]) for row in rows)


class SqlSnapshotStore(_SqlStoreBase, SnapshotStore):
    """State-snapshot store backed by SQLAlchemy Core."""

    def save(self, snapshot: StateSnapshot) -> StateSnapshot:
        table = schema.state_snapshots
        payload = mappers.snapshot_to_payload(snapshot)
        with self._write() as conn:
            exists = conn.execute(
                select(table.c.snapshot_id).where(table.c.snapshot_id == snapshot.snapshot_id)
            ).fetchone()
            if exists is None:
                conn.execute(
                    table.insert().values(
                        snapshot_id=snapshot.snapshot_id,
                        operation_id=snapshot.operation_id,
                        payload=payload,
                    )
                )
            else:
                conn.execute(
                    table.update()
                    .where(table.c.snapshot_id == snapshot.snapshot_id)
                    .values(operation_id=snapshot.operation_id, payload=payload)
                )
        return snapshot

    def get(self, snapshot_id: str) -> StateSnapshot | None:
        table = schema.state_snapshots
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload).where(table.c.snapshot_id == snapshot_id)
            ).fetchone()
        return mappers.snapshot_from_payload(row[0]) if row is not None else None

    def list_for_operation(self, operation_id: str) -> tuple[StateSnapshot, ...]:
        table = schema.state_snapshots
        stmt = (
            select(table.c.payload)
            .where(table.c.operation_id == operation_id)
            .order_by(table.c.snapshot_id)
        )
        with self._read() as conn:
            rows = conn.execute(stmt).fetchall()
        return tuple(mappers.snapshot_from_payload(row[0]) for row in rows)


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
                    select(table.c.id, table.c.payload).where(
                        table.c.idempotency_key == idempotency_key
                    )
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

    def records(self) -> tuple[dict[str, object], ...]:
        table = schema.action_records
        with self._read() as conn:
            rows = conn.execute(select(table.c.payload).order_by(table.c.id)).fetchall()
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
    ) -> dict[str, object]:
        table = schema.action_records
        with self._write() as conn:
            row = conn.execute(
                select(table.c.id, table.c.payload).where(table.c.record_id == record_id)
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

    def snapshot_state(self) -> dict[str, object]:
        return {"records": [copy.deepcopy(record) for record in self.records()]}

    def restore(self, state_payload: dict[str, object]) -> None:
        table = schema.action_records
        raw_records = state_payload.get("records") or []
        records = [copy.deepcopy(dict(record)) for record in raw_records]
        rollback_operation_id = state_payload.get("rollback_operation_id")
        with self._write() as conn:
            if rollback_operation_id is None:
                conn.execute(table.delete())
            else:
                snapshot_record_ids = {record["record_id"] for record in records}
                conn.execute(
                    table.delete()
                    .where(table.c.operation_id == rollback_operation_id)
                    .where(table.c.record_id.not_in(snapshot_record_ids))
                )
                return
            for record in records:
                conn.execute(
                    table.insert().values(
                        record_id=record["record_id"],
                        operation_id=record["operation_id"],
                        action_type=record["action_type"],
                        idempotency_key=record.get("idempotency_key"),
                        payload=copy.deepcopy(record),
                    )
                )


class SqlApprovalStore(_SqlStoreBase, ApprovalStorePort):
    """Approval-record store (upsert by approval_id) backed by SQLAlchemy Core."""

    def save(self, record: ApprovalRecord) -> ApprovalRecord:
        table = schema.approval_records
        payload = mappers.approval_to_payload(record)
        with self._write() as conn:
            exists = conn.execute(
                select(table.c.approval_id).where(table.c.approval_id == record.approval_id)
            ).fetchone()
            if exists is None:
                conn.execute(
                    table.insert().values(
                        approval_id=record.approval_id,
                        proposal_id=record.proposal_id,
                        payload=payload,
                    )
                )
            else:
                conn.execute(
                    table.update()
                    .where(table.c.approval_id == record.approval_id)
                    .values(proposal_id=record.proposal_id, payload=payload)
                )
        return record

    def get(self, approval_id: str) -> ApprovalRecord | None:
        table = schema.approval_records
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload).where(table.c.approval_id == approval_id)
            ).fetchone()
        return mappers.approval_from_payload(row[0]) if row is not None else None


class SqlApprovalContextStore(_SqlStoreBase, ApprovalContextStorePort):
    """Approval-resume context store backed by SQLAlchemy Core."""

    def __init__(self, bind: Engine | Connection, *, clock: Callable[[], datetime] | None = None):
        super().__init__(bind)
        self._clock = clock or _utc_now

    def save(self, context: ApprovalOperationContext) -> ApprovalOperationContext:
        table = schema.approval_operation_contexts
        payload = mappers.approval_context_to_payload(context)
        with self._write() as conn:
            exists = conn.execute(
                select(table.c.approval_id).where(table.c.approval_id == context.approval_id)
            ).fetchone()
            values = {
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
                    .where(table.c.approval_id == context.approval_id)
                    .values(**values)
                )
        return context

    def get(self, approval_id: str) -> ApprovalOperationContext | None:
        table = schema.approval_operation_contexts
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload).where(table.c.approval_id == approval_id)
            ).fetchone()
        return mappers.approval_context_from_payload(row[0]) if row is not None else None

    def claim(
        self,
        approval_id: str,
        *,
        reclaim_stale_after_seconds: float | None = None,
    ) -> ApprovalOperationContext | None:
        table = schema.approval_operation_contexts
        with self._write() as conn:
            row = conn.execute(
                select(table.c.status, table.c.payload).where(table.c.approval_id == approval_id)
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

    def release_claim(self, approval_id: str) -> None:
        table = schema.approval_operation_contexts
        with self._write() as conn:
            row = conn.execute(
                select(table.c.payload).where(table.c.approval_id == approval_id)
            ).fetchone()
            payload = copy.deepcopy(dict(row.payload)) if row is not None else {}
            payload.pop("_claim", None)
            conn.execute(
                table.update()
                .where(table.c.approval_id == approval_id)
                .where(table.c.status == "executing")
                .values(status="pending", payload=payload)
            )

    def delete(self, approval_id: str) -> None:
        table = schema.approval_operation_contexts
        with self._write() as conn:
            conn.execute(table.delete().where(table.c.approval_id == approval_id))

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

    def save(self, run_trace: RunTrace) -> None:
        table = schema.run_traces
        payload = mappers.run_trace_to_payload(run_trace)
        with self._write() as conn:
            exists = conn.execute(
                select(table.c.trace_id).where(table.c.trace_id == run_trace.trace_id)
            ).fetchone()
            if exists is None:
                conn.execute(
                    table.insert().values(
                        trace_id=run_trace.trace_id,
                        status=run_trace.status,
                        payload=payload,
                    )
                )
            else:
                conn.execute(
                    table.update()
                    .where(table.c.trace_id == run_trace.trace_id)
                    .values(status=run_trace.status, payload=payload)
                )

    def get(self, trace_id: str) -> RunTrace | None:
        table = schema.run_traces
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload).where(table.c.trace_id == trace_id)
            ).fetchone()
        if row is None:
            return None
        return mappers.run_trace_from_payload(row.payload)
