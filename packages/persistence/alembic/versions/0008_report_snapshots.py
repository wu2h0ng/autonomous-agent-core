"""report_snapshots: durable read-side report projections

Revision ID: 0008_report_snapshots
Revises: 0007_action_records
Create Date: 2026-06-24

Stores already-built internal/external report projections for side-effect-free
report reads across app/runtime instances. This is report-read durability only;
it does not claim external release, external-system exactly-once, or automatic
business action execution.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_report_snapshots"
down_revision: str | None = "0007_action_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_snapshots",
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("audience", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("trace_id", "audience", name="pk_report_snapshots"),
    )
    op.create_index("ix_report_snapshots_trace_id", "report_snapshots", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_report_snapshots_trace_id", table_name="report_snapshots")
    op.drop_table("report_snapshots")
