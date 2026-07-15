"""Persistent (SQLAlchemy Core) implementations of the OS Core store Ports.

This package is an adapter layer: it depends on OS Core's Port ABCs and the
public contracts, never the other way around (OS Core stays infra-independent).
Repositories take an injected SQLAlchemy ``Engine`` and are dialect-portable
(SQLite for tests, PostgreSQL for production). Schema migrations are managed by
Alembic (see ``packages/persistence/alembic``).
"""

from __future__ import annotations

from sqlalchemy import Engine

from .dashboard import SqlDashboardStore
from .repositories import (
    SqlActionRecordStore,
    SqlAgentCheckpointStore,
    SqlApprovalContextStore,
    SqlApprovalStore,
    SqlPolicyApprovalRecordStore,
    SqlAutoExecutionPolicyStore,
    SqlWorkflowStore,
    SqlFeedbackStore,
    SqlKnowledgeStore,
    SqlReportSnapshotStore,
    SqlSnapshotStore,
    SqlTraceStore,
    SqlUnitOfWork,
)
from .retrieval import EmbeddingKnowledgeStore, SqlKnowledgeRetriever, default_projector
from .schema import (
    agent_runtime_checkpoints,
    action_records,
    approval_operation_contexts,
    approval_records,
    dashboards,
    feedback_events,
    knowledge_assets,
    knowledge_index,
    metadata,
    report_snapshot_events,
    report_snapshots,
    run_traces,
    state_snapshots,
    tenants,
    usage_events,
)
from .tenant import SqlTenantStore
from .usage import SqlUsageStore

__all__ = [
    "EmbeddingKnowledgeStore",
    "SqlActionRecordStore",
    "SqlAgentCheckpointStore",
    "SqlApprovalStore",
    "SqlApprovalContextStore",
    "SqlPolicyApprovalRecordStore",
    "SqlAutoExecutionPolicyStore",
    "SqlWorkflowStore",
    "SqlDashboardStore",
    "SqlFeedbackStore",
    "SqlKnowledgeRetriever",
    "SqlKnowledgeStore",
    "SqlReportSnapshotStore",
    "SqlSnapshotStore",
    "SqlTenantStore",
    "SqlTraceStore",
    "SqlUnitOfWork",
    "SqlUsageStore",
    "agent_runtime_checkpoints",
    "action_records",
    "approval_operation_contexts",
    "approval_records",
    "create_all",
    "dashboards",
    "default_projector",
    "feedback_events",
    "knowledge_assets",
    "knowledge_index",
    "metadata",
    "report_snapshot_events",
    "report_snapshots",
    "run_traces",
    "state_snapshots",
    "tenants",
    "usage_events",
]


def create_all(engine: Engine) -> None:
    """Create all persistence tables on ``engine`` if they do not exist.

    Convenience for tests and first-run/dev bootstrap. Production schema changes
    go through Alembic migrations, not this call.
    """
    metadata.create_all(engine)
