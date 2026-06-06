"""PostgreSQL/SQLAlchemy-Core implementations of the OS Core store Ports.

These adapters live OUTSIDE OS Core (which only owns the Port ABCs). They take an
injected SQLAlchemy ``Engine`` and persist the contracts via the schema/mappers,
preserving the same semantics as the in-memory stores (dedup on source_trace_id,
version bump on supersede, append-only feedback). The code is dialect-portable:
tests run it on SQLite; production wires a PostgreSQL engine.
"""

from __future__ import annotations

from collections import Counter

from agent_os_contracts import FeedbackEvent, KnowledgeAsset, StateSnapshot
from agent_os_core import (
    ApprovalRecord,
    ApprovalStorePort,
    FeedbackStorePort,
    KnowledgeStorePort,
    SnapshotStore,
)
from sqlalchemy import Engine, select

from . import mappers, schema


class SqlFeedbackStore(FeedbackStorePort):
    """Append-only feedback store backed by SQLAlchemy Core."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record(self, event: FeedbackEvent) -> FeedbackEvent:
        with self._engine.begin() as conn:
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
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return tuple(mappers.feedback_from_payload(row[0]) for row in rows)

    def all_events(self) -> tuple[FeedbackEvent, ...]:
        stmt = select(schema.feedback_events.c.payload).order_by(schema.feedback_events.c.id)
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return tuple(mappers.feedback_from_payload(row[0]) for row in rows)

    def outcome_counts(self) -> dict[str, int]:
        return dict(Counter(event.outcome for event in self.all_events()))


class SqlKnowledgeStore(KnowledgeStorePort):
    """Knowledge-asset store with dedup/versioning backed by SQLAlchemy Core."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def register(self, asset: KnowledgeAsset) -> KnowledgeAsset:
        key = asset.source_trace_id
        if key is None:
            raise ValueError("KnowledgeAsset.source_trace_id is required for dedup")
        table = schema.knowledge_assets
        with self._engine.begin() as conn:
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
        with self._engine.begin() as conn:
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
        with self._engine.connect() as conn:
            row = conn.execute(
                select(table.c.payload).where(table.c.source_trace_id == trace_id)
            ).fetchone()
        return mappers.knowledge_from_payload(row[0]) if row is not None else None

    def version_of(self, trace_id: str) -> int:
        table = schema.knowledge_assets
        with self._engine.connect() as conn:
            row = conn.execute(
                select(table.c.version).where(table.c.source_trace_id == trace_id)
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def all_assets(self) -> tuple[KnowledgeAsset, ...]:
        table = schema.knowledge_assets
        with self._engine.connect() as conn:
            rows = conn.execute(select(table.c.payload)).fetchall()
        return tuple(mappers.knowledge_from_payload(row[0]) for row in rows)


class SqlSnapshotStore(SnapshotStore):
    """State-snapshot store backed by SQLAlchemy Core."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save(self, snapshot: StateSnapshot) -> StateSnapshot:
        table = schema.state_snapshots
        payload = mappers.snapshot_to_payload(snapshot)
        with self._engine.begin() as conn:
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
        with self._engine.connect() as conn:
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
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return tuple(mappers.snapshot_from_payload(row[0]) for row in rows)


class SqlApprovalStore(ApprovalStorePort):
    """Approval-record store (upsert by approval_id) backed by SQLAlchemy Core."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save(self, record: ApprovalRecord) -> ApprovalRecord:
        table = schema.approval_records
        payload = mappers.approval_to_payload(record)
        with self._engine.begin() as conn:
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
        with self._engine.connect() as conn:
            row = conn.execute(
                select(table.c.payload).where(table.c.approval_id == approval_id)
            ).fetchone()
        return mappers.approval_from_payload(row[0]) if row is not None else None
