"""knowledge_index: projected columns + embedding for hybrid retrieval

Revision ID: 0003_knowledge_index
Revises: 0002_jsonb_gin
Create Date: 2026-06-07

Matches agent_os_persistence.schema.knowledge_index. `embedding` is generic JSON for
portability; a later PG-only migration can swap it to a pgvector `vector` column + HNSW.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_knowledge_index"
down_revision: str | None = "0002_jsonb_gin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_index",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_trace_id", sa.String(), nullable=False),
        sa.Column("asset_id", sa.String(), nullable=False),
        sa.Column("metric_name", sa.String()),
        sa.Column("owner", sa.String()),
        sa.Column("risk_level", sa.String()),
        sa.Column("lifecycle_state", sa.String()),
        sa.Column("outcome", sa.String()),
        sa.Column("outcome_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("asset_payload", sa.JSON(), nullable=False),
    )
    # One current row per trace (mirrors knowledge_assets).
    op.create_index(
        "ix_knowledge_index_source_trace_id", "knowledge_index", ["source_trace_id"], unique=True
    )
    for col in ("metric_name", "owner", "risk_level", "lifecycle_state", "outcome"):
        op.create_index(f"ix_knowledge_index_{col}", "knowledge_index", [col])


def downgrade() -> None:
    for col in ("metric_name", "owner", "risk_level", "lifecycle_state", "outcome"):
        op.drop_index(f"ix_knowledge_index_{col}", table_name="knowledge_index")
    op.drop_index("ix_knowledge_index_source_trace_id", table_name="knowledge_index")
    op.drop_table("knowledge_index")
