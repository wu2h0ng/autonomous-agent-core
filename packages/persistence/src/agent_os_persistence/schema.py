"""SQLAlchemy Core schema for the persistent store adapters.

A generic ``JSON`` column carries the serialized contract; lookup keys are
promoted to indexed columns. Generic ``JSON`` keeps the schema portable so the
repositories run on SQLite (unit tests) and PostgreSQL (production) from the same
code. On PostgreSQL the column can be migrated to ``JSONB`` via Alembic for
indexing/operators; that is a PG-only refinement, not required for correctness.

Every table is tenant-scoped via an indexed ``tenant_id`` column. Natural-key
tables include ``tenant_id`` in the primary key so lookups become
``(tenant_id, primary_key)``; autoincrement tables keep ``tenant_id`` as an
indexed filter column.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)

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
    Column("tenant_id", String, index=True, nullable=False, default="default"),
    Column("feedback_id", String, nullable=False),
    Column("trace_id", String, index=True, nullable=False),
    Column("payload", JSON, nullable=False),
)

# Knowledge assets: one row per source_trace_id (dedup key) with a version counter.
# Tenant-scoped: primary key is (tenant_id, source_trace_id).
knowledge_assets = Table(
    "knowledge_assets",
    metadata,
    Column("tenant_id", String, primary_key=True, default="default"),
    Column("source_trace_id", String, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("payload", JSON, nullable=False),
)

# State snapshots: keyed by snapshot_id, indexed by operation_id.
# Tenant-scoped: primary key is (tenant_id, snapshot_id).
state_snapshots = Table(
    "state_snapshots",
    metadata,
    Column("tenant_id", String, primary_key=True, default="default"),
    Column("snapshot_id", String, primary_key=True),
    Column("operation_id", String, index=True, nullable=False),
    Column("payload", JSON, nullable=False),
)

# Agent Runtime checkpoints: keyed by run_id and storing the canonical
# RunStateSnapshot payload. The indexed columns are audit/search affordances; the
# fingerprint-bearing payload remains the source of truth for resume validation.
# Tenant-scoped: primary key is (tenant_id, run_id).
agent_runtime_checkpoints = Table(
    "agent_runtime_checkpoints",
    metadata,
    Column("tenant_id", String, primary_key=True, default="default"),
    Column("run_id", String, primary_key=True),
    Column("trace_id", String, index=True, nullable=False),
    Column("step_id", String, index=True, nullable=False),
    Column("status", String, index=True, nullable=False),
    Column("payload", JSON, nullable=False),
)

# User-facing report snapshots: keyed by trace_id + audience. These are already-built
# projections for read-side report retrieval; they never re-run SQL or actions.
# Tenant-scoped: primary key is (tenant_id, trace_id, audience).
report_snapshots = Table(
    "report_snapshots",
    metadata,
    Column("tenant_id", String, primary_key=True, default="default"),
    Column("trace_id", String, primary_key=True),
    Column("audience", String, primary_key=True),
    Column("payload", JSON, nullable=False),
)

# Append-only external report revision feed. The global sequence provides stable
# pagination while every read remains tenant filtered and the HTTP cursor binds
# the sequence to a server-configured tenant.
report_snapshot_events = Table(
    "report_snapshot_events",
    metadata,
    Column("sequence", Integer, primary_key=True, autoincrement=True),
    Column("tenant_id", String, index=True, nullable=False),
    Column("event_id", String, unique=True, nullable=False),
    Column("trace_id", String, index=True, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("report_digest", String(64), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "trace_id",
        "revision",
        name="uq_report_snapshot_events_tenant_trace_revision",
    ),
)

# Connector-side action records: the durable side-effect ledger for the
# action_record connector. Approval context persistence proves command recovery;
# this table proves the connector write target and idempotency map survive a
# later runtime instance.
action_records = Table(
    "action_records",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant_id", String, index=True, nullable=False, default="default"),
    Column("record_id", String, unique=True, nullable=False),
    Column("operation_id", String, index=True, nullable=False),
    Column("action_type", String, nullable=False),
    Column("idempotency_key", String, unique=True, index=True),
    Column("payload", JSON, nullable=False),
)

# Approval records: one row per approval_id (upserted as the lifecycle advances).
# Tenant-scoped: primary key is (tenant_id, approval_id).
approval_records = Table(
    "approval_records",
    metadata,
    Column("tenant_id", String, primary_key=True, default="default"),
    Column("approval_id", String, primary_key=True),
    Column("proposal_id", String, index=True, nullable=False),
    Column("payload", JSON, nullable=False),
)

# Approval-bound operation contexts: one row per approval_id. This is the
# cross-process resume payload for approval execution; approval_records remains
# the decision lifecycle store.
# Tenant-scoped: primary key is (tenant_id, approval_id).
approval_operation_contexts = Table(
    "approval_operation_contexts",
    metadata,
    Column("tenant_id", String, primary_key=True, default="default"),
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
# Tenant-scoped: source_trace_id is unique within a tenant.
knowledge_index = Table(
    "knowledge_index",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant_id", String, index=True, nullable=False, default="default"),
    # Keyed by source_trace_id (one current row per trace, mirroring knowledge_assets);
    # asset_id changes across versions and is stored for reference only.
    Column("source_trace_id", String, nullable=False),
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
# Tenant-scoped: primary key is (tenant_id, trace_id).
run_traces = Table(
    "run_traces",
    metadata,
    Column("tenant_id", String, primary_key=True, default="default"),
    Column("trace_id", String, primary_key=True),
    Column("status", String, index=True, nullable=False),
    Column("payload", JSON, nullable=False),
)

# Usage events: append-only accounting for tenant-scoped quota gating.
# Surrogate autoincrement id preserves insertion order; tenant_id + operation are
# indexed so count(tenant, operation, window) is cheap.
usage_events = Table(
    "usage_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant_id", String, index=True, nullable=False, default="default"),
    Column("operation", String, index=True, nullable=False),
    Column("trace_id", String, nullable=False),
    Column("units", Integer, nullable=False, default=1),
    Column("recorded_at", DateTime, nullable=False),
    Column("payload", JSON, nullable=False, default=dict),
)

# Tenant metadata: minimal provisioning table for the tenant management API.
# tenant_id is the natural primary key; display_name + status support onboarding
# and lifecycle gating. config is a JSON bag for provider/connector defaults.
tenants = Table(
    "tenants",
    metadata,
    Column("tenant_id", String, primary_key=True),
    Column("display_name", String, nullable=False),
    Column("status", String, nullable=False, default="active"),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    Column("config", JSON, nullable=False, default=dict),
)

# Dashboards: tenant-scoped NL Data Product Workspace layouts.
# Primary key is (tenant_id, dashboard_id); cards are stored as JSON payload.
dashboards = Table(
    "dashboards",
    metadata,
    Column("tenant_id", String, primary_key=True, default="default"),
    Column("dashboard_id", String, primary_key=True),
    Column("title", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("payload", JSON, nullable=False),
)

# Policy approval records (ADR-0012 / workstream E): one row per record_id,
# tenant-scoped; payload holds the full frozen record for round-trip.
policy_approval_records = Table(
    "policy_approval_records",
    metadata,
    Column("tenant_id", String, primary_key=True, default="default"),
    Column("record_id", String, primary_key=True),
    Column("proposal_id", String, index=True, nullable=False),
    Column("policy_version", String, index=True, nullable=False),
    Column("status", String, index=True, nullable=False, default="active"),
    Column("payload", JSON, nullable=False),
)

# Multi-step BPM workflows (workstream D): tenant-scoped workflow definitions.
approval_workflows = Table(
    "approval_workflows",
    metadata,
    Column("tenant_id", String, primary_key=True, default="default"),
    Column("workflow_id", String, primary_key=True),
    Column("state", String, index=True, nullable=False, default="draft"),
    Column("payload", JSON, nullable=False),
)

# Running workflow instances with assignment metadata for timeout checks.
workflow_instances = Table(
    "workflow_instances",
    metadata,
    Column("tenant_id", String, primary_key=True, default="default"),
    Column("instance_id", String, primary_key=True),
    Column("workflow_id", String, index=True, nullable=False),
    Column("proposal_id", String, index=True, nullable=False),
    Column("state", String, index=True, nullable=False, default="pending"),
    Column("payload", JSON, nullable=False),
)

# Tenant auto-execution policies (workstream E).
auto_execution_policies = Table(
    "auto_execution_policies",
    metadata,
    Column("tenant_id", String, primary_key=True, default="default"),
    Column("policy_version", String, index=True, nullable=False),
    Column("payload", JSON, nullable=False),
)
