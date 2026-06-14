"""PostgreSQL/SQLAlchemy-Core implementations of the OS Core store Ports.

These adapters live OUTSIDE OS Core (which only owns the Port ABCs). They take an
injected SQLAlchemy *bind* — an ``Engine`` (each call its own transaction) or a
``Connection`` (transaction owned by a caller, e.g. a unit of work). This lets the
same store classes run standalone or inside :class:`SqlUnitOfWork` for atomic
multi-store writes. The code is dialect-portable: tests run it on SQLite;
production wires a PostgreSQL engine.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from agent_os_contracts import FeedbackEvent, KnowledgeAsset, RunTrace, StateSnapshot
from agent_os_core import (
    ApprovalRecord,
    ApprovalStorePort,
    FeedbackStorePort,
    KnowledgeStorePort,
    SnapshotStore,
    TraceStorePort,
)
from sqlalchemy import Connection, Engine, select

from . import mappers, schema


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
            row = conn.execute(
                select(table.c.version).where(table.c.source_trace_id == key)
            ).fetchone()
            if row is None:
                conn.execute(table.insert().values(source_trace_id=key, version=1, payload=payload))
            else:
                conn.execute(
                    table.update()
                    .where(table.c.source_trace_id == key)
                    .values(version=row[0] + 1, payload=payload)
                )
        return asset

    def get_by_trace(self, trace_id: str) -> KnowledgeAsset | None:
        table = schema.knowledge_assets
        with self._read() as conn:
            row = conn.execute(
                select(table.c.payload).where(table.c.source_trace_id == trace_id)
            ).fetchone()
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
