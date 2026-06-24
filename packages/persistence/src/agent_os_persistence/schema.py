"""SQLAlchemy Core schema for the persistent store adapters.

A generic ``JSON`` column carries the serialized contract; lookup keys are
promoted to indexed columns. Generic ``JSON`` keeps the schema portable so the
repositories run on SQLite (unit tests) and PostgreSQL (production) from the same
code. On PostgreSQL the column can be migrated to ``JSONB`` via Alembic for
indexing/operators; that is a PG-only refinement, not required for correctness.
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, Float, Integer, MetaData, String, Table

# Single source of truth for the embedding dimension. The pgvector column migration
# (0004) and the runtime factory's default embedder MUST agree with this value; if a
# deployment uses a different embedder dimension, the migration must be regenerated.
DEFAULT_EMBEDDING_DIMENSIONS = 64

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

# Agent Runtime checkpoints: keyed by run_id and storing the canonical
# RunStateSnapshot payload. The indexed columns are audit/search affordances; the
# fingerprint-bearing payload remains the source of truth for resume validation.
agent_runtime_checkpoints = Table(
    "agent_runtime_checkpoints",
    metadata,
    Column("run_id", String, primary_key=True),
    Column("trace_id", String, index=True, nullable=False),
    Column("step_id", String, index=True, nullable=False),
    Column("status", String, index=True, nullable=False),
    Column("payload", JSON, nullable=False),
)

# Connector-side action records: the durable side-effect ledger for the
# action_record connector. Approval context persistence proves command recovery;
# this table proves the connector write target and idempotency map survive a
# later runtime instance.
action_records = Table(
    "action_records",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("record_id", String, unique=True, nullable=False),
    Column("operation_id", String, index=True, nullable=False),
    Column("action_type", String, nullable=False),
    Column("idempotency_key", String, unique=True, index=True),
    Column("payload", JSON, nullable=False),
)

# Approval records: one row per approval_id (upserted as the lifecycle advances).
approval_records = Table(
    "approval_records",
    metadata,
    Column("approval_id", String, primary_key=True),
    Column("proposal_id", String, index=True, nullable=False),
    Column("payload", JSON, nullable=False),
)

# Approval-bound operation contexts: one row per approval_id. This is the
# cross-process resume payload for approval execution; approval_records remains
# the decision lifecycle store.
approval_operation_contexts = Table(
    "approval_operation_contexts",
    metadata,
    Column("approval_id", String, primary_key=True),
    Column("proposal_id", String, index=True, nullable=False),
    Column("operation_id", String, index=True, nullable=False),
    Column("trace_id", String, index=True, nullable=False),
    Column("status", String, index=True, nullable=False, default="pending"),
    Column("payload", JSON, nullable=False),
)

# Knowledge retrieval index: projected, indexed columns for structured filtering
# (never JSON scans) + a stored embedding and content for hybrid ranking. Maintained
# by the EmbeddingKnowledgeStore decorator. `id` (autoincrement) doubles as the recency
# key; `asset_id` is the logical unique key (re-index = delete+insert -> newer id).
# `embedding` is a generic JSON list for portability/tests; a PG-only migration can
# later swap it to a pgvector `vector` column + HNSW for ANN performance.
knowledge_index = Table(
    "knowledge_index",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    # Keyed by source_trace_id (one current row per trace, mirroring knowledge_assets);
    # asset_id changes across versions and is stored for reference only.
    Column("source_trace_id", String, unique=True, nullable=False),
    Column("asset_id", String, nullable=False),
    Column("metric_name", String, index=True),
    Column("owner", String, index=True),
    Column("risk_level", String, index=True),
    Column("lifecycle_state", String, index=True),
    Column("outcome", String, index=True),
    Column("outcome_score", Float, nullable=False, default=0.0),
    Column("content", String, nullable=False),
    Column("embedding", JSON, nullable=False),
    Column("asset_payload", JSON, nullable=False),
)

# Run traces (observability v1, AR-20260611): one row per trace_id, persisted on
# BOTH exits of run() ("ok" answers and "blocked" refusals), so any run is
# auditable after the fact. Events + telemetry are stored as the canonical
# serialized payload.
run_traces = Table(
    "run_traces",
    metadata,
    Column("trace_id", String, primary_key=True),
    Column("status", String, index=True, nullable=False),
    Column("payload", JSON, nullable=False),
)
