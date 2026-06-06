"""SQLAlchemy Core schema for the persistent store adapters.

A generic ``JSON`` column carries the serialized contract; lookup keys are
promoted to indexed columns. Generic ``JSON`` keeps the schema portable so the
repositories run on SQLite (unit tests) and PostgreSQL (production) from the same
code. On PostgreSQL the column can be migrated to ``JSONB`` via Alembic for
indexing/operators; that is a PG-only refinement, not required for correctness.
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, Integer, MetaData, String, Table

metadata = MetaData()

# Feedback events: append-only; a surrogate autoincrement id preserves insertion
# order and allows duplicate (deterministic) feedback_ids, matching the in-memory store.
feedback_events = Table(
    "feedback_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("feedback_id", String, nullable=False),
    Column("trace_id", String, index=True, nullable=False),
    Column("payload", JSON, nullable=False),
)

# Knowledge assets: one row per source_trace_id (dedup key) with a version counter.
knowledge_assets = Table(
    "knowledge_assets",
    metadata,
    Column("source_trace_id", String, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("payload", JSON, nullable=False),
)

# State snapshots: keyed by snapshot_id, indexed by operation_id.
state_snapshots = Table(
    "state_snapshots",
    metadata,
    Column("snapshot_id", String, primary_key=True),
    Column("operation_id", String, index=True, nullable=False),
    Column("payload", JSON, nullable=False),
)
