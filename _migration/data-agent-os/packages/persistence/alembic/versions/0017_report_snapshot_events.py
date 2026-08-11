"""append-only external report snapshot event feed

Revision ID: 0017_report_snapshot_events
Revises: 0016_legacy_table_tenant_scoping
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_report_snapshot_events"
down_revision: str | None = "0016_legacy_table_tenant_scoping"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_snapshot_events",
        sa.Column("sequence", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False, unique=True),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("report_digest", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "trace_id",
            "revision",
            name="uq_report_snapshot_events_tenant_trace_revision",
        ),
    )
    op.create_index(
        "ix_report_snapshot_events_tenant_id",
        "report_snapshot_events",
        ["tenant_id"],
    )
    op.create_index(
        "ix_report_snapshot_events_trace_id",
        "report_snapshot_events",
        ["trace_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_report_snapshot_events_trace_id",
        table_name="report_snapshot_events",
    )
    op.drop_index(
        "ix_report_snapshot_events_tenant_id",
        table_name="report_snapshot_events",
    )
    op.drop_table("report_snapshot_events")
