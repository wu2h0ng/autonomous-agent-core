"""usage_events: tenant-scoped quota accounting

Revision ID: 0010_usage_events
Revises: 0009_report_snapshots
Create Date: 2026-07-06

Append-only table used by ``QuotaGate`` to enforce per-tenant operation limits.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_usage_events"
down_revision: str | None = "0009_report_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_usage_events_tenant_id", "usage_events", ["tenant_id"])
    op.create_index("ix_usage_events_operation", "usage_events", ["operation"])
    op.create_index("ix_usage_events_recorded_at", "usage_events", ["recorded_at"])


def downgrade() -> None:
    op.drop_index("ix_usage_events_recorded_at", table_name="usage_events")
    op.drop_index("ix_usage_events_operation", table_name="usage_events")
    op.drop_index("ix_usage_events_tenant_id", table_name="usage_events")
    op.drop_table("usage_events")
