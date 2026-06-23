"""approval_operation_contexts: durable approval-resume payloads

Revision ID: 0006_approval_operation_contexts
Revises: 0005_run_traces
Create Date: 2026-06-23

Stores the exact operation/evidence/action context captured when a run creates a
pending approval, so a later process can resume approved execution by approval_id
without client replay. Approval lifecycle remains in approval_records.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_approval_operation_contexts"
down_revision: str | None = "0005_run_traces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_operation_contexts",
        sa.Column("approval_id", sa.String(), primary_key=True),
        sa.Column("proposal_id", sa.String(), nullable=False),
        sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_approval_operation_contexts_proposal_id",
        "approval_operation_contexts",
        ["proposal_id"],
    )
    op.create_index(
        "ix_approval_operation_contexts_operation_id",
        "approval_operation_contexts",
        ["operation_id"],
    )
    op.create_index(
        "ix_approval_operation_contexts_trace_id",
        "approval_operation_contexts",
        ["trace_id"],
    )
    op.create_index(
        "ix_approval_operation_contexts_status",
        "approval_operation_contexts",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_approval_operation_contexts_status", table_name="approval_operation_contexts")
    op.drop_index(
        "ix_approval_operation_contexts_trace_id", table_name="approval_operation_contexts"
    )
    op.drop_index(
        "ix_approval_operation_contexts_operation_id",
        table_name="approval_operation_contexts",
    )
    op.drop_index(
        "ix_approval_operation_contexts_proposal_id",
        table_name="approval_operation_contexts",
    )
    op.drop_table("approval_operation_contexts")
