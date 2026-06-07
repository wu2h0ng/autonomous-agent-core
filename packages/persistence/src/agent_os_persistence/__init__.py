"""Persistent (SQLAlchemy Core) implementations of the OS Core store Ports.

This package is an adapter layer: it depends on OS Core's Port ABCs and the
public contracts, never the other way around (OS Core stays infra-independent).
Repositories take an injected SQLAlchemy ``Engine`` and are dialect-portable
(SQLite for tests, PostgreSQL for production). Schema migrations are managed by
Alembic (see ``packages/persistence/alembic``).
"""

from __future__ import annotations

from sqlalchemy import Engine

from .repositories import (
    SqlApprovalStore,
    SqlFeedbackStore,
    SqlKnowledgeStore,
    SqlSnapshotStore,
    SqlUnitOfWork,
)
from .retrieval import EmbeddingKnowledgeStore, SqlKnowledgeRetriever, default_projector
from .schema import (
    approval_records,
    feedback_events,
    knowledge_assets,
    knowledge_index,
    metadata,
    state_snapshots,
)

__all__ = [
    "EmbeddingKnowledgeStore",
    "SqlApprovalStore",
    "SqlFeedbackStore",
    "SqlKnowledgeRetriever",
    "SqlKnowledgeStore",
    "SqlSnapshotStore",
    "SqlUnitOfWork",
    "approval_records",
    "create_all",
    "default_projector",
    "feedback_events",
    "knowledge_assets",
    "knowledge_index",
    "metadata",
    "state_snapshots",
]


def create_all(engine: Engine) -> None:
    """Create all persistence tables on ``engine`` if they do not exist.

    Convenience for tests and first-run/dev bootstrap. Production schema changes
    go through Alembic migrations, not this call.
    """
    metadata.create_all(engine)
