"""initial persistence schema (feedback_events, knowledge_assets, state_snapshots)

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-06

Matches agent_os_persistence.schema. Uses generic JSON for portability; a PG-only
refinement to JSONB (with GIN indexes) can be a later migration.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("feedback_id", sa.String(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_feedback_events_trace_id", "feedback_events", ["trace_id"])

    op.create_table(
        "knowledge_assets",
        sa.Column("source_trace_id", sa.String(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )

    op.create_table(
        "state_snapshots",
        sa.Column("snapshot_id", sa.String(), primary_key=True),
        sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_state_snapshots_operation_id", "state_snapshots", ["operation_id"])


def downgrade() -> None:
    op.drop_index("ix_state_snapshots_operation_id", table_name="state_snapshots")
    op.drop_table("state_snapshots")
    op.drop_table("knowledge_assets")
    op.drop_index("ix_feedback_events_trace_id", table_name="feedback_events")
    op.drop_table("feedback_events")
