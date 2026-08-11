"""knowledge_index pgvector column + HNSW index (PostgreSQL only)

Revision ID: 0004_pgvector_embedding
Revises: 0003_knowledge_index
Create Date: 2026-06-07

Prepares the schema for pushing vector similarity into the DB via pgvector. Adds the
`vector` extension, an `embedding_vec` column, and an HNSW index for cosine distance.
PostgreSQL-only (no-op elsewhere). This is a PERFORMANCE path: the JSON `embedding`
column remains the portable source the shared scorer reads; a future SqlKnowledgeRetriever
variant can rank with `embedding_vec <=> :q` + HNSW. Populating `embedding_vec` (backfill
+ write-side dual-write) is a follow-up once running on a pgvector-enabled PostgreSQL.

Because pgvector is performance-only, a PostgreSQL WITHOUT the extension installed must
still migrate to head: upgrade() checks pg_available_extensions and skips (with a warning)
when `vector` is unavailable, instead of breaking the whole migration chain. Enabling
pgvector later = install the extension, `alembic downgrade 0003 && alembic upgrade head`
(or run the backfill script once it exists).

The embedding dimensions must match the configured embedder (default 64).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from agent_os_persistence.schema import DEFAULT_EMBEDDING_DIMENSIONS
from alembic import op
from sqlalchemy import text

revision: str = "0004_pgvector_embedding"
down_revision: str | None = "0003_knowledge_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must match the deployed embedder dimension (see schema.DEFAULT_EMBEDDING_DIMENSIONS
# and RuntimeFactoryConfig.embedding_dimensions).
_DIMENSIONS = DEFAULT_EMBEDDING_DIMENSIONS


def _vector_available(bind) -> bool:
    row = bind.execute(
        text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
    ).fetchone()
    return row is not None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if not _vector_available(bind):
        # pgvector is a performance-only path: its absence must not block the chain.
        logging.getLogger("alembic.runtime.migration").warning(
            "pgvector extension not available on this PostgreSQL; skipping embedding_vec "
            "column + HNSW index (retrieval falls back to the portable JSON embedding). "
            "To enable later: install pgvector, then `alembic downgrade 0003` + `upgrade head`."
        )
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(f"ALTER TABLE knowledge_index ADD COLUMN embedding_vec vector({_DIMENSIONS})")
    op.execute(
        "CREATE INDEX ix_knowledge_index_embedding_vec_hnsw "
        "ON knowledge_index USING hnsw (embedding_vec vector_cosine_ops)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_knowledge_index_embedding_vec_hnsw")
    op.execute("ALTER TABLE knowledge_index DROP COLUMN IF EXISTS embedding_vec")
