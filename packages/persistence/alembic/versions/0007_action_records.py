"""action_records: durable connector-side action ledger

Revision ID: 0007_action_records
Revises: 0006_approval_operation_contexts
Create Date: 2026-06-23

Stores the action_record connector's side-effect ledger and idempotency keys so
approval-resume execution remains observable across runtime instances. This is a
connector-side durability slice, not a product release or a claim of external
business-system exactly-once semantics.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_action_records"
down_revision: str | None = "0006_approval_operation_contexts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("record_id", sa.String(), nullable=False),
        sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("record_id", name="uq_action_records_record_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_action_records_idempotency_key"),
    )
    op.create_index("ix_action_records_operation_id", "action_records", ["operation_id"])
    op.create_index("ix_action_records_idempotency_key", "action_records", ["idempotency_key"])


def downgrade() -> None:
    op.drop_index("ix_action_records_idempotency_key", table_name="action_records")
    op.drop_index("ix_action_records_operation_id", table_name="action_records")
    op.drop_table("action_records")
