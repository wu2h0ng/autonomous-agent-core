"""promote payload columns to JSONB + add GIN indexes (PostgreSQL only)

Revision ID: 0002_jsonb_gin
Revises: 0001_initial
Create Date: 2026-06-06

The base schema uses generic JSON for SQLite/portability. On PostgreSQL, JSONB +
GIN indexes enable efficient containment/key queries on the payload. This is a
PG-only refinement: a no-op on other dialects (e.g. SQLite in tests).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_jsonb_gin"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("feedback_events", "knowledge_assets", "state_snapshots", "approval_records")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in _TABLES:
        op.alter_column(
            table,
            "payload",
            type_=postgresql.JSONB(astext_type=sa.Text()),
            postgresql_using="payload::jsonb",
        )
        op.create_index(f"ix_{table}_payload_gin", table, ["payload"], postgresql_using="gin")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in _TABLES:
        op.drop_index(f"ix_{table}_payload_gin", table_name=table)
        op.alter_column(
            table,
            "payload",
            type_=sa.JSON(),
            postgresql_using="payload::json",
        )
