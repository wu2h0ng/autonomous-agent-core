"""add immutable report payloads and per-trace revision state

Revision ID: 0018_report_snapshot_event_payloads
Revises: 0017_report_snapshot_events
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_report_snapshot_event_payloads"
down_revision: str | None = "0017_report_snapshot_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Intermediate 0017 deployments may already contain events whose historical
    # payload cannot be reconstructed from the mutable current snapshot. Keep
    # those rows intact and nullable so upgrade is lossless; readers fail closed
    # if they encounter such a legacy event.
    op.add_column(
        "report_snapshot_events",
        sa.Column("report_payload", sa.JSON(), nullable=True),
    )
    op.create_table(
        "report_snapshot_event_revisions",
        sa.Column("tenant_id", sa.String(), primary_key=True),
        sa.Column("trace_id", sa.String(), primary_key=True),
        sa.Column("last_revision", sa.Integer(), nullable=False),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO report_snapshot_event_revisions
                (tenant_id, trace_id, last_revision)
            SELECT tenant_id, trace_id, MAX(revision)
            FROM report_snapshot_events
            GROUP BY tenant_id, trace_id
            """
        )
    )


def downgrade() -> None:
    op.drop_table("report_snapshot_event_revisions")
    op.drop_column("report_snapshot_events", "report_payload")
